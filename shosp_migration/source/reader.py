import time
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import asyncpg
import structlog
from pydantic import BaseModel, ValidationError

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
MAX_KEY = 2**31 - 1
CLIENT_LOOKAHEAD = 100

FULL_WAVE = {"min_cliente": NO_KEY, "max_cliente": MAX_KEY, "after_grupo": NO_KEY}

log = structlog.get_logger(__name__)


class SourceRowError(ValueError):
    def __init__(self, query: str, fields: tuple[str, ...]) -> None:
        self.query = query
        self.fields = fields
        super().__init__("linha inválida na origem")


class SourceReader:
    def __init__(
        self, pool: SourcePool, settings: Settings, registry: SqlRegistry | None = None
    ) -> None:
        self._pool = pool
        self._settings = settings
        self._registry = registry or default_registry()

    async def organizations(
        self, scope: WaveScope, after: OrgKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospCliente]]:
        size = batch_size or self._settings.batch_size_for(Entity.ORGANIZATION)
        last = after
        while True:
            page = await self._organization_page(scope, last, size)
            if not page:
                return
            yield page
            if len(page) < size:
                return
            last = page[-1].key

    def physicians(
        self, scope: WaveScope, after: ClientScopedKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospPrestador]]:
        size = batch_size or self._settings.batch_size_for(Entity.PHYSICIAN)
        return self._client_scoped("physicians", ShospPrestador, scope, after, size)

    def patients(
        self, scope: WaveScope, after: ClientScopedKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospPaciente]]:
        size = batch_size or self._settings.batch_size_for(Entity.PATIENT)
        return self._client_scoped("patients", ShospPaciente, scope, after, size)

    async def prescription_groups(
        self, scope: WaveScope, after: GroupKey | None = None, batch_size: int | None = None
    ) -> AsyncIterator[list[ShospGroupWithItems]]:
        size = batch_size or self._settings.batch_size_for(Entity.PRESCRIPTION)
        last = after
        while True:
            params = (
                scope.params()
                | FULL_WAVE
                | {"after_grupo": NO_KEY if last is None else last.grupo_id, "batch": size}
            )
            async with self._pool.readonly() as conn:
                rows = await self._fetch(conn, "prescription_groups", scope, params)
                groups = [
                    self._parse(ShospProntuarioGrupo, row, "prescription_groups") for row in rows
                ]
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
        params = scope.params() | FULL_WAVE
        async with self._pool.readonly() as conn:
            (row,) = await self._fetch(conn, "counts", scope, params)
            vaccines = None
            if scope.reads_vaccines:
                (vaccine_row,) = await self._fetch(conn, "counts_vaccines", scope, params)
                vaccines = self._parse(VaccineCounts, vaccine_row, "counts_vaccines")
        return self._parse(WaveCounts, dict(row) | {"vacinas": vaccines}, "counts")

    async def _organization_page(
        self, scope: WaveScope, after: OrgKey | None, size: int
    ) -> list[ShospCliente]:
        params = (
            scope.params()
            | FULL_WAVE
            | {"min_cliente": NO_KEY if after is None else after.prk + 1, "batch": size}
        )
        async with self._pool.readonly() as conn:
            rows = await self._fetch(conn, "organizations", scope, params)
        return [self._parse(ShospCliente, row, "organizations") for row in rows]

    async def _wave_clients(self, scope: WaveScope, after: int | None) -> AsyncIterator[int]:
        last = None if after is None else OrgKey(after)
        while True:
            page = await self._organization_page(scope, last, CLIENT_LOOKAHEAD)
            for cliente in page:
                yield cliente.prk
            if len(page) < CLIENT_LOOKAHEAD:
                return
            last = page[-1].key

    async def _client_scoped[M: BaseModel](
        self,
        query: str,
        model: type[M],
        scope: WaveScope,
        after: ClientScopedKey | None,
        size: int,
    ) -> AsyncIterator[list[M]]:
        """Lê um cliente por vez, para que a CTE da onda só avalie os grupos desse cliente.

        Uma query traz todos os registros restantes do cliente; o lote é fatiado em memória.
        """
        buffer: list[M] = []
        clients: AsyncIterator[int]
        if after is None:
            clients = self._wave_clients(scope, None)
            after_prk = NO_KEY
        else:
            clients = _prepend(after.cliente_id, self._wave_clients(scope, after.cliente_id))
            after_prk = after.prk

        async for cliente_id in clients:
            params = scope.params() | {
                "min_cliente": cliente_id,
                "max_cliente": cliente_id,
                "after_grupo": NO_KEY,
                "after_cliente": cliente_id,
                "after_prk": after_prk,
            }
            async with self._pool.readonly() as conn:
                rows = await self._fetch(conn, query, scope, params)
            buffer.extend(self._parse(model, row, query) for row in rows)
            while len(buffer) >= size:
                yield buffer[:size]
                buffer = buffer[size:]
            after_prk = NO_KEY
        if buffer:
            yield buffer

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
                item = self._parse(model, row, query)
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
        try:
            rows = await conn.fetch(query.text, *query.args(params))
        except asyncpg.PostgresError as exc:
            log.error(
                "source.query.failed",
                query=name,
                wave=scope.wave.value,
                group_status=scope.group_status.value,
                sqlstate=exc.sqlstate,
            )
            raise
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

    def _parse[M: BaseModel](self, model: type[M], row: object, query: str) -> M:
        payload = row if isinstance(row, dict) else dict(row)  # type: ignore[arg-type]
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            fields = tuple(".".join(str(part) for part in error["loc"]) for error in exc.errors())
            log.error("source.row.invalid", query=query, fields=list(fields))
            raise SourceRowError(query, fields) from None


async def _prepend(first: int, rest: AsyncIterator[int]) -> AsyncIterator[int]:
    yield first
    async for value in rest:
        yield value
