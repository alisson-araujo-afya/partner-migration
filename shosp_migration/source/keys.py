from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class OrgKey:
    prk: int


@dataclass(frozen=True, order=True)
class ClientScopedKey:
    cliente_id: int
    prk: int


@dataclass(frozen=True, order=True)
class GroupKey:
    grupo_id: int
