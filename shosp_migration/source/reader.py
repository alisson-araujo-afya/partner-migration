import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

import asyncpg
import structlog
from pydantic import BaseModel

from shosp_migration.config import Entity, Settings
from shosp_migration.source.connection import SourcePool
from shosp_migration.source.keys import ClientScopedKey, GroupKey, OrgKey
from shosp_migration.source.models import (
    ShospCliente,
    ShospExameItem,
    ShospGroupItems,
    ShospGroupWithItems,
    ShospPaciente,
    ShospPrescricaoItem,
    ShospPrestador,
    ShospProntuarioGrupo,
    ShospVacinaItem,
    VaccineCounts,
    WaveCounts,
)
from shosp_migration.source.sql_registry import SqlRegistry, default_registry
from shosp_migration.source.waves import WaveOrigin, WaveScope

NO_KEY = -1

log = structlog.get_logger(__name__)


class SourceReader:
    def __init__(
        self, pool: SourcePool, settings: Settings, registry: SqlRegistry | None = None
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._registry = registry or default_registry()

    def organizations(
        self, scope: WaveScope, after: OrgKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospCliente]]:
        def keyset(last: OrgKey | None) -> dict[str, object]:
            return {
                "min_cliente": NO_KEY if last is None else last.prk + 1,
                "after_grupo": NO_KEY,
            }

        return self._paginate(
            "organizations", Entity.ORGANIZATION, scope, after, batch_size, keyset, ShospCliente
        )

    def physicians(
        self, scope: WaveScope, after: ClientScopedKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospPrestador]]:
        return self._paginate(
            "physicians",
            Entity.PHYSICIAN,
            scope,
            after,
            batch_size,
            _client_scoped_keyset,
            ShospPrestador,
        )

    def patients(
        self, scope: WaveScope, after: ClientScopedKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospPaciente]]:
        return self._paginate(
            "patients",
            Entity.PATIENT,
            scope,
            after,
            batch_size,
            _client_scoped_keyset,
            ShospPaciente,
        )

    async def prescription_groups(
        self, scope: WaveScope, after: GroupKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospGroupWithItems]]:
        size = batch_size or self._settings.batch_size_for(Entity.PRESCRIPTION)
        last = after
        while True:
            params = scope.params() | {
                "min_cliente": NO_KEY,
                "after_grupo": NO_KEY if last is None else last.grupo_id,
                "batch": size,
            }
            async with self._pool.readonly() as conn:
                rows = await self._fetch(conn, "prescription_groups", scope, params)
                groups = [ShospProntuarioGrupo.model_validate(dict(row)) for row in rows]
                items = await self._items(conn, scope, [g.grupo_id for g in groups])
            if not groups:
                return
            yield [
                ShospGroupWithItems(group=group, items=items[group.grupo_id]) for group in groups
            ]
            if len(groups) < size:
                return
            last = groups[-1].key

    async def count(self, scope: WaveScope) -> WaveCounts:
        params = scope.params() | {"min_cliente": NO_KEY, "after_grupo": NO_KEY}
        async with self._pool.readonly() as conn:
            (row,) = await self._fetch(conn, "counts", scope, params)
            vaccines = None
            if scope.reads_vaccines:
                (vaccine_row,) = await self._fetch(conn, "counts_vaccines", scope, params)
                vaccines = VaccineCounts.model_validate(dict(vaccine_row))
        return WaveCounts.model_validate(dict(row) | {"vacinas": vaccines})

    async def _paginate[K, M: BaseModel](
        self,
        query: str,
        entity: Entity,
        scope: WaveScope,
        after: K | None,
        batch_size: int | None,
        keyset: Callable[[K | None], Mapping[str, object]],
        model: type[M],
    ) -> AsyncIterator[list[M]]:
        size = batch_size or self._settings.batch_size_for(entity)
        last = after
        while True:
            params = scope.params() | dict(keyset(last)) | {"batch": size}
            async with self._pool.readonly() as conn:
                rows = await self._fetch(conn, query, scope, params)
            if not rows:
                return
            batch = [model.model_validate(dict(row)) for row in rows]
            yield batch
            if len(batch) < size:
                return
            last = batch[-1].key  # type: ignore[attr-defined]

    async def _items(
        self, conn: asyncpg.Connection, scope: WaveScope, grupo_ids: Sequence[int]
    ) -> defaultdict[int, ShospGroupItems]:
        result: defaultdict[int, ShospGroupItems] = defaultdict(ShospGroupItems)
        if not grupo_ids:
            return result
        params = {"grupo_ids": list(grupo_ids)}
        by_group: dict[str, defaultdict[int, list[Any]]] = {
            "prescricao": defaultdict(list),
            "exames": defaultdict(list),
            "vacinas": defaultdict(list),
        }
        sources: list[tuple[str, str, type[Any]]] = []
        if scope.origin is WaveOrigin.LEGADO:
            sources.append(("prescription_items_legacy", "prescricao", ShospPrescricaoItem))
            sources.append(("prescription_items_exam", "exames", ShospExameItem))
            if scope.reads_vaccines:
                sources.append(("prescription_items_vaccine", "vacinas", ShospVacinaItem))
        else:
            sources.append(("prescription_items_memed", "prescricao", ShospPrescricaoItem))

        for query, field, model in sources:
            for row in await self._fetch(conn, query, scope, params):
                item = model.model_validate(dict(row))
                by_group[field][item.grupo_id].append(item)

        for grupo_id in grupo_ids:
            result[grupo_id] = ShospGroupItems(
                prescricao=tuple(by_group["prescricao"][grupo_id]),
                exames=tuple(by_group["exames"][grupo_id]),
                vacinas=tuple(by_group["vacinas"][grupo_id]),
            )
        return result

    async def _fetch(
        self,
        conn: asyncpg.Connection,
        name: str,
        scope: WaveScope,
        params: Mapping[str, object],
    ) -> list[asyncpg.Record]:
        query = self._registry.get(name)
        started = time.perf_counter()
        rows = await conn.fetch(query.text, *query.args(params))
        log.info(
            "source.query",
            query=name,
            wave=scope.wave.value,
            group_status=scope.group_status.value,
            batch_size=params.get("batch"),
            rows=len(rows),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return rows


def _client_scoped_keyset(last: ClientScopedKey | None) -> dict[str, object]:
    if last is None:
        return {
            "min_cliente": NO_KEY,
            "after_cliente": NO_KEY,
            "after_prk": NO_KEY,
            "after_grupo": NO_KEY,
        }
    return {
        "min_cliente": last.cliente_id,
        "after_cliente": last.cliente_id,
        "after_prk": last.prk,
        "after_grupo": NO_KEY,
    }
