from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

import pytest
from typer.testing import CliRunner

from shosp_migration.cli import app as cli
from shosp_migration.config import Settings
from shosp_migration.source.models import (
    ShospCliente,
    ShospGroupItems,
    ShospGroupWithItems,
    ShospPrescricaoItem,
    ShospProntuarioGrupo,
    WaveCounts,
)
from shosp_migration.source.waves import WaveScope

PII = "Fulano de Tal"
runner = CliRunner()


class FakeReader:
    def __init__(self) -> None:
        self.scopes: list[WaveScope] = []

    async def count(self, scope: WaveScope) -> WaveCounts:
        self.scopes.append(scope)
        return WaveCounts(
            total_contas=1,
            total_medicos=2,
            total_pacientes=3,
            total_grupos=4,
            grupos_ativos=4,
            grupos_inativos=0,
            grupos_mistos=0,
            clientes_status_indefinido=5,
        )

    async def organizations(
        self, scope: WaveScope, batch_size: int
    ) -> AsyncIterator[list[ShospCliente]]:
        self.scopes.append(scope)
        yield [ShospCliente(prk=10, nome=PII, ativo=True, data_inativacao=None)]

    async def prescription_groups(
        self, scope: WaveScope, batch_size: int
    ) -> AsyncIterator[list[ShospGroupWithItems]]:
        self.scopes.append(scope)
        group = ShospProntuarioGrupo(
            grupo_id=7,
            cliente_id=10,
            prestador_id=3,
            paciente_id=4,
            grupo_data=date(2020, 1, 1),
            grupo_ativo=True,
        )
        item = ShospPrescricaoItem(grupo_id=7, prk=1, item=PII, folha="1", codigo_memed=None)
        yield [ShospGroupWithItems(group=group, items=ShospGroupItems(prescricao=(item,)))]


@pytest.fixture
def fake_reader(monkeypatch: pytest.MonkeyPatch) -> FakeReader:
    reader = FakeReader()
    settings = Settings(
        shosp_db_url="postgresql://u:topsecret@h/db",
        batch_size_organization=1,
        batch_size_physician=1,
        batch_size_patient=1,
        batch_size_prescription=1,
        source_statement_timeout_seconds=1,
    )

    @asynccontextmanager
    async def open_reader(_: Settings) -> AsyncIterator[FakeReader]:
        yield reader

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "open_reader", open_reader)
    return reader


@pytest.mark.parametrize(
    "args",
    [
        ["count", "--group-status", "ativo"],
        ["preview", "--group-status", "ativo", "--entity", "org"],
        ["count", "--wave", "legado-ativos"],
        ["count", "--wave", "onda-x", "--group-status", "ativo"],
    ],
)
def test_requires_wave_and_group_status(fake_reader: FakeReader, args: list[str]) -> None:
    result = runner.invoke(cli.app, args)

    assert result.exit_code == 2
    assert fake_reader.scopes == []


def test_rejects_vaccines_in_memed_wave(fake_reader: FakeReader) -> None:
    result = runner.invoke(
        cli.app, ["count", "--wave", "memed-ativos", "--group-status", "ativo", "--with-vaccines"]
    )

    assert result.exit_code == 2
    assert fake_reader.scopes == []


def test_count_prints_volume(fake_reader: FakeReader) -> None:
    result = runner.invoke(
        cli.app,
        ["count", "--wave", "legado-inativos", "--group-status", "todos", "--with-vaccines"],
    )

    assert result.exit_code == 0, result.output
    assert "total_grupos: 4" in result.output
    assert "clientes_status_indefinido: 5" in result.output
    assert fake_reader.scopes[0].reads_vaccines


def test_preview_prints_only_technical_ids(fake_reader: FakeReader) -> None:
    orgs = runner.invoke(
        cli.app,
        ["preview", "--wave", "legado-ativos", "--group-status", "ativo", "--entity", "org"],
    )
    groups = runner.invoke(
        cli.app,
        [
            "preview",
            "--wave",
            "legado-ativos",
            "--group-status",
            "ativo",
            "--entity",
            "prescription",
        ],
    )

    assert orgs.exit_code == 0, orgs.output
    assert orgs.output.strip() == "prk=10"
    assert "grupo_id=7" in groups.output and "prescricao=1" in groups.output
    assert PII not in orgs.output + groups.output


def test_invalid_configuration_exits_1_without_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)

    result = runner.invoke(cli.app, ["count", "--wave", "legado-ativos", "--group-status", "ativo"])

    assert result.exit_code == 1
    assert "SHOSP_DB_URL" in result.output


def test_connection_failure_exits_1_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        shosp_db_url="postgresql://u:topsecret@127.0.0.1:1/db",
        batch_size_organization=1,
        batch_size_physician=1,
        batch_size_patient=1,
        batch_size_prescription=1,
        source_statement_timeout_seconds=1,
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    result = runner.invoke(cli.app, ["count", "--wave", "legado-ativos", "--group-status", "ativo"])

    assert result.exit_code == 1
    assert "falha ao acessar a SHOSP" in result.output
    assert "topsecret" not in result.output
