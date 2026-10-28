import hashlib
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from shosp_migration.source.keys import ClientScopedKey, GroupKey, OrgKey


def _pii(default: object = None) -> object:
    return Field(default=default, repr=False)


class _SourceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ShospCliente(_SourceModel):
    prk: int
    nome: str | None = _pii()
    ativo: bool
    data_inativacao: date | None

    @property
    def key(self) -> OrgKey:
        return OrgKey(self.prk)


class ShospPrestador(_SourceModel):
    cliente_id: int
    prk: int
    nome: str | None = _pii()
    razao_social: str | None = _pii()
    cpf: str | None = _pii()
    cns: str | None = _pii()
    email: str | None = _pii()
    conselho_numero: str | None = _pii()
    conselho_codigo: str | None
    conselho_uf: str | None
    ativo: bool | None

    @property
    def key(self) -> ClientScopedKey:
        return ClientScopedKey(self.cliente_id, self.prk)


class ShospPaciente(_SourceModel):
    cliente_id: int
    prk: int
    nome: str | None = _pii()
    apelido: str | None = _pii()
    nome_mae: str | None = _pii()
    cpf: str | None = _pii()
    data_nascimento: date | None = _pii()
    sexo: str | None = _pii()
    email: str | None = _pii()
    celular: str | None = _pii()
    telefone: str | None = _pii()
    cep: str | None = _pii()
    logradouro: str | None = _pii()
    numero: str | None = _pii()
    bairro: str | None = _pii()
    complemento: str | None = _pii()
    cidade: str | None = _pii()
    uf: str | None = _pii()

    @property
    def key(self) -> ClientScopedKey:
        return ClientScopedKey(self.cliente_id, self.prk)


class ShospProntuarioGrupo(_SourceModel):
    grupo_id: int
    cliente_id: int
    prestador_id: int
    paciente_id: int
    grupo_data: date
    grupo_ativo: bool

    @property
    def key(self) -> GroupKey:
        return GroupKey(self.grupo_id)


class ShospPrescricaoItem(_SourceModel):
    grupo_id: int
    prk: int
    item: str | None = _pii()
    quantidade: str | None = _pii()
    nr_quantidade: str | None = _pii()
    forma: str | None = _pii()
    dosagem: str | None = _pii()
    via: str | None = _pii()
    frequencia: str | None = _pii()
    duracao: str | None = _pii()
    observacao: str | None = _pii()
    folha: str | None
    codigo_memed: str | None


class ShospExameItem(_SourceModel):
    grupo_id: int
    prk: int
    nome_procedimento: str | None = _pii()
    orientacao_procedimento: str | None = _pii()
    qtd: Decimal | None = _pii()
    nr_folha: Decimal | None


class ShospVacinaItem(_SourceModel):
    grupo_id: int
    paciente_id: int
    descricao: str | None = _pii()
    status: str | None
    data_solicitacao: date | None
    data_vacina: date | None
    lote: str | None = _pii()
    local: str | None = _pii()

    @property
    def source_id(self) -> str:
        parts = (
            self.paciente_id,
            self.descricao,
            self.status,
            self.data_solicitacao,
            self.data_vacina,
            self.lote,
            self.local,
        )
        raw = "\x1f".join("\x00" if part is None else str(part) for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ShospGroupItems(_SourceModel):
    prescricao: tuple[ShospPrescricaoItem, ...] = ()
    exames: tuple[ShospExameItem, ...] = ()
    vacinas: tuple[ShospVacinaItem, ...] = ()


class ShospGroupWithItems(_SourceModel):
    group: ShospProntuarioGrupo
    items: ShospGroupItems

    @property
    def key(self) -> GroupKey:
        return self.group.key


class VaccineCounts(_SourceModel):
    vinculadas: int
    vinculadas_fora_do_escopo: int
    ambiguas: int
    sem_grupo: int


class WaveCounts(_SourceModel):
    total_contas: int
    total_medicos: int
    total_pacientes: int
    total_grupos: int
    grupos_ativos: int
    grupos_inativos: int
    grupos_mistos: int
    clientes_status_indefinido: int
    vacinas: VaccineCounts | None = None
