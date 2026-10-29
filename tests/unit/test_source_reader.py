from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import pytest
from structlog.testing import capture_logs

from shosp_migration.config import Settings
from shosp_migration.source.keys import ClientScopedKey
from shosp_migration.source.models import ShospCliente, ShospPrestador
from shosp_migration.source.reader import NO_KEY, SourceReader, SourceRowError
from shosp_migration.source.waves import GroupStatus, Wave, WaveScope

SCOPE = WaveScope(Wave.LEGADO_INATIVOS, GroupStatus.ATIVO)
PARAMS = {
    "wave_status": "inativo",
    "wave_origin": "legado",
    "group_status": "ativo",
    "min_cliente": -1,
    "max_cliente": 1,
    "after_grupo": -1,
    "batch": 1,
}


class _FailingConnection:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def fetch(self, *_args: Any, **_kwargs: Any) -> list[asyncpg.Record]:
        raise self._error


def _reader() -> SourceReader:
    settings = Settings(
        shosp_db_url="postgresql://u:s@h/db",
        batch_size_organization=1,
        batch_size_physician=1,
        batch_size_patient=1,
        batch_size_prescription=1,
        source_statement_timeout_seconds=1,
    )
    return SourceReader(object(), settings)  # type: ignore[arg-type]


async def test_fetch_logs_sqlstate_and_query_without_exception_text() -> None:
    message = 'column "nome_secreto" of relation "Cliente" does not exist'
    error = asyncpg.UndefinedColumnError(message)
    reader = _reader()

    with capture_logs() as logs, pytest.raises(asyncpg.UndefinedColumnError):
        await reader._fetch(_FailingConnection(error), "organizations", SCOPE, PARAMS)

    failed = [entry for entry in logs if entry.get("event") == "source.query.failed"]
    assert failed == [
        {
            "event": "source.query.failed",
            "log_level": "error",
            "query": "organizations",
            "wave": "legado-inativos",
            "group_status": "ativo",
            "sqlstate": "42703",
        }
    ]
    dumped = str(failed)
    assert message not in dumped
    assert "nome_secreto" not in dumped
    assert "Cliente" not in dumped


def test_invalid_row_logs_fields_without_personal_data() -> None:
    pii = "123.456.789-00 Fulano de Tal"
    reader = _reader()

    with capture_logs() as logs, pytest.raises(SourceRowError) as caught:
        reader._parse(
            ShospCliente,
            {"prk": "não-é-int", "nome": pii, "ativo": True, "data_inativacao": None},
            "organizations",
        )

    assert caught.value.query == "organizations"
    assert caught.value.fields == ("prk",)
    assert pii not in str(caught.value)
    failed = [entry for entry in logs if entry.get("event") == "source.row.invalid"]
    assert failed == [
        {
            "event": "source.row.invalid",
            "log_level": "error",
            "query": "organizations",
            "fields": ["prk"],
        }
    ]
    assert pii not in str(failed)


class _FakePool:
    @asynccontextmanager
    async def readonly(self) -> AsyncIterator[object]:
        yield object()


def _physician(cliente_id: int, prk: int) -> dict[str, object]:
    return {
        "cliente_id": cliente_id,
        "prk": prk,
        "conselho_codigo": None,
        "conselho_uf": None,
        "ativo": True,
    }


def _stub_client_scoped(
    reader: SourceReader, by_client: dict[int, list[dict[str, object]]]
) -> list[tuple[int, int, object]]:
    fetches: list[tuple[int, int, object]] = []

    async def wave_clients(_scope: WaveScope, after: int | None) -> AsyncIterator[int]:
        for cliente_id in by_client:
            if after is None or cliente_id > after:
                yield cliente_id

    async def fetch(
        _conn: object, _name: str, _scope: WaveScope, params: dict[str, object]
    ) -> list[dict[str, object]]:
        cliente_id = int(params["min_cliente"])  # type: ignore[arg-type]
        after_prk = int(params["after_prk"])  # type: ignore[arg-type]
        fetches.append((cliente_id, after_prk, params.get("batch")))
        remaining = [row for row in by_client[cliente_id] if int(row["prk"]) > after_prk]
        batch = params.get("batch")
        if batch is not None:
            remaining = remaining[: int(batch)]
        return remaining

    reader._wave_clients = wave_clients  # type: ignore[method-assign]
    reader._fetch = fetch  # type: ignore[method-assign]
    return fetches


async def test_client_scoped_fetches_each_client_once_and_slices_batches() -> None:
    reader = SourceReader(_FakePool(), _reader()._settings)  # type: ignore[arg-type]
    by_client = {
        10: [_physician(10, prk) for prk in (1, 2, 3, 4, 5)],
        20: [_physician(20, prk) for prk in (8, 9, 11)],
    }
    fetches = _stub_client_scoped(reader, by_client)

    pages = [page async for page in reader.physicians(SCOPE, batch_size=2)]

    assert [(p.cliente_id, p.prk) for page in pages for p in page] == [
        (10, 1),
        (10, 2),
        (10, 3),
        (10, 4),
        (10, 5),
        (20, 8),
        (20, 9),
        (20, 11),
    ]
    assert [len(page) for page in pages] == [2, 2, 2, 2]
    assert fetches == [(10, NO_KEY, None), (20, NO_KEY, None)]
    assert all(isinstance(row, ShospPrestador) for page in pages for row in page)


async def test_client_scoped_resume_fetches_remaining_of_current_client_once() -> None:
    reader = SourceReader(_FakePool(), _reader()._settings)  # type: ignore[arg-type]
    by_client = {
        10: [_physician(10, prk) for prk in (1, 2, 3, 4, 5)],
        20: [_physician(20, prk) for prk in (8, 9)],
    }
    fetches = _stub_client_scoped(reader, by_client)

    pages = [
        page
        async for page in reader.physicians(SCOPE, after=ClientScopedKey(10, 3), batch_size=10)
    ]

    assert [(p.cliente_id, p.prk) for page in pages for p in page] == [
        (10, 4),
        (10, 5),
        (20, 8),
        (20, 9),
    ]
    assert fetches == [(10, 3, None), (20, NO_KEY, None)]
