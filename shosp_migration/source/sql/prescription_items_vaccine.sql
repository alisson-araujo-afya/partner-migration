-- DECISAO-status-cliente-e-vacinas, secao 4.2: vinculo inferido por paciente e data.
-- A ambiguidade e medida por linha fisica (ctid) contra todos os grupos do paciente,
-- nao so os do lote. So entram vacinas com exatamente um grupo, e esse grupo no lote.
with batch_patient as (
  select distinct a."frkPaciente" as paciente_id
  from prontuario."ProntuarioGrupo" pg
  join shosp."ServicoPrestado" sp on sp.prk = pg."frkServicoPrestado"
  join shosp."Atendimento" a      on a.prk = sp."frkAtendimento"
  where pg.prk = any(:grupo_ids)
),
candidate as (
  select v.ctid                          as vid,
         pg.prk                          as grupo_id,
         v."frkPaciente"                 as paciente_id,
         v.descricao,
         v.status,
         v."dataSolicitacao"             as data_solicitacao,
         v."dataVacina"                  as data_vacina,
         v.lote,
         v.local,
         count(*) over (partition by v.ctid) as matches
  from prontuario."VacinaPaciente" v
  join batch_patient bp               on bp.paciente_id = v."frkPaciente"
  join shosp."Atendimento" a          on a."frkPaciente" = v."frkPaciente"
  join shosp."ServicoPrestado" sp     on sp."frkAtendimento" = a.prk
  join prontuario."ProntuarioGrupo" pg on pg."frkServicoPrestado" = sp.prk
                                      and pg.data = v."dataSolicitacao"
  where v."codigoAfyaRx" is null
)
select grupo_id, paciente_id, descricao, status, data_solicitacao, data_vacina, lote, local
from candidate
where matches = 1
  and grupo_id = any(:grupo_ids)
order by grupo_id, data_solicitacao, descricao, vid
