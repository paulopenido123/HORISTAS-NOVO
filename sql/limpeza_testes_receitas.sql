-- =====================================================================
-- Limpeza dos 3 pagamentos de TESTE (pedido do Paulo em 25/10/2026)
--   22/10/2026  Paulo  Pix  Pacote de 6h        R$ 390,00
--   23/09/2026  Paulo  Pix  Recarga de horas    R$  20,00
--   11/09/2026  Paulo  Pix  Recarga de horas    R$  20,00
--
-- O que faz:
--  * apaga esses 3 pagamentos  -> somem de Admin > Relatórios > Receitas
--  * apaga SÓ a transação da compra de 6h de 22/10 -> "Horas vendidas"
--    de outubro cai de 30 para 24
-- O que NÃO mexe: saldo atual de qualquer médico, reservas, outros
-- pagamentos, outras transações.
--
-- COMO USAR (no Neon > SQL Editor):
--  1) Rode o PASSO 1 (SELECT). Deve listar EXATAMENTE 3 linhas, as de cima.
--     Se vier outra quantidade, NÃO rode o passo 2 e me avise.
--  2) Rode o PASSO 2. Deve mostrar: pagamentos_apagados = 3 e
--     transacoes_apagadas = 1. (Se o passo 1 não deu 3, o passo 2 não apaga nada.)
-- Se o passo 1 der ERRO de coluna inexistente ou vier VAZIO, confira no Neon se está
-- no projeto/banco/branch correto (o mesmo do site horistas-novo) antes de qualquer coisa.
-- Este script é de uso único; não rode o passo 2 duas vezes.
-- =====================================================================

-- PASSO 1 -- conferir (não altera nada)
select p.id, m.nome, p.valor, p.status,
       (coalesce(p.pago_em, p.criado_em) at time zone 'America/Sao_Paulo') as quando
from pagamentos_pix p join medicos m on m.id = p.medico_id
where p.status = 'pago'
  and m.nome ilike 'paulo%'
  and (
        (p.valor = 390
          and (coalesce(p.pago_em, p.criado_em) at time zone 'America/Sao_Paulo')::date = date '2026-10-22')
     or (p.valor = 20
          and (coalesce(p.pago_em, p.criado_em) at time zone 'America/Sao_Paulo')::date in (date '2026-09-23', date '2026-09-11'))
  )
order by quando desc;

-- PASSO 2 -- apagar (só roda se o passo 1 tiver achado exatamente 3)
with alvo as (
  select p.id, p.valor
  from pagamentos_pix p join medicos m on m.id = p.medico_id
  where p.status = 'pago'
    and m.nome ilike 'paulo%'
    and (
          (p.valor = 390
            and (coalesce(p.pago_em, p.criado_em) at time zone 'America/Sao_Paulo')::date = date '2026-10-22')
       or (p.valor = 20
            and (coalesce(p.pago_em, p.criado_em) at time zone 'America/Sao_Paulo')::date in (date '2026-09-23', date '2026-09-11'))
    )
),
trava as (select 1 as ok where (select count(*) from alvo) = 3),
t as (
  delete from creditos_transacoes
  where tipo = 'compra'
    and pagamento_id in (select id from alvo where valor = 390)
    and exists (select 1 from trava)
  returning id
),
d as (
  delete from pagamentos_pix
  where id in (select id from alvo) and exists (select 1 from trava)
  returning id
)
select (select count(*) from d) as pagamentos_apagados,
       (select count(*) from t) as transacoes_apagadas;
