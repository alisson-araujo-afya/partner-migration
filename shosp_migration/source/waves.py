from dataclasses import dataclass
from enum import Enum, StrEnum


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


class Wave(str, Enum):
    LEGADO_INATIVOS = "legado-inativos", WaveOrigin.LEGADO, ClientStatus.INATIVO
    LEGADO_ATIVOS = "legado-ativos", WaveOrigin.LEGADO, ClientStatus.ATIVO
    MEMED_INATIVOS = "memed-inativos", WaveOrigin.MEMED, ClientStatus.INATIVO
    MEMED_ATIVOS = "memed-ativos", WaveOrigin.MEMED, ClientStatus.ATIVO

    _origin: WaveOrigin
    _client_status: ClientStatus

    def __new__(cls, slug: str, origin: WaveOrigin, status: ClientStatus) -> "Wave":
        obj = str.__new__(cls, slug)
        obj._value_ = slug
        obj._origin = origin
        obj._client_status = status
        return obj

    @property
    def client_status(self) -> ClientStatus:
        return self._client_status

    @property
    def origin(self) -> WaveOrigin:
        return self._origin


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
