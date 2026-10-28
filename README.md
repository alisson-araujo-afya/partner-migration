# partner-migration

Repository to migrate data from partners.

## SHOSP (`shosp_migration`)

Aplicação de linha de comando que lê a base SHOSP (PostgreSQL) em modo somente leitura, por onda de migração. Documentação em [`DOCS-MIGRACAO-SHOSP/`](DOCS-MIGRACAO-SHOSP/) (PRD-00 a PRD-05) e design em [`docs/superpowers/specs/`](docs/superpowers/specs/).

Esta versão entrega a camada de leitura (PGC-241). Transformação, envio aos destinos e banco de controle ficam para os próximos cards.

### Configuração

```bash
uv sync
cp .env.example .env   # preencha; o .env nao e versionado
```

`SHOSP_DB_URL`, os quatro `BATCH_SIZE_*` e `SOURCE_STATEMENT_TIMEOUT_SECONDS` são obrigatórios e não têm valor padrão.

### Comandos

```bash
# volume da onda, sem transformar nem enviar
uv run shosp-migration count --wave legado-inativos --group-status ativo [--with-vaccines] [--json]

# primeiros registros, so com IDs tecnicos
uv run shosp-migration preview --wave legado-inativos --group-status ativo --entity prescription --limit 5
```

- `--wave`: `legado-inativos`, `legado-ativos`, `memed-inativos` ou `memed-ativos`.
- `--group-status`: `ativo`, `inativo` ou `todos` (`ProntuarioGrupo.status`).
- `--with-vaccines`: só nas ondas legadas; padrão em `INCLUDE_VACCINES` (desligado).

### Uso pelas transformações

```python
async with await SourcePool.open(settings) as pool:
    reader = SourceReader(pool, settings)
    scope = WaveScope(Wave.LEGADO_INATIVOS, GroupStatus.ATIVO)
    async for batch in reader.organizations(scope, after=checkpoint):
        ...  # batch[-1].key e o proximo checkpoint
```

### Testes

```bash
uv run pytest                                   # unitarios
SHOSP_TEST_DB_URL=postgresql://... uv run pytest -m integration
```
