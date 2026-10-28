-- PRD-01, secao 3.2. Keyset por prk (min_cliente = ultimo prk + 1).
with {{wave_cte}}
select c.prk,
       c.nome,
       (c.status = '1')   as ativo,
       c."dataInativacao" as data_inativacao
from cliente."Cliente" c
where c.prk in (select distinct cliente_id from wave_group)
order by c.prk
limit :batch
