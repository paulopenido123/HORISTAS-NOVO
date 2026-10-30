-- Extrato de horas de um médico (SOMENTE LEITURA -- não altera nada).
-- Neon > SQL Editor: cole, rode UMA consulta por vez (selecione e clique Run).
-- Para outro médico, troque o texto %Grateki% abaixo.

-- 1) Confirma quem é o médico (deve voltar 1 linha; se voltar mais de uma, me avise)
select id, nome, email, telefone, saldo_creditos as saldo_reais
from medicos
where nome ilike '%Grateki%';

-- 2) Todas as movimentações (compras, usos, reembolsos, ajustes do admin)
select to_char(t.criado_em at time zone 'America/Sao_Paulo','DD/MM/YYYY HH24:MI') as data,
       t.tipo, t.quantidade_horas as horas, t.valor as reais, t.saldo_apos,
       t.descricao, t.criado_por
from creditos_transacoes t
join medicos m on m.id = t.medico_id
where m.nome ilike '%Grateki%' and t.carteira = 'salas'
order by t.criado_em;

-- 3) Totais
select count(*) filter (where t.tipo='compra')                      as qtd_compras,
       coalesce(sum(t.quantidade_horas) filter (where t.tipo='compra'),0)  as horas_compradas,
       coalesce(sum(t.valor) filter (where t.tipo='compra'),0)             as reais_pagos,
       coalesce(sum(t.quantidade_horas) filter (where t.tipo='consumo'),0) as horas_consumo,
       coalesce(sum(t.quantidade_horas) filter (where t.tipo='ajuste'),0)  as horas_ajustes_e_reembolsos
from creditos_transacoes t
join medicos m on m.id = t.medico_id
where m.nome ilike '%Grateki%' and t.carteira = 'salas';
