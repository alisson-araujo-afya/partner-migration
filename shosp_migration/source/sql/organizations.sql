-- PRD-01, secao 3.2. Keyset por prk (min_cliente = ultimo prk + 1).
-- O exists correlacionado para no primeiro grupo elegivel de cada cliente.
with {{wave_cte}}
select c.prk,
       c.nome,
       (c.status = '1')   as ativo,
       c."dataInativacao" as data_inativacao
from cliente."Cliente" c
join wave_cliente wc on wc.prk = c.prk
where exists (select 1 from wave_group wg where wg.cliente_id = c.prk)
order by c.prk
limit :batch
