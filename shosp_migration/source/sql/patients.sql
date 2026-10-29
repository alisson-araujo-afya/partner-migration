-- PRD-03, secao 3.2. Keyset por (cliente_id, prk), lido um cliente por vez
-- (min_cliente = max_cliente = after_cliente). Sem LIMIT: o reader fatia o lote.
with {{wave_cte}},
wave_patient as (
  select distinct cliente_id, paciente_id from wave_group
)
select wp.cliente_id,
       pac.prk,
       pac.nome,
       pac.apelido,
       pac."nomeMae"            as nome_mae,
       pac.cpf,
       pac."dataNascimento"     as data_nascimento,
       pac.sexo,
       pac.email,
       pac.celular,
       pac.telefone,
       pac.cep,
       pac.logradouro,
       pac.numero,
       pac.bairro,
       pac.complementoendereco  as complemento,
       cid.nome                 as cidade,
       est.uf
from wave_patient wp
join shosp."Paciente" pac   on pac.prk = wp.paciente_id
left join shosp."Cidade" cid on cid.prk = pac."frkCidadeResidencia"
left join shosp."Estado" est on est.prk = cid."frkEstado"
where (wp.cliente_id, pac.prk) > (:after_cliente, :after_prk)
order by wp.cliente_id, pac.prk
