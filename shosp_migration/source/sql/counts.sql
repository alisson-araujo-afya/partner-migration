-- PRD-00, secao 6.5.4: volume da onda antes da carga. Chamar com min_cliente = after_grupo = -1.
with {{wave_cte}}
select (select count(distinct cliente_id) from wave_group)   as total_contas,
       (select count(distinct (cliente_id, prestador_id)) from wave_group) as total_medicos,
       (select count(distinct (cliente_id, paciente_id)) from wave_group)  as total_pacientes,
       (select count(*) from wave_group)                    as total_grupos,
       (select count(*) from wave_group where grupo_status = '1') as grupos_ativos,
       (select count(*) from wave_group where grupo_status = '0') as grupos_inativos,
       (select count(*)
          from wave_group wg
         where exists (select 1 from prontuario."Prescricao" p
                        where p."frkProntuarioGrupo" = wg.grupo_id
                          and p."codigoAfyaRx" is null and p."codigoMemed" is null)
           and exists (select 1 from prontuario."Prescricao" p
                        where p."frkProntuarioGrupo" = wg.grupo_id
                          and p."codigoMemed" is not null
                          and p."codigoAfyaRx" is null))   as grupos_mistos,
       (select count(*)
          from cliente."Cliente" c
         where c.status = '0' and c."dataInativacao" is null) as clientes_status_indefinido
