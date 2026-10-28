# PRD-04 — Migração de Prescription e endpoint novo no Maagizo (SHOSP)

Status: rascunho para revisão técnica. Data: 2026-10-26.

- PRD principal: [PRD-00 — Migração de dados do parceiro SHOSP](./PRD-00-migracao-shosp.md). Este documento especifica o endpoint das seções 6.3, RF-06 a RF-06f, RN-10 a RN-20 e D-01a do principal.
- Depende de: [PRD-01 — Organization](./PRD-01-organization.md), [PRD-02 — Physician](./PRD-02-physician.md) e [PRD-03 — Patient](./PRD-03-patient.md).
- Cliente que executa este fluxo: [PRD-05 — Aplicação Python](./PRD-05-aplicacao-python.md).

Convenções iguais às do PRD principal: **[FATO]**, **[REQ]**, **[HIP]**, **[QA]** e **[REC]**. Abreviações: `MR` = `afya-prescription-monorepo/apps/prescription-backend/app`, `MZ` = `maagizo/backend`.

Este documento usa o prefixo `PRE`.

---

## 1. Objetivo

Gravar cada prescrição SHOSP (um `prontuario."ProntuarioGrupo"` elegível na onda, seção 10) como **uma única linha pai** em `prescription`, com todos os itens como medicamentos `freeText` simples, por um endpoint novo **implementado no Maagizo** [REQ]. O endpoint não aciona SNCR, Numerations, webhook, PDF, SenseData, LME, SADT, event stream, labels, interações nem upsert de paciente. A prescrição gravada precisa ser lida pelo `prescription-backend` (detalhe, histórico, PDF e renovação) sem nenhuma sincronização, porque os dois usam o mesmo banco `maagizo` [FATO].

## 2. Por que um endpoint novo

- [FATO] O `POST /v1/physician/prescriptions` (legado) gera filhos `apart` e futuros, LME e SADT, publica no event stream e grava interações (`MZ/pkg/http/restecho/routes/physician/post_prescriptions.go`, linhas 175-265).
- [FATO] O `PUT /v1/partner/iclinic/prescriptions` resolve organização e médico pelo `partnerId` da `api-key`, mas cria paciente vazio com `FindOrCreateEmptyByExternalID` e grava por `PrescriptionSvc.Save` (`MZ/pkg/http/restecho/routes/partner/put_org_physicians_prescriptions.go`, linhas 28-128).
- [FATO] `PrescriptionService.Save` chama `SetEmpty()` e dispara, em goroutines, `updatePatientInstructions` e `insertPrescriptionLabel` (`MZ/pkg/services/prescription_svc.go`, linhas 287-307). `PrescriptionStorage.Save` grava o paciente na mesma transação (`patientStorage.fill`, `MZ/pkg/postgres/prescription_storage.go`, a partir da linha 569), o que pode alterar um paciente que já existia (contraria RN-07a).
- [FATO] O `POST /v1/physicians/{id}/prescriptions` do `prescription-backend` aloca SNCR e grava outbox de webhook. Não pode ser usado (RN-20 e O-04).

## 3. Contrato proposto [REC]

Decisão pendente de aprovação (D-01a). Proposta:

- **Grupo e autenticação:** `/v1/partner`, com o middleware `APIKeyAuth` (`MZ/pkg/http/restecho/handler.go`, linhas 117-119). O `partnerId` vem **da chave** (`c.Get("partnerId")`), nunca do corpo. Alternativa equivalente: grupo próprio no padrão de `/v1/migration-va-sp` (`handler.go`, linhas 320-323), também com `APIKeyAuth`.
- **Rotas:**
  - `POST /v1/partner/migration/prescriptions`: cria a prescrição.
  - `GET /v1/partner/migration/prescriptions/{externalId}?orgExternalId=...`: consulta por `external_id`, para a reconciliação (RF-18 e RN-10).
- **Formato de erro:** envelope v1 `resterrors.APIErrors` (`{"errors":[{"code","detail","source"}]}`), por coerência com o grupo. [QA] Hoje o `ErrorHandler` v1 responde **400 para qualquer `APIErrors`**, inclusive `not_found` (`MZ/pkg/http/restecho/error_handler.go`, linhas 44-46 e 62-66). O endpoint novo precisa responder 404 e 409 reais para a aplicação classificar a falha (PRD-00, seção 13). Isso exige responder com `c.JSON(status, apiErrors)` direto no handler, em vez de retornar o erro ao `ErrorHandler`.

### 3.1 `POST /v1/partner/migration/prescriptions`

Request:

```json
{
  "orgExternalId": "shosp-org-123",
  "physicianExternalId": "shosp-med-456",
  "patientExternalId": "shosp-pac-789",
  "externalId": "shosp-presc-0001",
  "prescriptionDate": "2024-03-15T10:30:00-03:00",
  "signed": false,
  "items": [
    {
      "type": "freeText",
      "printType": "simple",
      "apart": false,
      "withinLme": false,
      "freeText": {
        "title": "Amoxicilina 500 mg",
        "patientInstruction": "1 comprimido de 8 em 8 horas por 7 dias",
        "unit": "",
        "quantity": 21
      }
    }
  ],
  "freeTexts": []
}
```

As chaves seguem o camelCase das rotas v1 do Maagizo e do `immutable_data`. A ADR de snake_case vale só para o monorepo.

| Campo | Regra |
| --- | --- |
| `orgExternalId` | obrigatório; resolvido por `OrgSvc.ByExternalIDAndPartnerID` com o `partnerId` da chave |
| `physicianExternalId` | obrigatório; resolvido por `PhysicianSvc.PhysicianByExternalID(orgID, ...)` |
| `patientExternalId` | obrigatório; resolvido por `PatientSvc.PatientByExternalID(orgID, ...)`, que ignora removidos (`deleted_at IS NULL`, `MZ/pkg/postgres/patient_storage.go`, linhas 31-37). **Nunca cria nem altera paciente** |
| `externalId` | obrigatório, não vazio; chave de idempotência (seção 4) |
| `prescriptionDate` | opcional; RFC 3339; gravado em `prescription_date` (RN-19) |
| `signed` | opcional, padrão `false` (D-10) |
| `items` | obrigatório, pelo menos 1 elemento (senão a renovação é bloqueada por `NO_ITEMS`) |
| `items[].type` | exatamente `freeText` |
| `items[].printType` | exatamente `simple` (RN-12) |
| `items[].apart` | exatamente `false` (RN-13) |
| `items[].withinLme` | exatamente `false` (RF-06f) |
| `items[].freeText.title` | obrigatório, não vazio, até 40000 caracteres, sem truncamento (RF-06e) |
| `items[].freeText.patientInstruction` | opcional, texto |
| `items[].freeText.unit` | opcional, padrão `""` |
| `items[].freeText.quantity` | opcional; inteiro entre 0 e 32767, porque o campo é `*int16` (`MZ/pkg/prescription/item_free_text.go`). [QA] Valor padrão quando ausente (D-10) |
| `freeTexts` | opcional, lista de strings; só para anotações soltas (RN-14) |

Os helpers `GetOrgFromBody` e `GetPhysicianFromBody` (`MZ/pkg/http/restecho/routes/partner/request_helper.go`, linhas 17-59) já resolvem organização e médico com o `partnerId` do contexto e montam o erro `not_found` com o ponteiro do campo.

Respostas:

| Status | Quando | Corpo |
| --- | --- | --- |
| 201 | prescrição criada | `{"data": {"id": "<uuid>", "externalId": "...", "created": true}}` |
| 200 | já existia prescrição com o mesmo `externalId` na organização (idempotência) | `{"data": {"id": "<uuid>", "externalId": "...", "created": false}}` |
| 400 | JSON inválido ou violação de regra da tabela acima | `APIErrors` com `source.pointer` (por exemplo, `/body/items/0/printType`) |
| 401 | `api-key` ausente ou inválida | vazio |
| 404 | organização, médico ou paciente não encontrado no escopo do parceiro | `APIErrors` com `code = not_found` e o ponteiro do campo |
| 409 | já existe prescrição com o mesmo `externalId` na organização, mas com médico ou paciente diferentes | `APIErrors` com `code = conflict` |
| 5xx | erro interno | `APIErrors` |

O 409 sinaliza colisão de `external_id` entre prescrições diferentes. A aplicação registra como `FALHA_PERMANENTE`, sem reconciliação automática.

### 3.2 `GET /v1/partner/migration/prescriptions/{externalId}?orgExternalId=...`

- Resposta 200: `{"data": {"id", "externalId", "orgExternalId", "physicianExternalId", "patientExternalId", "prescriptionDate", "createdAt"}}`. Não devolve o `immutable_data`, para não expor conteúdo clínico na reconciliação.
- Status: 200, 401 e 404 (organização ou prescrição não encontrada).
- Filtro: `org_id` da organização resolvida, `external_id` informado e `deleted_at IS NULL`. Hoje só existe `PrescriptionByExternalID` global, sem filtro de organização (`prescription_storage.go`, linhas 42-46 e 271-278), então a consulta escopada é nova.

## 4. Idempotência (RN-10 e RN-15)

- [FATO] `prescription.external_id` aceita nulo e não tem restrição de unicidade. O precedente Memed deduplica na aplicação com `AlreadyImported`, que filtra por `org_id`, `patient_id`, `physician_id`, `not empty` e `external_id` (`prescription_storage.go`, linhas 190-193 e 381-388).
- **RF-PRE-01 — Chave:** a unicidade é por (`org_id`, `external_id`), com `deleted_at IS NULL`. O escopo é a organização, e não o trio do `AlreadyImported`, para detectar colisões de `external_id` entre pacientes (o 409 da seção 3.1).
- **RF-PRE-02 — Serialização sem campo novo:** a checagem e o `INSERT` rodam na mesma transação, protegidos por `pg_advisory_xact_lock(hashtext(org_id || ':' || external_id))`. Isso evita duplicata quando a mesma prescrição é enviada em paralelo, sem criar coluna, tabela nem índice. [QA] Se o time preferir um índice único parcial sobre colunas existentes (`(org_id, external_id) WHERE external_id IS NOT NULL AND deleted_at IS NULL`), ele exige uma migration Go e a confirmação de que não conta como campo novo (RN-15). Antes de criar o índice, é preciso verificar se já existem duplicatas na base.
- **RF-PRE-03 — Reenvio:** reenviar a mesma prescrição retorna 200 com o ID existente e não grava nada.

## 5. Gravação dedicada

**RF-PRE-04:** o service novo monta a linha e chama uma função de storage nova, que faz só o `INSERT` em `prescription`. Não usa `PrescriptionService.Save` nem `PrescriptionStorage.Save`.

Colunas gravadas (subconjunto de `sqlInsertPrescription`, `prescription_storage.go`, linhas 48-54):

| Coluna | Valor |
| --- | --- |
| `org_id`, `physician_id`, `patient_id` | IDs internos resolvidos pelos external IDs |
| `id` | UUID novo |
| `prescription_date` | `prescriptionDate` do request ou nulo |
| `created_at` | horário da gravação. [QA] RN-19: preservar a data original exige aceitar `createdAt` no request |
| `immutable_data` | snapshot da seção 6 |
| `signed` | `signed` do request |
| `code` e `password` | [QA] D-10: string vazia, como no Memed, ou geração pelo mesmo gerador do fluxo normal. Com `code` vazio, o índice parcial `prescription_code_key` não se aplica |
| `external_id` | `externalId` do request |
| `imported_data_id` | **nulo** (RN-16) |
| `parent_id` | **nulo** (RF-06a) |
| `empty` | **`false`** (RF-06a); não chama `SetEmpty()` |
| `apart` | **`false`** (RN-13) |
| `sign_provider_id` e `appointment_id` | nulos |
| `hide_patient_personal_data` | `false` |
| `relative_order` | `0` |
| `pub_id` | UUID v7, como no `Save` atual (linhas 604-608) |

**RF-PRE-05 — Sem efeitos colaterais.** O endpoint não executa nenhuma destas ações:

- `patientStorage.fill` nem qualquer escrita em `patient`, `physician` ou `organization`;
- `updatePatientInstructions` e `insertPrescriptionLabel`;
- envio ao SenseData;
- event stream, interações, LME, SADT, filhos `apart` ou futuros;
- chamada ao `prescription-backend` (proxy SNCR) ou gravação em `numeration.*` e `partner_webhook_outbox`;
- geração de PDF.

## 6. Snapshot `immutable_data`

**RF-PRE-06:** o snapshot repete o formato que o fluxo normal produz quando há só itens `freeText` simples (RF-06d do principal):

- `items`: os itens do request, na ordem recebida, com `type`, `printType`, `apart`, `withinLme` e `freeText` (`title`, `patientInstruction`, `unit` e `quantity`);
- `exams = []`, `vaccines = []`, sem `lme`;
- `freeTexts`: a lista do request ou `[]`.

**RF-PRE-07:** a serialização usa os mesmos tipos Go do fluxo normal (`prescription.Prescription`, `ItemFreeText` e o serializador de `immutable_data` usado em `prescription_storage.go`, linhas 570-572), para garantir que o leitor Python do `prescription-backend` reconheça o snapshot. [QA] Confirmar as demais chaves que o leitor espera (`patient`, `physician`, `organization`) comparando com uma prescrição real que tenha só itens `freeText` (pendência do RF-06d).

**RF-PRE-08 — Validação do snapshot:** o handler rejeita com 400 qualquer item com `type` diferente de `freeText`, `printType` diferente de `simple`, `apart = true`, `withinLme = true`, título vazio ou com mais de 40000 caracteres, e `freeTexts` com elemento que não seja string. A aplicação Python faz as mesmas validações antes do envio (PRD-05), mas o endpoint não confia nela.

## 7. Estrutura de implementação no Maagizo

- **Handler:** `MZ/pkg/http/restecho/routes/partner/post_migration_prescriptions.go` e `get_migration_prescription.go`, com o struct `Handler` do pacote `partner` e os helpers de `request_helper.go`.
- **Registro:** no `v1PartnerGroup` de `MZ/pkg/http/restecho/handler.go`.
- **Service:** método novo em `MZ/pkg/services/prescription_svc.go` (por exemplo, `SaveMigrated`) ou um service dedicado em `MZ/pkg/services/`, com a lógica de idempotência da seção 4.
- **Storage:** funções novas em `MZ/pkg/postgres/prescription_storage.go`: `InsertMigrated` (só o `INSERT`, dentro da transação com o advisory lock) e `ByOrgAndExternalID`.
- **Testes:** `*_test.go` ao lado do handler, com testify e `testapi.WithSuite`/`suite.NewPartnerRequest` (`MZ/pkg/http/restecho/testapi/testapi.go`, linha 581). Cobrir os cenários da seção 9.
- **Swagger:** anotações no handler, no padrão das rotas do grupo.

## 8. Fluxo

```mermaid
sequenceDiagram
    participant App as AplicacaoPython
    participant MZ as Maagizo
    participant DB as PostgresMaagizo
    participant MR as PrescriptionBackend
    App->>MZ: "POST /v1/partner/migration/prescriptions (api-key)"
    MZ->>MZ: "Validar request e snapshot"
    MZ->>DB: "Resolver org, physician e patient por external_id"
    MZ->>DB: "BEGIN; advisory lock; buscar (org_id, external_id)"
    alt "ja existe"
        MZ-->>App: "200 created=false"
    else "nao existe"
        MZ->>DB: "INSERT prescription; COMMIT"
        MZ-->>App: "201 created=true"
    end
    MR->>DB: "Le detalhe, historico, PDF e renovacao"
```

## 9. Critérios de aceite

Os critérios CA-14 a CA-23 do principal valem integralmente. Critérios específicos do endpoint:

- **CA-PRE-01:** Dado um request válido, quando enviado, então a resposta é 201 e existe exatamente uma linha em `prescription` com `parent_id`, `imported_data_id` nulos, `apart = false`, `empty = false` e o `external_id` enviado (CA-15).
- **CA-PRE-02:** Dado o mesmo request enviado duas vezes, inclusive em paralelo, quando processado, então existe uma única linha, e a segunda resposta é 200 com `created = false` e o mesmo `id`.
- **CA-PRE-03:** Dado um `patientExternalId` que não existe ou está removido logicamente, quando enviado, então a resposta é 404 com ponteiro `/body/patientExternalId`, e nenhuma linha é criada em `patient` nem em `prescription`.
- **CA-PRE-04:** Dado um item com `printType = "sncr"` ou `apart = true`, quando enviado, então a resposta é 400 com o ponteiro do item, sem gravação.
- **CA-PRE-05:** Dado uma `api-key` de outro parceiro, quando o `orgExternalId` pertence ao SHOSP, então a resposta é 404 (a organização não existe no escopo da chave).
- **CA-PRE-06:** Dado uma prescrição gravada, quando a linha do paciente é comparada antes e depois, então ela está inalterada, e nenhuma label, instrução de paciente ou evento do event stream foi gerado (CA-22).
- **CA-PRE-07:** Dado uma prescrição gravada, quando o `GET` de reconciliação é chamado com o mesmo `externalId` e `orgExternalId`, então retorna 200 com o mesmo `id`.
- **CA-PRE-08:** Dado uma prescrição gravada, quando lida pelo `prescription-backend`, então `is_renewable` é verdadeiro e o PDF e o histórico mostram os N itens (CA-17, CA-18 e CA-23).
- **CA-PRE-09:** Dado uma prescrição gravada, quando consultadas `numeration.*` e `partner_webhook_outbox`, então nenhuma linha nova existe (CA-14).

## 10. Origem SHOSP e agrupamento

Fonte: [Guia de migração - prescrição legada](https://afya-spm.atlassian.net/wiki/spaces/Tech/pages/1552482315/Guia+de+migra+o+-+prescri+o+legada) e PRD-00, seções 4.1 e 6.5. Todas as queries partem da CTE `wave_cliente` e `wave_group` (PRD-00, seção 6.5.3).

### 10.1 Agrupamento e `externalId`

- **RF-PRE-09 — Um grupo, uma prescrição:** cada `prontuario."ProntuarioGrupo"` elegível na onda gera um request do endpoint (seção 3.1) [REQ]. Todos os itens do grupo, de todas as fontes da onda, entram em `items`.
- **RF-PRE-10 — `externalId` por origem (RN-23):**
  - ondas legadas (1 e 2): `<prefixo><ProntuarioGrupo.prk>`;
  - ondas Memed (3 e 4): `<prefixo>memed-<ProntuarioGrupo.prk>`.

  Um grupo com itens legados e Memed gera duas prescrições, sem colisão na unicidade por (`org_id`, `external_id`) (RF-PRE-01 e RN-21).
- **Referências do request:**
  - `orgExternalId`: `external_id` do `Cliente` do usuário do grupo (PRD-01);
  - `physicianExternalId`: `external_id` do `Prestador` do grupo (PRD-02);
  - `patientExternalId`: `external_id` do `Paciente` do atendimento do grupo (PRD-03).
- **`prescriptionDate`** [HIP]: a data do `Atendimento` ou do `ProntuarioGrupo`. O guia não documenta essa coluna. [QA] Nome da coluna.
- **Grupo sem itens válidos:** se todos os itens do grupo forem descartados na transformação, a prescrição recebe `FALHA_DADOS`, porque o endpoint exige pelo menos 1 item (seção 3.1).

### 10.2 Query dos grupos

```sql
-- prescription_groups.sql  (parametros: :wave_status, :wave_origin, :last_prk, :batch)
with wave_cliente as (...), wave_group as (...)   -- PRD-00, secao 6.5.3
select wg.grupo_id,
       wg.cliente_id,
       wg.prestador_id,
       wg.paciente_id
from wave_group wg
where wg.grupo_id > :last_prk
order by wg.grupo_id
limit :batch;
```

Os itens de cada lote são lidos em seguida, com `:grupo_ids` igual aos `grupo_id` do lote.

### 10.3 Queries dos itens

**Ondas legadas: `Prescricao`** [FATO: guia]

```sql
-- prescription_items_legacy.sql
select p."frkProntuarioGrupo" as grupo_id,
       p.prk,
       p.item,
       p.quantidade,
       p."nrQuantidade",
       p.forma,
       p.dosagem,
       p.via,
       p.frequencia,
       p.duracao,
       p.observacao,
       p.folha
from prontuario."Prescricao" p
where p."frkProntuarioGrupo" = any(:grupo_ids)
  and p."codigoAfyaRx" is null
  and p."codigoMemed" is null
order by p."frkProntuarioGrupo", p.folha, p.prk;
```

**Ondas legadas: `ProntuarioExame`** [FATO: guia]

```sql
-- prescription_items_exam.sql
select pe."frkProntuarioGrupo" as grupo_id,
       pe.prk,
       pe."nomeProcedimento",
       pe."orientacaoProcedimento",
       pe.qtd,
       pe."nrFolha"
from prontuario."ProntuarioExame" pe
where pe."frkProntuarioGrupo" = any(:grupo_ids)
  and pe."codigoAfyaRx" is null
  and pe.ativo
order by pe."frkProntuarioGrupo", pe."nrFolha", pe.prk;
```

**Ondas legadas: `VacinaPaciente`** [QA]

O guia liga a vacina só ao paciente (`frkPaciente`), sem grupo do prontuário nem prestador. Antes do desenvolvimento, é preciso confirmar se existe uma coluna de ligação ao grupo não documentada.

- Se existir (por exemplo, `frkProntuarioGrupo`) [HIP], a vacina entra no grupo como os outros itens:

  ```sql
  -- prescription_items_vaccine.sql
  select v."frkProntuarioGrupo" as grupo_id,  -- [HIP] coluna nao documentada
         v.prk,
         v.descricao,
         v.lote,
         v.local,
         v."dataSolicitacao"
  from prontuario."VacinaPaciente" v
  where v."frkProntuarioGrupo" = any(:grupo_ids)
    and v."codigoAfyaRx" is null
  order by v."frkProntuarioGrupo", v."dataSolicitacao", v.prk;
  ```

- Se não existir, as vacinas ficam fora desta fase, porque não há como atribuí-las a um médico nem a uma prescrição sem inventar o vínculo. O motivo fica registrado no relatório da execução.

**Ondas Memed: `Prescricao`**

```sql
-- prescription_items_memed.sql
select p."frkProntuarioGrupo" as grupo_id,
       p.prk,
       p."codigoMemed",
       p.item,
       p.quantidade,
       p."nrQuantidade",
       p.forma,
       p.dosagem,
       p.via,
       p.frequencia,
       p.duracao,
       p.observacao,
       p.folha
from prontuario."Prescricao" p
where p."frkProntuarioGrupo" = any(:grupo_ids)
  and p."codigoMemed" is not null
  and p."codigoAfyaRx" is null
order by p."frkProntuarioGrupo", p.folha, p.prk;
```

**Ordem dos itens no snapshot (RF-06e):** nas ondas legadas, primeiro os itens de `Prescricao`, depois os de `ProntuarioExame` e por fim as vacinas, cada fonte na ordem da sua query. Nas ondas Memed, a ordem da query Memed.

### 10.4 Estratégia das ondas Memed (D-11)

[QA] O guia não diz se, para itens Memed, a SHOSP guarda o conteúdo do item (`item`, `via`, `frequencia` etc.) ou só o `codigoMemed`. A query de amostra abaixo responde à pergunta antes do desenvolvimento das ondas 3 e 4:

```sql
select count(*) as total_memed,
       count(*) filter (where nullif(trim(p.item), '') is not null) as com_texto
from prontuario."Prescricao" p
where p."codigoMemed" is not null;
```

- **Alternativa A [REC]:** com o texto preenchido, as ondas Memed usam o mesmo pipeline, o mesmo endpoint e o mesmo de-para da seção 10.5. A prescrição continua renovável (RF-06f). Itens Memed sem texto viram `FALHA_DADOS`.
- **Alternativa B:** só com o código, a migração usa o importer Memed do Maagizo (`POST /v1/importer/migrationmemed`), que busca o conteúdo na Memed. Ele preenche `imported_data_id` e bloqueia a renovação (RN-16), além de seguir outro fluxo de deduplicação (`AlreadyImported`). Exige decisão do produto e ajustes no PRD-05.

### 10.5 De-para dos itens para `freeText` [REC]

Todos os itens têm `type = "freeText"`, `printType = "simple"`, `apart = false` e `withinLme = false` (RF-06b). Partes vazias são omitidas, sem separadores sobrando. O de-para precisa ser validado com amostras reais (PRD-00, seção 17).

| Fonte | `freeText.title` | `freeText.patientInstruction` | `freeText.quantity` | `freeText.unit` |
| --- | --- | --- | --- | --- |
| `Prescricao` (legado e Memed) | `item`, seguido de `dosagem` e `forma` quando existirem (ex.: "Amoxicilina 500 mg cápsula") | `via`, `frequencia`, `duracao` e `observacao`, separados por "; " | `nrQuantidade`; se nulo, `quantidade` convertido para inteiro; senão o padrão de D-10 | `""` |
| `ProntuarioExame` | `nomeProcedimento` | `orientacaoProcedimento` | `qtd` | `""` |
| `VacinaPaciente` | `descricao` | "Lote: `lote`; Local: `local`", só com as partes preenchidas | padrão de D-10 | `""` |

- `tipo`, `aprazamentoData`, `aprazamentoHora`, `folha` e `nrFolha` só servem para ordenar e não entram no snapshot.
- Quantidade fora do intervalo de 0 a 32767, ou texto não numérico, usa o padrão de D-10 e não gera falha.
- Título vazio depois da montagem descarta o item e registra o motivo. Título com mais de 40000 caracteres é `FALHA_DADOS` da prescrição (CA-16).

## 11. Pendências

- [QA] Aprovação do contrato e da rota (D-01a).
- [QA] Respostas 404 e 409 reais no grupo v1 (seção 3).
- [QA] Advisory lock ou índice único parcial (RF-PRE-02).
- [QA] Geração de `code` e `password`, valor padrão de `quantity`, `signed` e `created_at` históricos (D-10 e RN-19).
- [QA] Chaves obrigatórias do snapshot além de `items`, `exams`, `vaccines` e `freeTexts` (RF-PRE-07).
- [QA] Emissão da `api-key` do SHOSP em cada ambiente.
- [QA] Coluna de data do atendimento ou do grupo para `prescriptionDate` (seção 10.1).
- [QA] Ligação de `VacinaPaciente` ao grupo do prontuário (seção 10.3).
- [QA] Conteúdo dos itens Memed na SHOSP e escolha da alternativa das ondas Memed (seção 10.4 e PRD-00, D-11).
- [QA] Validação do de-para da seção 10.5 com amostras reais.

## 12. Referências

- [Guia de migração - prescrição legada](https://afya-spm.atlassian.net/wiki/spaces/Tech/pages/1552482315/Guia+de+migra+o+-+prescri+o+legada)
- `MZ/pkg/http/restecho/handler.go` (grupos `/v1/partner` e `/v1/migration-va-sp`)
- `MZ/pkg/http/restecho/error_handler.go` e `MZ/pkg/http/restecho/resterrors/errors.go`
- `MZ/pkg/http/restecho/routes/partner/request_helper.go`
- `MZ/pkg/http/restecho/routes/partner/put_org_physicians_prescriptions.go`
- `MZ/pkg/services/prescription_svc.go`
- `MZ/pkg/postgres/prescription_storage.go` e `MZ/pkg/postgres/patient_storage.go`
- `MZ/pkg/prescription/prescription.go` e `MZ/pkg/prescription/item_free_text.go`
- `MZ/pkg/http/restecho/testapi/testapi.go`
- `MR/prescription/service/build_prescription_renewal_service.py`
