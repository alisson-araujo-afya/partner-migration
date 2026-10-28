-- PRD-04, secao 10.3: exames legados. ativo e character ('1').
select pe."frkProntuarioGrupo"     as grupo_id,
       pe.prk,
       pe."nomeProcedimento"       as nome_procedimento,
       pe."orientacaoProcedimento" as orientacao_procedimento,
       pe.qtd,
       pe."nrFolha"                as nr_folha
from prontuario."ProntuarioExame" pe
where pe."frkProntuarioGrupo" = any(:grupo_ids)
  and pe."codigoAfyaRx" is null
  and pe.ativo = '1'
order by pe."frkProntuarioGrupo", pe."nrFolha", pe.prk
