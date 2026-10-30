-- DIAGNÓSTICO (somente leitura): quem comprou pacote e recebeu menos horas do que comprou.
-- Neon > SQL Editor: cole tudo e clique Run. Não altera nada.
-- Causa: o saldo é guardado em R$ e o pacote maior tem desconto por hora; antes da v96 o sistema
-- creditava só o valor pago. Corrigido = horas compradas x preço da hora avulsa (pacote de menor qtd. de horas).
with avulsa as (
  select valor_hora as preco from pacotes_horas_avulsas where ativo order by horas limit 1
)
select m.nome,
       to_char(t.criado_em at time zone 'America/Sao_Paulo','DD/MM/YYYY HH24:MI') as data_compra,
       t.quantidade_horas as horas_compradas,
       t.valor as reais_creditados,
       round(t.quantidade_horas * a.preco, 2) as reais_corretos,
       round(t.quantidade_horas * a.preco - t.valor, 2) as diferenca_reais,
       round((t.quantidade_horas * a.preco - t.valor) / a.preco, 1) as horas_a_menos
from creditos_transacoes t
join medicos m on m.id = t.medico_id
cross join avulsa a
where t.tipo = 'compra' and t.carteira = 'salas' and t.quantidade_horas is not null
  and t.quantidade_horas * a.preco - t.valor > 0.005
order by t.criado_em;
