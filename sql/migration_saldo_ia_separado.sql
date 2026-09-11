-- Pedido do Paulo (08/09/2026): separar em DUAS carteiras o que antes
-- era um saldo único (decisão de 03/09/2026, revertida agora por
-- pedido explícito):
--   - saldo_creditos (já existia) = "Saldo para reserva de salas"
--   - saldo_ia (novo)             = "Saldo para IA"
-- Cada uma só é debitada pelo que é dela (sala nunca consome saldo de
-- IA, e vice-versa) e cada uma tem seu próprio alerta de saldo baixo.

alter table medicos add column if not exists saldo_ia numeric(10,2) not null default 0;
alter table medicos add column if not exists alerta_saldo_ia_baixo_enviado boolean not null default false;
comment on column medicos.saldo_ia is 'Saldo em R$ exclusivo pra uso de IA (secretária virtual, análise de prontuário, voz, contábil) -- separado do saldo_creditos (reserva de salas)';

alter table creditos_transacoes add column if not exists carteira text not null default 'salas'
    check (carteira in ('salas', 'ia'));
comment on column creditos_transacoes.carteira is 'Qual saldo essa transação mexeu: salas (saldo_creditos) ou ia (saldo_ia)';
update creditos_transacoes set carteira = 'ia' where categoria = 'ia' and carteira = 'salas';

-- ---------------------------------------------------------------------
-- Toggle EXPLÍCITO de cada módulo de IA, controlado pelo médico em
-- "Painel de IA" -- diferente de medico_modulos_ia (que só registra
-- quando o médico usou pela primeira vez, pra contar o trial de 30
-- dias). Sem marcar aqui, o médico só pode usar o crédito de teste
-- grátis (R$ 10, uma vez), nunca gastar saldo de verdade.
-- ---------------------------------------------------------------------
create table if not exists ia_modulos_ativados (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    modulo_slug text not null check (modulo_slug in ('secretaria', 'prontuario', 'prontuario_voz', 'financeiro')),
    ativado boolean not null default false,
    ativado_em timestamptz,
    atualizado_em timestamptz not null default now(),
    unique (medico_id, modulo_slug)
);
alter table ia_modulos_ativados enable row level security;

-- ---------------------------------------------------------------------
-- O médico pode comprar crédito de sala e/ou de IA no mesmo pagamento
-- -- guarda quanto de cada, pra saber como dividir quando o Asaas
-- confirmar que foi pago (ver webhooks_asaas.py).
-- ---------------------------------------------------------------------
alter table pagamentos_pix add column if not exists valor_salas numeric(10,2) not null default 0;
alter table pagamentos_pix add column if not exists valor_ia numeric(10,2) not null default 0;
comment on column pagamentos_pix.valor_salas is 'Parte do pagamento destinada ao saldo de reserva de salas';
comment on column pagamentos_pix.valor_ia is 'Parte do pagamento destinada ao saldo de IA';

-- Pagamentos já existentes: tudo que já foi pago até hoje era 100% pra
-- salas (a opção de comprar IA separadamente não existia ainda).
update pagamentos_pix set valor_salas = valor, valor_ia = 0 where valor_salas = 0 and valor_ia = 0 and valor > 0;

-- ---------------------------------------------------------------------
-- 4º módulo de IA: "Análise de voz para preenchimento automático de
-- prontuário" -- a restrição antiga só aceitava 3 valores.
-- ---------------------------------------------------------------------
alter table medico_modulos_ia drop constraint if exists medico_modulos_ia_modulo_slug_check;
alter table medico_modulos_ia add constraint medico_modulos_ia_modulo_slug_check
    check (modulo_slug in ('secretaria', 'prontuario', 'prontuario_voz', 'financeiro'));
