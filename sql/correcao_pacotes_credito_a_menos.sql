-- CORREÇÃO: credita a diferença das compras de pacote que entraram com horas a menos.
-- ANTES: rode sql/diagnostico_pacotes_credito_a_menos.sql, confira a lista e faça um BACKUP
-- (Admin > Backup). Rode este script UMA vez, inteiro, no Neon SQL Editor (pode rodar de novo: ele
-- não repete quem já foi corrigido).
-- O que faz, para cada compra de pacote com diferença:
--   1) grava uma linha "Correção de crédito do pacote" (logo após a compra, no histórico);
--   2) soma a diferença no saldo_apos das movimentações seguintes do médico (histórico coerente);
--   3) soma a diferença no saldo atual do médico.
begin;

alter table creditos_transacoes add column if not exists criado_por text;

create temp table corr on commit drop as
select t.id as compra_id, t.medico_id, t.pagamento_id, t.criado_em, t.quantidade_horas,
       round(t.quantidade_horas * a.preco - t.valor, 2) as diff, a.preco
from creditos_transacoes t
cross join (select valor_hora as preco from pacotes_horas_avulsas where ativo order by horas limit 1) a
where t.tipo = 'compra' and t.carteira = 'salas' and t.quantidade_horas is not null
  and t.quantidade_horas * a.preco - t.valor > 0.005
  and not exists (
    select 1 from creditos_transacoes x
    where x.medico_id = t.medico_id and x.tipo = 'ajuste' and x.reserva_id is null
      and x.pagamento_id is not distinct from t.pagamento_id
      and x.descricao like 'Correção de crédito do pacote%');

-- 2) histórico: movimentações do médico depois de cada compra corrigida
update creditos_transacoes t
set saldo_apos = t.saldo_apos + d.soma
from (
  select x.id, sum(c.diff) as soma
  from creditos_transacoes x
  join corr c on c.medico_id = x.medico_id and x.criado_em > c.criado_em
  where x.carteira = 'salas'
  group by x.id
) d
where t.id = d.id;

-- 1) linhas de correção (saldo_apos já considera as correções anteriores do mesmo médico)
insert into creditos_transacoes (medico_id, tipo, valor, saldo_apos, descricao, pagamento_id,
                                 quantidade_horas, categoria, carteira, criado_em, criado_por)
select c.medico_id, 'ajuste', c.diff,
       (select t.saldo_apos from creditos_transacoes t where t.id = c.compra_id) + c.diff,
       'Correção de crédito do pacote de ' || c.quantidade_horas || 'h (diferença do desconto por volume)',
       c.pagamento_id, greatest(round(c.diff / c.preco), 1)::int, 'horas', 'salas',
       c.criado_em + interval '1 second', 'Correção automática'
from corr c;

-- 3) saldo atual
update medicos m set saldo_creditos = m.saldo_creditos + s.soma
from (select medico_id, sum(diff) as soma from corr group by medico_id) s
where m.id = s.medico_id;

-- conferência: lista o que foi corrigido
select m.nome, c.quantidade_horas as pacote_h, c.diff as reais_creditados_a_mais, m.saldo_creditos as saldo_novo_reais
from corr c join medicos m on m.id = c.medico_id order by m.nome;

commit;
