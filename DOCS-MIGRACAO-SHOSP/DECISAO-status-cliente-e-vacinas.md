# Decisão: status do Cliente e vínculo VacinaPaciente → grupo

Complementa o PRD-00 (seção 4.1), o PRD-01 (seção 3), o PRD-04 (seção 10.3) e o PRD-05 (RF-APP-23). Usa as mesmas convenções: **[FATO]**, **[REQ]**, **[HIP]**, **[QA]** e **[REC]**.

## 1. Questionamento

> As colunas de status do Cliente (`ativo`, `dataInativacao`) e o vínculo `VacinaPaciente` → grupo ainda são [HIP]. Como tratar no código?

Alternativas apresentadas:

- **A:** usar as hipóteses do PRD, isoladas em `_wave_cte.sql`, com as vacinas desligadas por uma flag de configuração até o vínculo ser confirmado.
- **B:** usar os nomes reais das colunas e/ou a confirmação do vínculo da vacina.
- **C:** usar as hipóteses para o Cliente e tirar as vacinas deste card.
- **D:** outra.

## 2. Resposta escolhida: D

Usar os nomes reais das colunas, confirmados no `dbpgshosp_dev`, e desenvolver as vacinas para as ondas legadas de ativos e de inativos, ligadas por flag em cada execução. O responsável decide quando rodar cada uma.

A alternativa A foi descartada porque a hipótese `c.ativo` não existe no banco: a query falharia na primeira execução com `column c.ativo does not exist`.

## 3. Evidências no banco

Base consultada: `jdbc:postgresql://localhost:5435/dbpgshosp_dev` (container `dbpgshosp_dev`), em 28/10/2026.

### 3.1 `cliente."Cliente"` [FATO]

| Coluna | Tipo | Nulo | Comentário no banco |
| --- | --- | --- | --- |
| `status` | `character(1)` | não | "Status do cliente" |
| `dataInativacao` | `date` | sim | "Data que o cliente inativou o sistema" |

- Não existe a coluna `ativo`.
- A view `cliente."ClienteAtivo"` do próprio banco filtra `where cli.status = '1'::bpchar`, então **`'1'` = ativo**.
- Em dev só existem os valores `'0'` e `'1'`, então **`'0'` = inativo**.

| Situação | Filtro | Clientes em dev |
| --- | --- | --- |
| Inativo com data (ondas 1 e 3) | `status = '0' and "dataInativacao" is not null` | 5.613 |
| Ativo (ondas 2 e 4) | `status = '1'` | 57 |
| Status indefinido (CA-25) | `status = '0' and "dataInativacao" is null` | 4.473 (44%) |

Quatro clientes ativos têm `dataInativacao` preenchida, provavelmente reativados. Eles entram como ativos e a data é ignorada.

### 3.2 `prontuario."VacinaPaciente"` [FATO]

Colunas: `frkPaciente`, `descricao`, `status`, `dataSolicitacao`, `dataVacina`, `lote`, `local` e `codigoAfyaRx`.

- Não tem coluna de grupo (`frkProntuarioGrupo`), nem de prestador, nem `prk`.
- A única FK é `frkPaciente` → `shosp."Paciente"`. O único índice é em `frkPaciente`, e não há índice único.
- Em dev há 559 linhas, 2 delas com `codigoAfyaRx`, e 340 sem `dataSolicitacao`.
- Não há linhas duplicadas na combinação (`frkPaciente`, `descricao`, `status`, `dataSolicitacao`, `dataVacina`, `lote`, `local`).

### 3.3 Caminho do grupo até o paciente [FATO]

`ProntuarioGrupo` não tem `frkPaciente`. O paciente é alcançado por:

`prontuario."ProntuarioGrupo".frkServicoPrestado` → `shosp."ServicoPrestado".frkAtendimento` → `shosp."Atendimento".frkPaciente`

## 4. Como tratar no código

### 4.1 Status do Cliente

Colocar o critério só em `_wave_cte.sql`:

```sql
wave_cliente as (
  select c.prk
  from cliente."Cliente" c
  where (:wave_status = 'inativo' and c.status = '0' and c."dataInativacao" is not null)
     or (:wave_status = 'ativo'   and c.status = '1')
)
```

- Comparar com texto (`'0'` e `'1'`), não com booleano nem com inteiro. O `asyncpg` devolve `str`.
- Se o modelo Python precisar do status, converter na leitura (`ativo = row["status"] == "1"`) e não espalhar `'1'` pelo código.
- Cliente com `status = '0'` e `"dataInativacao" is null` vai para o relatório como "status indefinido" (CA-25).
- As queries das entidades (`organizations.sql` etc.) leem `c.status` no lugar de `c.ativo`.

### 4.2 Vínculo VacinaPaciente → grupo [REC]

O vínculo é inferido pelo paciente e pela data da solicitação:

```sql
-- prescription_items_vaccine.sql
select pg.prk as grupo_id,
       v."frkPaciente", v.descricao, v.status, v."dataSolicitacao", v."dataVacina", v.lote, v.local
from prontuario."VacinaPaciente" v
join shosp."Atendimento" a      on a."frkPaciente" = v."frkPaciente"
join shosp."ServicoPrestado" sp on sp."frkAtendimento" = a.prk
join prontuario."ProntuarioGrupo" pg on pg."frkServicoPrestado" = sp.prk
                                    and pg.data = v."dataSolicitacao"
where pg.prk = any(:grupo_ids)
  and v."codigoAfyaRx" is null
order by pg.prk, v."dataSolicitacao";
```

Regras:

- **Escopo:** só as ondas legadas, de inativos (`legado-inativos`) e de ativos (`legado-ativos`). As ondas Memed não leem vacinas. O status do cliente vem da `wave_cliente` (seção 4.1), como nas outras fontes de itens.
- **Flag:** `include_vaccines` na configuração, que pode ser sobrescrita na CLI (`run --wave legado-ativos --with-vaccines`). O padrão é desligado, e o valor usado em cada execução fica registrado no relatório.
- **Associação ambígua:** se a vacina casa com mais de um grupo, ela não entra e vai para o relatório como "vínculo ambíguo". Se não casa com nenhum grupo, entra como "sem grupo" (inclui as vacinas sem `dataSolicitacao`).
- **Chave de origem:** como não existe `prk`, o `source_id` é um hash de (`frkPaciente`, `descricao`, `status`, `dataSolicitacao`, `dataVacina`, `lote`, `local`).
- **Snapshot:** a vacina entra no grupo depois de `Prescricao` e `ProntuarioExame`, com o de-para do PRD-04, seção 10.5.

### 4.3 Cobertura medida em dev

557 vacinas legadas (`codigoAfyaRx is null`):

| Resultado da associação | Vacinas |
| --- | --- |
| 1 grupo (migra) | 168 (30%) |
| Vários grupos (ambíguo, fica de fora) | 40 |
| Nenhum grupo (fica de fora) | 349 (340 delas sem `dataSolicitacao`) |

## 5. Pontos de atenção

- **Conflito com o PRD-04.** A seção 10.3 diz que, sem coluna de ligação, as vacinas ficam fora desta fase para não inventar o vínculo. A associação por paciente e data é um vínculo inferido e precisa da aprovação do produto.
- **Cobertura baixa.** Só 30% das vacinas de dev casam com exatamente um grupo, e a maioria das que ficam de fora não tem `dataSolicitacao`. Uma segunda tentativa de associação usando `dataVacina` quando `dataSolicitacao` vier vazia ainda não foi medida.

## 6. Pendências

- [QA] Rodar as mesmas consultas na base real (PRD-00, D-03). Os números de dev podem mudar.
- [QA] Aprovação do produto para o vínculo inferido de `VacinaPaciente` (PRD-04, seção 10.3).
- [QA] O que fazer com os clientes de status indefinido (PRD-00, D-12): 4.473 em dev, 44% da base.
- [QA] Medir o ganho de cobertura usando `dataVacina` como segunda tentativa de associação.
- Atualizar as marcações [HIP] de `c.ativo` nos PRDs 00 (linhas 106, 258 e 319) e 01 (linhas 82 e 94).
