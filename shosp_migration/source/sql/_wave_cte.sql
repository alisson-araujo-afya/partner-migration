-- CTE compartilhada por todas as queries de onda (PRD-00, secao 6.5.3).
-- Status do cliente: '1' ativo, '0' inativo (DECISAO-status-cliente-e-vacinas, secao 4.1).
-- :min_cliente, :max_cliente e :after_grupo recortam a onda pelo checkpoint.
wave_cliente as (
  select c.prk
  from cliente."Cliente" c
  where ((:wave_status = 'inativo' and c.status = '0' and c."dataInativacao" is not null)
      or (:wave_status = 'ativo' and c.status = '1'))
    and c.prk between :min_cliente and :max_cliente
),
wave_group as (
  select pg.prk            as grupo_id,
         u."frkCliente"    as cliente_id,
         pg."frkPrestador" as prestador_id,
         a."frkPaciente"   as paciente_id,
         pg.data           as grupo_data,
         pg.status         as grupo_status
  from prontuario."ProntuarioGrupo" pg
  join login."Usuario" u          on u.prk = pg."frkUsuario"
  join wave_cliente wc            on wc.prk = u."frkCliente"
  join shosp."ServicoPrestado" sp on sp.prk = pg."frkServicoPrestado"
  join shosp."Atendimento" a      on a.prk = sp."frkAtendimento"
  where pg.prk > :after_grupo
    and (:group_status = 'todos'
      or (:group_status = 'ativo' and pg.status = '1')
      or (:group_status = 'inativo' and pg.status = '0'))
    and ((:wave_origin = 'legado' and (
            exists (select 1 from prontuario."Prescricao" p
                    where p."frkProntuarioGrupo" = pg.prk
                      and p."codigoAfyaRx" is null and p."codigoMemed" is null)
         or exists (select 1 from prontuario."ProntuarioExame" pe
                    where pe."frkProntuarioGrupo" = pg.prk
                      and pe."codigoAfyaRx" is null and pe.ativo = '1')))
      or (:wave_origin = 'memed' and
            exists (select 1 from prontuario."Prescricao" p
                    where p."frkProntuarioGrupo" = pg.prk
                      and p."codigoMemed" is not null
                      and p."codigoAfyaRx" is null)))
)
