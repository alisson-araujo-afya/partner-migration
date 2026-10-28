from datetime import date

import pytest

from shosp_migration.source.connection import session_settings
from shosp_migration.source.keys import ClientScopedKey, GroupKey, OrgKey
from shosp_migration.source.models import (
    ShospCliente,
    ShospPaciente,
    ShospPrestador,
    ShospProntuarioGrupo,
    ShospVacinaItem,
)

PII = "Maria da Silva 123.456.789-00"


def test_models_expose_keyset_keys() -> None:
    cliente = ShospCliente(prk=7, nome=PII, ativo=False, data_inativacao=date(2020, 1, 1))
    grupo = ShospProntuarioGrupo(
        grupo_id=9,
        cliente_id=7,
        prestador_id=3,
        paciente_id=4,
        grupo_data=date(2020, 1, 1),
        grupo_ativo=True,
    )

    assert cliente.key == OrgKey(7)
    assert grupo.key == GroupKey(9)


def test_repr_hides_personal_fields() -> None:
    models = [
        ShospCliente(prk=1, nome=PII, ativo=True, data_inativacao=None),
        ShospPrestador(
            cliente_id=1,
            prk=2,
            nome=PII,
            razao_social=PII,
            cpf=PII,
            cns=PII,
            email=PII,
            conselho_numero=PII,
            conselho_codigo="CRM",
            conselho_uf="SP",
            ativo=True,
        ),
        ShospPaciente(cliente_id=1, prk=3, nome=PII, cpf=PII, email=PII, cidade=PII),
    ]

    for model in models:
        assert PII not in repr(model)
        assert PII not in str(model)
    assert models[2].key == ClientScopedKey(1, 3)


def _vaccine(**overrides: object) -> ShospVacinaItem:
    fields: dict[str, object] = {
        "grupo_id": 1,
        "paciente_id": 10,
        "descricao": "BCG",
        "status": "A",
        "data_solicitacao": date(2021, 5, 1),
        "data_vacina": None,
        "lote": "L1",
        "local": None,
    }
    return ShospVacinaItem(**(fields | overrides))


def test_vaccine_source_id_is_stable_and_ignores_group() -> None:
    assert _vaccine().source_id == _vaccine(grupo_id=2).source_id
    assert len(_vaccine().source_id) == 64


@pytest.mark.parametrize(
    "override",
    [
        {"paciente_id": 11},
        {"descricao": "Hepatite B"},
        {"status": "B"},
        {"data_solicitacao": date(2021, 5, 2)},
        {"data_vacina": date(2021, 5, 1)},
        {"lote": "L2"},
        {"local": ""},
    ],
)
def test_vaccine_source_id_changes_with_each_field(override: dict[str, object]) -> None:
    assert _vaccine(**override).source_id != _vaccine().source_id


def test_session_is_read_only() -> None:
    settings = session_settings(30)

    assert settings["default_transaction_read_only"] == "on"
    assert settings["statement_timeout"] == "30000"
