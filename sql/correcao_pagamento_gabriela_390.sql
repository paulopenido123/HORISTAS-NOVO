-- SÓ RODAR DEPOIS de confirmar no Asaas que a cobrança pay_fjnqfsdnq9rvoapj
-- está como "Recebida" ou "Confirmada". Idempotente: se já estiver "pago", não faz nada.
-- Faça o mesmo que o webhook: marca pago, credita R$ 390 (6h x R$ 65) e grava a transação.
with p as (
  update pagamentos_pix set status = 'pago', pago_em = now()
  where id = '73c80df8-0030-47bc-a33c-36d4e8029b30' and status = 'pendente'
  returning id, medico_id
),
m as (
  update medicos set saldo_creditos = saldo_creditos + 390, alerta_saldo_baixo_enviado = false
  where id = (select medico_id from p)
  returning id, saldo_creditos
)
insert into creditos_transacoes
  (medico_id, tipo, valor, saldo_apos, descricao, pagamento_id, quantidade_horas, categoria, carteira)
select m.id, 'compra', 390, m.saldo_creditos,
       'Recarga via pix (Asaas) — pacote de 6h (crédito manual após conferência)',
       (select id from p), 6, 'horas', 'salas'
from m;
