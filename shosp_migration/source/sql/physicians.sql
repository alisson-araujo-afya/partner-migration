-- PRD-02, secao 3.2. Keyset por (cliente_id, prk), lido um cliente por vez
-- (min_cliente = max_cliente = after_cliente).
with {{wave_cte}},
wave_physician as (
  select distinct cliente_id, prestador_id from wave_group
)
select wp.cliente_id,
       pt.prk,
       pt.nome,
       pt."razaoSocial"           as razao_social,
       pt.cpf,
       pt.cns,
       pt.email,
       pt."numeroConselhoClasse"  as conselho_numero,
       trim(cp.codigo)            as conselho_codigo,
       uf_conselho.uf             as conselho_uf,
       (pt.ativo = '1')           as ativo
from wave_physician wp
join shosp."Prestador" pt                 on pt.prk = wp.prestador_id
left join shosp."ConselhoProfissional" cp on cp.prk = pt."frkConselhoProfissional"
left join shosp."Estado" uf_conselho      on uf_conselho.prk = pt."frkUfConselhoProfissional"
where (wp.cliente_id, pt.prk) > (:after_cliente, :after_prk)
order by wp.cliente_id, pt.prk
limit :batch
