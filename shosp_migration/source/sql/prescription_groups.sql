-- PRD-04, secao 10.2. Keyset por grupo_id (after_grupo na CTE).
with {{wave_cte}}
select wg.grupo_id,
       wg.cliente_id,
       wg.prestador_id,
       wg.paciente_id,
       wg.grupo_data,
       (wg.grupo_status = '1') as grupo_ativo
from wave_group wg
order by wg.grupo_id
limit :batch
