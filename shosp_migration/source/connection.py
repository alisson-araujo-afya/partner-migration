from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

import asyncpg

from shosp_migration.config import Settings

APPLICATION_NAME = "shosp-migration"


def session_settings(statement_timeout_seconds: int) -> dict[str, str]:
    return {
        "default_transaction_read_only": "on",
        "application_name": APPLICATION_NAME,
        "statement_timeout": str(statement_timeout_seconds * 1000),
        "plan_cache_mode": "force_custom_plan",
    }


class SourcePool:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def open(cls, settings: Settings) -> Self:
        pool = await asyncpg.create_pool(
            dsn=settings.shosp_db_url.get_secret_value(),
            min_size=1,
            max_size=settings.source_pool_max_size,
            server_settings=session_settings(settings.source_statement_timeout_seconds),
        )
        return cls(pool)

    @asynccontextmanager
    async def readonly(self) -> AsyncIterator[asyncpg.Connection]:
        async with self._pool.acquire() as conn, conn.transaction(readonly=True):
            yield conn

    async def close(self) -> None:
        await self._pool.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
