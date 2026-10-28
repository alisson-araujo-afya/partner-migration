import pytest
from pydantic import ValidationError

from shosp_migration.config import Entity, Settings

BASE = {
    "SHOSP_DB_URL": "postgresql://reader:s3cr3t@localhost:5435/db",
    "BATCH_SIZE_ORGANIZATION": "10",
    "BATCH_SIZE_PHYSICIAN": "20",
    "BATCH_SIZE_PATIENT": "30",
    "BATCH_SIZE_PRESCRIPTION": "40",
    "SOURCE_STATEMENT_TIMEOUT_SECONDS": "60",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> pytest.MonkeyPatch:
    monkeypatch.chdir(tmp_path)
    for key, value in BASE.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_loads_from_env(env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert settings.batch_size_for(Entity.ORGANIZATION) == 10
    assert settings.batch_size_for(Entity.PHYSICIAN) == 20
    assert settings.batch_size_for(Entity.PATIENT) == 30
    assert settings.batch_size_for(Entity.PRESCRIPTION) == 40
    assert settings.include_vaccines is False


@pytest.mark.parametrize("missing", ["SHOSP_DB_URL", "BATCH_SIZE_PATIENT", "SOURCE_STATEMENT_TIMEOUT_SECONDS"])
def test_required_without_default(env: pytest.MonkeyPatch, missing: str) -> None:
    env.delenv(missing)

    with pytest.raises(ValidationError):
        Settings()


def test_rejects_non_positive_batch(env: pytest.MonkeyPatch) -> None:
    env.setenv("BATCH_SIZE_ORGANIZATION", "0")

    with pytest.raises(ValidationError):
        Settings()


def test_strips_jdbc_prefix(env: pytest.MonkeyPatch) -> None:
    env.setenv("SHOSP_DB_URL", "jdbc:postgresql://localhost:5435/dbpgshosp_dev")

    assert Settings().shosp_db_url.get_secret_value() == "postgresql://localhost:5435/dbpgshosp_dev"


def test_repr_hides_dsn(env: pytest.MonkeyPatch) -> None:
    settings = Settings()

    assert "s3cr3t" not in repr(settings)
    assert "s3cr3t" not in str(settings.model_dump())
