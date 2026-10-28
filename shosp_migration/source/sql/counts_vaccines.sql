-- Cobertura do vinculo inferido das vacinas dos pacientes da onda
-- (DECISAO-status-cliente-e-vacinas, secoes 4.2 e 4.3). Chamar sem recorte de checkpoint.
with {{wave_cte}},
wave_vaccine as (
  select m.matches, m.grupo_id
  from prontuario."VacinaPaciente" v
  cross join lateral (
    select count(*) as matches, min(pg.prk) as grupo_id
    from shosp."Atendimento" a
    join shosp."ServicoPrestado" sp      on sp."frkAtendimento" = a.prk
    join prontuario."ProntuarioGrupo" pg on pg."frkServicoPrestado" = sp.prk
                                        and pg.data = v."dataSolicitacao"
    where a."frkPaciente" = v."frkPaciente"
  ) m
  where v."codigoAfyaRx" is null
    and v."frkPaciente" in (select paciente_id from wave_group)
)
select count(*) filter (where matches = 1
                          and grupo_id in (select grupo_id from wave_group)) as vinculadas,
       count(*) filter (where matches = 1
                          and grupo_id not in (select grupo_id from wave_group)) as vinculadas_fora_do_escopo,
       count(*) filter (where matches > 1) as ambiguas,
       count(*) filter (where matches = 0) as sem_grupo
from wave_vaccine
