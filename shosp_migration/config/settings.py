from enum import StrEnum

from pydantic import PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Entity(StrEnum):
    ORGANIZATION = "org"
    PHYSICIAN = "physician"
    PATIENT = "patient"
    PRESCRIPTION = "prescription"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    shosp_db_url: SecretStr
    batch_size_organization: PositiveInt
    batch_size_physician: PositiveInt
    batch_size_patient: PositiveInt
    batch_size_prescription: PositiveInt
    source_statement_timeout_seconds: PositiveInt
    source_pool_max_size: PositiveInt = 4
    include_vaccines: bool = False

    @field_validator("shosp_db_url", mode="before")
    @classmethod
    def _strip_jdbc_prefix(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                raise ValueError("SHOSP_DB_URL vazia")
            return raw.removeprefix("jdbc:")
        return value

    def batch_size_for(self, entity: Entity) -> int:
        return {
            Entity.ORGANIZATION: self.batch_size_organization,
            Entity.PHYSICIAN: self.batch_size_physician,
            Entity.PATIENT: self.batch_size_patient,
            Entity.PRESCRIPTION: self.batch_size_prescription,
        }[entity]
