# PGC-241 Consulta SHOSP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** camada `source/` da aplicação de migração SHOSP: leitura somente leitura, por onda, paginada por keyset, consumida em processo pelas transformações.

**Architecture:** arquivos `.sql` versionados entregues só pelo `sql_registry`; `SourcePool` (asyncpg) com sessões somente leitura; `SourceReader` com iteradores assíncronos por entidade; CLI typer com `count` e `preview`.

**Tech Stack:** Python 3.13, uv, asyncpg, pydantic v2, pydantic-settings, typer, structlog, pytest, pytest-asyncio, ruff.

Spec: [2026-10-28-pgc-241-consulta-shosp-design.md](../specs/2026-10-28-pgc-241-consulta-shosp-design.md).

## Global Constraints

- Python 3.13; pacote `shosp_migration`; entry point `shosp-migration`.
- Nenhum segredo, DSN ou dado da SHOSP em commit (repositório público).
- Tamanhos de lote e `SOURCE_STATEMENT_TIMEOUT_SECONDS` sem valor padrão.
- Toda sessão com `default_transaction_read_only = on` e transação `readonly=True`.
- Campos pessoais com `repr=False`; logs sem PII.

---

### Task 1: Scaffold e configuração

**Files:** `pyproject.toml`, `.gitignore`, `.env.example`, `shosp_migration/__init__.py`, `shosp_migration/config/settings.py`, `shosp_migration/logging.py`, `tests/unit/test_settings.py`

**Produces:** `Settings` com `shosp_db_url: SecretStr`, `batch_size_organization|physician|patient|prescription: PositiveInt`, `source_statement_timeout_seconds: PositiveInt`, `source_pool_max_size: PositiveInt = 4`, `include_vaccines: bool = False`; `Settings.batch_size_for(entity: Entity) -> int`; `configure_logging()`.

- [ ] Teste: settings sem `SHOSP_DB_URL` ou sem lote falha; prefixo `jdbc:` removido; `repr` não mostra o DSN.
- [ ] Implementar e rodar `uv run pytest tests/unit/test_settings.py`.
- [ ] Commit `feat: scaffold project and settings`.

### Task 2: Ondas e registro de SQL

**Files:** `shosp_migration/source/waves.py`, `shosp_migration/source/sql_registry.py`, `shosp_migration/source/sql/*.sql`, `tests/unit/test_waves.py`, `tests/unit/test_sql_registry.py`

**Produces:** `Wave`, `WaveOrigin`, `ClientStatus`, `GroupStatus`, `WaveScope(wave, group_status, include_vaccines)` com `origin`, `client_status`, `reads_vaccines`, `params() -> dict`; `SqlRegistry.get(name) -> Query`; `Query.args(params: Mapping[str, object]) -> list[object]`; `UnknownQueryError`, `MissingParameterError`.

- [ ] Testes: mapeamento das 4 ondas; vacinas em onda Memed recusadas; `:nome -> $n` com reuso do mesmo número, `::cast` preservado, comentário ignorado, CTE injetada, nome desconhecido recusado, parâmetro faltando recusado; todos os arquivos do diretório carregam.
- [ ] Implementar SQL conforme a seção 6 do spec.
- [ ] Rodar `uv run pytest tests/unit`; commit `feat: add wave scope and versioned SHOSP queries`.

### Task 3: Conexão, chaves e modelos

**Files:** `shosp_migration/source/connection.py`, `shosp_migration/source/keys.py`, `shosp_migration/source/models.py`, `tests/unit/test_models.py`

**Produces:** `SourcePool.open(settings)`, `SourcePool.readonly() -> AsyncContextManager[asyncpg.Connection]`, `SourcePool.close()`; `OrgKey(prk)`, `ClientScopedKey(cliente_id, prk)`, `GroupKey(grupo_id)`; `ShospCliente`, `ShospPrestador`, `ShospPaciente`, `ShospProntuarioGrupo`, `ShospPrescricaoItem`, `ShospExameItem`, `ShospVacinaItem` (`source_id`), `ShospGroupItems`, `ShospGroupWithItems`, `WaveCounts`, `VaccineCounts`.

- [ ] Testes: `repr` sem PII; `key` de cada modelo; `source_id` da vacina estável e sensível a cada campo.
- [ ] Implementar; commit `feat: add read-only pool and source models`.

### Task 4: SourceReader

**Files:** `shosp_migration/source/reader.py`, `tests/integration/conftest.py`, `tests/integration/test_reader.py`

**Consumes:** Tasks 2 e 3. **Produces:** `SourceReader(pool, settings, registry=None)` com os métodos da seção 7 do spec.

- [ ] Testes de integração (pulados sem `SHOSP_TEST_DB_URL`): sessão somente leitura; status por onda; 3 páginas pequenas == 1 página do triplo; Memed sem exames; ordem dos itens; vacinas com um único grupo.
- [ ] Implementar; rodar `SHOSP_TEST_DB_URL=... uv run pytest -m integration`; commit `feat: add SourceReader`.

### Task 5: CLI

**Files:** `shosp_migration/cli/app.py`, `tests/unit/test_cli.py`

- [ ] Testes: sem `--wave` sai com código 2; sem `--group-status` sai com 2; `--with-vaccines` em onda Memed sai com 2; erro de configuração sai com 1 sem DSN; `count` e `preview` com reader falso imprimem só IDs e totais.
- [ ] Implementar; commit `feat: add count and preview commands`.

### Task 6: Medição e PR

- [ ] Medir tempo por página de cada entidade em `legado-inativos` contra dev; registrar no PR.
- [ ] `uv run ruff check . && uv run pytest`; push e PR para `main` citando PGC-241.
