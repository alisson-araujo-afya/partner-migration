from dataclasses import dataclass
from enum import StrEnum


class WaveOrigin(StrEnum):
    LEGADO = "legado"
    MEMED = "memed"


class ClientStatus(StrEnum):
    INATIVO = "inativo"
    ATIVO = "ativo"


class GroupStatus(StrEnum):
    ATIVO = "ativo"
    INATIVO = "inativo"
    TODOS = "todos"


class Wave(StrEnum):
    LEGADO_INATIVOS = "legado-inativos"
    LEGADO_ATIVOS = "legado-ativos"
    MEMED_INATIVOS = "memed-inativos"
    MEMED_ATIVOS = "memed-ativos"

    @property
    def client_status(self) -> ClientStatus:
        return ClientStatus(self.value.split("-")[1].removesuffix("s"))

    @property
    def origin(self) -> WaveOrigin:
        return WaveOrigin(self.value.split("-")[0])


@dataclass(frozen=True)
class WaveScope:
    wave: Wave
    group_status: GroupStatus
    include_vaccines: bool = False

    def __post_init__(self) -> None:
        if self.include_vaccines and self.wave.origin is not WaveOrigin.LEGADO:
            raise ValueError("vacinas só podem ser lidas nas ondas legadas")

    @property
    def origin(self) -> WaveOrigin:
        return self.wave.origin

    @property
    def client_status(self) -> ClientStatus:
        return self.wave.client_status

    @property
    def reads_vaccines(self) -> bool:
        return self.include_vaccines and self.origin is WaveOrigin.LEGADO

    def params(self) -> dict[str, object]:
        return {
            "wave_status": self.client_status.value,
            "wave_origin": self.origin.value,
            "group_status": self.group_status.value,
        }
