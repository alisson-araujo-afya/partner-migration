from collections.abc import AsyncIterator

import asyncpg
import pytest

from shosp_migration.source.connection import SourcePool
from shosp_migration.source.reader import SourceReader
from shosp_migration.source.sql_registry import default_registry
from shosp_migration.source.waves import GroupStatus, Wave, WaveScope

pytestmark = pytest.mark.integration

LEGADO_ATIVOS = WaveScope(Wave.LEGADO_ATIVOS, GroupStatus.ATIVO)


async def _pages[T](iterator: AsyncIterator[list[T]], limit: int) -> list[list[T]]:
    pages: list[list[T]] = []
    async for page in iterator:
        pages.append(page)
        if len(pages) == limit:
            break
    return pages


async def test_session_is_read_only(pool: SourcePool) -> None:
    async with pool.readonly() as conn:
        assert await conn.fetchval("show default_transaction_read_only") == "on"
        assert await conn.fetchval("show transaction_read_only") == "on"
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await conn.execute('update cliente."Cliente" set nome = nome where false')


async def test_organizations_match_client_status_of_wave(
    reader: SourceReader, pool: SourcePool
) -> None:
    (page,) = await _pages(reader.organizations(LEGADO_ATIVOS), limit=1)

    async with pool.readonly() as conn:
        statuses = await conn.fetch(
            'select distinct status from cliente."Cliente" where prk = any($1)',
            [cliente.prk for cliente in page],
        )
    assert page
    assert all(cliente.ativo for cliente in page)
    assert [row["status"] for row in statuses] == ["1"]


async def test_inactive_wave_groups_belong_to_inactive_clients_with_date(
    reader: SourceReader, pool: SourcePool
) -> None:
    scope = WaveScope(Wave.LEGADO_INATIVOS, GroupStatus.TODOS)
    (page,) = await _pages(reader.prescription_groups(scope), limit=1)

    async with pool.readonly() as conn:
        invalid = await conn.fetchval(
            'select count(*) from cliente."Cliente" '
            "where prk = any($1) and not (status = '0' and \"dataInativacao\" is not null)",
            list({group.group.cliente_id for group in page}),
        )
    assert page
    assert invalid == 0


@pytest.mark.parametrize("entity", ["physicians", "patients", "prescription_groups"])
async def test_keyset_pages_have_no_gaps_or_duplicates(reader: SourceReader, entity: str) -> None:
    read = getattr(reader, entity)

    small_pages = await _pages(read(LEGADO_ATIVOS, batch_size=20), limit=3)
    (single_page,) = await _pages(read(LEGADO_ATIVOS, batch_size=60), limit=1)

    keys = [record.key for page in small_pages for record in page]
    assert [len(page) for page in small_pages] == [20, 20, 20]
    assert keys == [record.key for record in single_page]
    assert keys == sorted(set(keys))


async def test_client_scoped_batches_cross_clients_and_stay_full(reader: SourceReader) -> None:
    pages = await _pages(reader.physicians(LEGADO_ATIVOS, batch_size=30), limit=4)

    keys = [p.key for page in pages for p in page]
    assert all(len(page) == 30 for page in pages[:-1])
    assert len({key.cliente_id for key in keys}) > 1
    assert keys == sorted(set(keys))


async def test_resume_from_key_continues_after_it(reader: SourceReader) -> None:
    (first, second) = await _pages(reader.patients(LEGADO_ATIVOS, batch_size=10), limit=2)

    (resumed,) = await _pages(
        reader.patients(LEGADO_ATIVOS, after=first[-1].key, batch_size=10), limit=1
    )

    assert [p.key for p in resumed] == [p.key for p in second]


async def test_legacy_groups_bring_only_legacy_items_in_source_order(reader: SourceReader) -> None:
    (page,) = await _pages(reader.prescription_groups(LEGADO_ATIVOS, batch_size=200), limit=1)

    assert all(group.group.grupo_ativo for group in page)
    for group in page:
        items = group.items
        assert items.prescricao or items.exames
        assert all(item.codigo_memed is None for item in items.prescricao)
        assert all(item.grupo_id == group.group.grupo_id for item in items.prescricao)
        order = [(item.folha is None, item.folha or "", item.prk) for item in items.prescricao]
        assert order == sorted(order)
        assert not items.vacinas


async def test_memed_groups_bring_only_memed_items(reader: SourceReader) -> None:
    scope = WaveScope(Wave.MEMED_ATIVOS, GroupStatus.ATIVO)
    (page,) = await _pages(reader.prescription_groups(scope, batch_size=200), limit=1)

    assert page
    for group in page:
        assert group.items.prescricao
        assert all(item.codigo_memed for item in group.items.prescricao)
        assert not group.items.exames
        assert not group.items.vacinas


async def test_count_respects_group_status(reader: SourceReader) -> None:
    counts = await reader.count(WaveScope(Wave.LEGADO_ATIVOS, GroupStatus.ATIVO, True))

    assert counts.total_grupos == counts.grupos_ativos > 0
    assert counts.grupos_inativos == 0
    assert counts.total_contas > 0
    assert counts.vacinas is not None


VACCINE_MATCHES = """
select v.ctid::text as vid, array_agg(pg.prk order by pg.prk) as grupos
from prontuario."VacinaPaciente" v
join shosp."Atendimento" a on a."frkPaciente" = v."frkPaciente"
join shosp."ServicoPrestado" sp on sp."frkAtendimento" = a.prk
join prontuario."ProntuarioGrupo" pg on pg."frkServicoPrestado" = sp.prk
                                    and pg.data = v."dataSolicitacao"
where v."codigoAfyaRx" is null
group by v.ctid
having count(*) {condition}
limit 1
"""


async def _vaccine_rows(pool: SourcePool, grupo_ids: list[int]) -> list[asyncpg.Record]:
    query = default_registry().get("prescription_items_vaccine")
    async with pool.readonly() as conn:
        return await conn.fetch(query.text, *query.args({"grupo_ids": grupo_ids}))


async def test_vaccine_with_single_group_is_linked(pool: SourcePool) -> None:
    async with pool.readonly() as conn:
        match = await conn.fetchrow(VACCINE_MATCHES.format(condition="= 1"))
    if match is None:
        pytest.skip("base sem vacina com grupo único")

    rows = await _vaccine_rows(pool, match["grupos"])

    assert rows
    assert {row["grupo_id"] for row in rows} == set(match["grupos"])


async def test_ambiguous_vaccine_is_excluded(pool: SourcePool) -> None:
    async with pool.readonly() as conn:
        match = await conn.fetchrow(VACCINE_MATCHES.format(condition="> 1"))
        if match is None:
            pytest.skip("base sem vacina ambígua")
        vaccine = await conn.fetchrow(
            'select "frkPaciente", descricao, "dataSolicitacao" '
            'from prontuario."VacinaPaciente" where ctid = $1::text::tid',
            match["vid"],
        )

    rows = await _vaccine_rows(pool, match["grupos"])

    assert not [
        row
        for row in rows
        if (row["paciente_id"], row["descricao"], row["data_solicitacao"]) == tuple(vaccine)
    ]
