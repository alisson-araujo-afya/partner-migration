# PGC-241 — Consulta aos dados da SHOSP (design)

Data: 2026-10-28. Card: [PGC-241](https://afya-spm.atlassian.net/browse/PGC-241). História pai: PGC-13.

Base: [PRD-05](../../../DOCS-MIGRACAO-SHOSP/PRD-05-aplicacao-python.md) (seções 2 a 4.1 e 9), [PRD-00](../../../DOCS-MIGRACAO-SHOSP/PRD-00-migracao-shosp.md) (seções 4.1 e 6.5) e [DECISAO-status-cliente-e-vacinas](../../../DOCS-MIGRACAO-SHOSP/DECISAO-status-cliente-e-vacinas.md).

## 1. Escopo

Entra: configuração, conexão somente leitura com o PostgreSQL da SHOSP, queries versionadas por onda, modelos de origem `Shosp*`, o `SourceReader` assíncrono e os comandos `count` e `preview` da CLI.

Fica fora: transformação (PGC-238, PGC-242, PGC-243 e PGC-244), clientes HTTP, banco de controle, orquestração e os comandos `run`, `resume`, `reprocess` e `report`.

As transformações consomem os dados em processo, chamando o `SourceReader`. Não há exportação nem API intermediária.

## 2. Ajustes ao PRD a partir do schema real

Verificado em `dbpgshosp_dev` (base de testes) em 2026-10-28.

| Ponto | PRD | Implementação |
| --- | --- | --- |
| Status do cliente | `c.ativo` | `c.status = '0' and c."dataInativacao" is not null` (inativo) e `c.status = '1'` (ativo) |
| Exame ativo | `and pe.ativo` | `pe.ativo = '1'`, porque a coluna é `character` |
| Status do grupo | não tratado | parâmetro `:group_status` (`ativo` = `'1'`, `inativo` = `'0'`, `todos`), escolhido em cada execução |
| Data da prescrição | [QA] | `ProntuarioGrupo.data` (`date`, nunca nulo em dev) |
| Conselho do médico | não documentado | `numeroConselhoClasse`, `trim(ConselhoProfissional.codigo)` e `Estado.uf` por `frkUfConselhoProfissional` |
| Vacinas | fora sem vínculo | vínculo inferido por paciente e `ProntuarioGrupo.data = VacinaPaciente."dataSolicitacao"`, só nas ondas legadas e com flag |
| Grupos mistos | toda a base | restritos aos grupos da onda |

## 3. Arquitetura

```
shosp_migration/
  config/settings.py      # Settings (pydantic-settings)
  logging.py              # structlog JSON
  source/
    waves.py              # Wave, WaveOrigin, ClientStatus, GroupStatus, WaveScope
    sql/                  # arquivos .sql versionados
    sql_registry.py       # unico ponto que entrega SQL executavel
    connection.py         # SourcePool somente leitura
    keys.py               # chaves keyset
    models.py             # modelos de origem
    reader.py             # SourceReader
  cli/app.py              # count, preview
```

Dependências: `cli` usa `source` e `config`; `source` não conhece a CLI.

## 4. Configuração

| Variável | Obrigatória | Uso |
| --- | --- | --- |
| `SHOSP_DB_URL` | sim | DSN somente leitura. Aceita o prefixo `jdbc:`, que é removido |
| `BATCH_SIZE_ORGANIZATION`, `BATCH_SIZE_PHYSICIAN`, `BATCH_SIZE_PATIENT`, `BATCH_SIZE_PRESCRIPTION` | sim | tamanho do lote, sem padrão (definido antes de cada carga) |
| `SOURCE_STATEMENT_TIMEOUT_SECONDS` | sim | `statement_timeout` das sessões |
| `SOURCE_POOL_MAX_SIZE` | não (4) | conexões simultâneas |
| `INCLUDE_VACCINES` | não (`false`) | padrão da flag de vacinas |

O DSN é `SecretStr`. Nenhuma mensagem de erro ou log mostra o DSN.

## 5. Ondas e escopo

```python
class Wave(StrEnum):  # legado-inativos, legado-ativos, memed-inativos, memed-ativos
@dataclass(frozen=True)
class WaveScope:
    wave: Wave
    group_status: GroupStatus      # ativo, inativo, todos
    include_vaccines: bool
    @property
    def reads_vaccines(self) -> bool  # include_vaccines and origem legado
```

`WaveScope` com `include_vaccines=True` numa onda Memed é recusado (`ValueError`).

## 6. SQL

- `_wave_cte.sql` define `wave_cliente` e `wave_group`. É injetado pelo marcador `{{wave_cte}}`.
- `wave_group` expõe `grupo_id`, `cliente_id`, `prestador_id`, `paciente_id`, `grupo_data` e `grupo_status`.
- Parâmetros de recorte de keyset dentro da CTE: `:min_cliente` e `:max_cliente` (em `wave_cliente`, `c.prk between ...`) e `:after_grupo` (em `wave_group`, `pg.prk > :after_grupo`). Evitam recalcular a onda inteira em cada página.
- `organizations.sql` usa `exists` correlacionado sobre `wave_group`, que para no primeiro grupo elegível de cada cliente.
- Physician e Patient são lidos **um cliente por vez** (`min_cliente = max_cliente`), com a lista de clientes vinda de `organizations.sql`. O reader completa cada lote com os clientes seguintes até o tamanho configurado.
- Os parâmetros nomeados (`:nome`) viram `$n` do asyncpg. Comentários `--` são removidos antes da conversão.
- A sessão usa `plan_cache_mode = force_custom_plan`, para que os `OR` por parâmetro sejam podados em cada execução.

| Arquivo | Chave keyset | Parâmetros próprios |
| --- | --- | --- |
| `organizations.sql` | `prk` | `:batch` |
| `physicians.sql` | (`cliente_id`, `prk`) | `:after_cliente`, `:after_prk`, `:batch` |
| `patients.sql` | (`cliente_id`, `prk`) | `:after_cliente`, `:after_prk`, `:batch` |
| `prescription_groups.sql` | `grupo_id` | `:batch` |
| `prescription_items_legacy.sql`, `_exam.sql`, `_memed.sql` | — | `:grupo_ids` |
| `prescription_items_vaccine.sql` | — | `:grupo_ids` |
| `counts.sql` | — | — |
| `counts_vaccines.sql` | — | — |

### 6.1 Vacinas

- Candidatos: vacinas com `codigoAfyaRx is null` dos pacientes dos grupos do lote, ligadas a todo grupo do paciente com `ProntuarioGrupo.data = "dataSolicitacao"`.
- A ambiguidade é medida por linha física (`ctid`) sobre **todos** os grupos do paciente, não só os do lote. Só entram as vacinas com exatamente um grupo, e esse grupo precisa estar no lote.
- `source_id` = SHA-256 de (`frkPaciente`, `descricao`, `status`, `dataSolicitacao`, `dataVacina`, `lote`, `local`), calculado no modelo.
- `counts_vaccines.sql` classifica as vacinas dos pacientes da onda em: vinculadas (um grupo, dentro da onda), vinculadas fora do escopo (um grupo, fora da onda ou do filtro de status do grupo), ambíguas e sem grupo.

## 7. Interface

```python
class SourceReader:
    def organizations(self, scope, after: OrgKey | None = None, batch_size: int | None = None) -> AsyncIterator[list[ShospCliente]]
    def physicians(self, scope, after: ClientScopedKey | None = None, batch_size: int | None = None) -> AsyncIterator[list[ShospPrestador]]
    def patients(self, scope, after: ClientScopedKey | None = None, batch_size: int | None = None) -> AsyncIterator[list[ShospPaciente]]
    def prescription_groups(self, scope, after: GroupKey | None = None, batch_size: int | None = None) -> AsyncIterator[list[ShospGroupWithItems]]
    async def count(self, scope) -> WaveCounts
```

- Cada modelo expõe `key`. O consumidor grava a chave do último registro do lote como checkpoint e a passa em `after` na retomada.
- `batch_size` sobrescreve a configuração (usado pelo `preview`).
- Em `prescription_groups`, o lote de grupos e os itens são lidos na mesma transação. Ordem dos itens: `prescricao` (legado ou Memed), `exames` e `vacinas`, cada fonte na ordem da sua query.
- Ondas legadas leem `legacy`, `exam` e, com a flag, `vaccine`. Ondas Memed leem só `memed`.

## 8. Segurança

- Sessões abertas com `default_transaction_read_only = on`, e cada consulta dentro de `transaction(readonly=True)`.
- Só o `sql_registry` entrega SQL, por nome de arquivo. Não há método público que aceite SQL livre.
- Campos pessoais dos modelos (nome, CPF, CNS, e-mail, telefones, endereço, texto clínico) têm `repr=False`.
- Logs: nome da query, onda, tamanho do lote, linhas e duração.

## 9. CLI

- `shosp-migration count --wave W --group-status S [--with-vaccines/--without-vaccines] [--json]`
- `shosp-migration preview --wave W --group-status S --entity org|physician|patient|prescription [--limit N] [--with-vaccines/--without-vaccines]`
- `--wave` e `--group-status` são obrigatórios. `--with-vaccines` numa onda Memed sai com código 2.
- Código 1 para erro de configuração ou de conexão, sem mostrar o DSN.
- O `preview` mostra só IDs técnicos e o número de itens por fonte.

## 10. Testes

- Unitários: ondas, registro de SQL (conversão de parâmetros, `::` preservado, comentário ignorado, arquivo desconhecido recusado, parâmetro faltando), settings, CLI e `repr` sem PII.
- Integração (`-m integration`, `SHOSP_TEST_DB_URL`): sessão somente leitura, status do cliente por onda, keyset sem duplicata nem lacuna entre páginas, itens Memed sem itens legados, ordem dos itens e vacinas sem ambiguidade.

## 11. Riscos e pendências

- Tempo medido em dev, onda `legado-inativos`, grupos ativos, lotes 100/200/500/500:

  | Entidade | Registros | Páginas | Total | Pior página |
  | --- | --- | --- | --- | --- |
  | Organization | 398 | 4 | 2,4 s | 1,2 s |
  | Physician | 784 | 4 | 7,1 s | 3,5 s |
  | Patient | 37.784 | 76 | 19,8 s | 1,4 s |
  | Prescription (com itens) | 73.649 | 148 | 16,6 s | 1,9 s |

  Os totais batem com o `count`. Com a CTE completa em cada página, Organization, Physician e Patient levavam cerca de 18 s por página (cerca de 23 min só para Patient).
- O vínculo inferido das vacinas depende da aprovação do produto. A flag vem desligada.
- Os números de dev não valem para a base real (PRD-00, D-03).
