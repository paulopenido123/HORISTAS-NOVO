-- SOMENTE LEITURA. Rode no Neon (SQL Editor), um bloco por vez.

-- 1) Pagamentos de R$ 390 (pacote de 6h) dos últimos 30 dias e se geraram crédito
select p.id, m.nome, p.valor, p.horas_pacote, p.forma_pagamento, p.status,
       p.criado_em at time zone 'America/Sao_Paulo' as criado_em_br,
       p.pago_em  at time zone 'America/Sao_Paulo' as pago_em_br,
       p.asaas_payment_id,
       (select count(*) from creditos_transacoes t where t.pagamento_id = p.id) as qtd_transacoes
from pagamentos_pix p join medicos m on m.id = p.medico_id
where p.valor = 390 and p.criado_em > now() - interval '30 days'
order by p.criado_em desc;

-- 2) TODOS os pagamentos "pago" sem crédito, ou "pendente" há mais de 1 hora (os suspeitos)
select p.id, m.nome, p.valor, p.horas_pacote, p.status,
       p.criado_em at time zone 'America/Sao_Paulo' as criado_em_br,
       p.asaas_payment_id,
       (select count(*) from creditos_transacoes t where t.pagamento_id = p.id) as qtd_transacoes
from pagamentos_pix p join medicos m on m.id = p.medico_id
where (p.status = 'pago' and not exists (select 1 from creditos_transacoes t where t.pagamento_id = p.id))
   or (p.status = 'pendente' and p.criado_em < now() - interval '1 hour' and p.criado_em > now() - interval '30 days')
order by p.criado_em desc;

-- 3) Pagamentos creditados em duplicidade (mais de 1 transação para o mesmo pagamento)
select pagamento_id, count(*) from creditos_transacoes
where pagamento_id is not null and tipo = 'compra'
group by pagamento_id having count(*) > 1;
