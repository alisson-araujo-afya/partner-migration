-- PRD-04, secao 10.3: itens legados de Prescricao.
select p."frkProntuarioGrupo" as grupo_id,
       p.prk,
       p.item,
       p.quantidade,
       p."nrQuantidade"       as nr_quantidade,
       p.forma,
       p.dosagem,
       p.via,
       p.frequencia,
       p.duracao,
       p.observacao,
       p.folha,
       p."codigoMemed"        as codigo_memed
from prontuario."Prescricao" p
where p."frkProntuarioGrupo" = any(:grupo_ids)
  and p."codigoAfyaRx" is null
  and p."codigoMemed" is null
order by p."frkProntuarioGrupo", p.folha, p.prk
