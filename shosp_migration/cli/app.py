import asyncio
import json
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated, Any

import asyncpg
import typer
from pydantic import BaseModel, ValidationError

from shosp_migration.config import Entity, Settings
from shosp_migration.logging import configure_logging
from shosp_migration.source.connection import SourcePool
from shosp_migration.source.models import ShospGroupWithItems
from shosp_migration.source.reader import SourceReader
from shosp_migration.source.waves import GroupStatus, Wave, WaveOrigin, WaveScope

_READER_METHOD = {
    Entity.ORGANIZATION: "organizations",
    Entity.PHYSICIAN: "physicians",
    Entity.PATIENT: "patients",
    Entity.PRESCRIPTION: "prescription_groups",
}

app = typer.Typer(no_args_is_help=True, help="Migração de dados do parceiro SHOSP.")

WaveOption = Annotated[Wave, typer.Option("--wave", help="Onda da execução (obrigatória).")]
GroupStatusOption = Annotated[
    GroupStatus,
    typer.Option("--group-status", help="Status de ProntuarioGrupo a considerar (obrigatório)."),
]
VaccinesOption = Annotated[
    bool | None,
    typer.Option(
        "--with-vaccines/--without-vaccines",
        help="Lê vacinas (só ondas legadas). Padrão: INCLUDE_VACCINES.",
    ),
]


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


@asynccontextmanager
async def open_reader(settings: Settings) -> AsyncIterator[SourceReader]:
    async with await SourcePool.open(settings) as pool:
        yield SourceReader(pool, settings)


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def _settings() -> Settings:
    try:
        return load_settings()
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]).upper() for error in exc.errors() if error["loc"]})
        raise _fail(f"configuração inválida: {', '.join(fields)}") from None


def _scope(
    settings: Settings, wave: Wave, group_status: GroupStatus, with_vaccines: bool | None
) -> WaveScope:
    if with_vaccines and wave.origin is not WaveOrigin.LEGADO:
        raise typer.BadParameter(
            "vacinas só podem ser lidas nas ondas legadas", param_hint="--with-vaccines"
        )
    include = settings.include_vaccines if with_vaccines is None else with_vaccines
    return WaveScope(wave, group_status, include and wave.origin is WaveOrigin.LEGADO)


def _run(coroutine: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(coroutine)
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        raise _fail(f"falha ao acessar a SHOSP: {type(exc).__name__}") from None


@app.command()
def count(
    wave: WaveOption,
    group_status: GroupStatusOption,
    with_vaccines: VaccinesOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Saída em JSON.")] = False,
) -> None:
    """Mostra o volume da onda, sem transformar nem enviar dados."""
    settings = _settings()
    scope = _scope(settings, wave, group_status, with_vaccines)
    configure_logging()

    async def execute() -> None:
        async with open_reader(settings) as reader:
            counts = await reader.count(scope)
        summary = {
            "wave": scope.wave.value,
            "group_status": scope.group_status.value,
            "include_vaccines": scope.reads_vaccines,
            **counts.model_dump(),
        }
        if as_json:
            typer.echo(json.dumps(summary, ensure_ascii=False))
            return
        for key, value in summary.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    typer.echo(f"{key}.{sub_key}: {sub_value}")
            else:
                typer.echo(f"{key}: {value}")

    _run(execute())


@app.command()
def preview(
    wave: WaveOption,
    group_status: GroupStatusOption,
    entity: Annotated[Entity, typer.Option("--entity", help="Entidade a listar.")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 10,
    with_vaccines: VaccinesOption = None,
) -> None:
    """Lista os primeiros registros da onda, só com IDs técnicos."""
    settings = _settings()
    scope = _scope(settings, wave, group_status, with_vaccines)
    configure_logging()

    async def execute() -> None:
        async with open_reader(settings) as reader:
            read = getattr(reader, _READER_METHOD[entity])
            async for page in read(scope, batch_size=limit):
                for record in page:
                    typer.echo(_technical_row(record))
                break

    _run(execute())


def _technical_row(record: BaseModel) -> str:
    if isinstance(record, ShospGroupWithItems):
        group, items = record.group, record.items
        fields = {
            "grupo_id": group.grupo_id,
            "cliente_id": group.cliente_id,
            "prestador_id": group.prestador_id,
            "paciente_id": group.paciente_id,
            "grupo_ativo": group.grupo_ativo,
            "prescricao": len(items.prescricao),
            "exames": len(items.exames),
            "vacinas": len(items.vacinas),
        }
    else:
        fields = asdict(record.key)  # type: ignore[attr-defined]
    return " ".join(f"{name}={value}" for name, value in fields.items())


def main() -> None:
    app()
