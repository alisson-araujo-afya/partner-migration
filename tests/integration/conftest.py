import os
from collections.abc import AsyncIterator

import pytest

from shosp_migration.config import Settings
from shosp_migration.source.connection import SourcePool
from shosp_migration.source.reader import SourceReader


@pytest.fixture(scope="session")
def settings() -> Settings:
    dsn = os.environ.get("SHOSP_TEST_DB_URL")
    if not dsn:
        pytest.skip("SHOSP_TEST_DB_URL não definida")
    return Settings(
        shosp_db_url=dsn,
        batch_size_organization=50,
        batch_size_physician=50,
        batch_size_patient=50,
        batch_size_prescription=50,
        source_statement_timeout_seconds=300,
    )


@pytest.fixture(scope="session")
async def pool(settings: Settings) -> AsyncIterator[SourcePool]:
    async with await SourcePool.open(settings) as source_pool:
        yield source_pool


@pytest.fixture(scope="session")
def reader(pool: SourcePool, settings: Settings) -> SourceReader:
    return SourceReader(pool, settings)
