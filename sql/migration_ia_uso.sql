-- Sistema de cobrança por uso de IA (Gemini) — "calculador de consumo".
--
-- Ideia geral, confirmada com o Paulo:
--   1. No primeiro acesso, o médico ganha um crédito único de teste
--      (ex: R$ 5,00) na MESMA carteira que já existe hoje (saldo_creditos) —
--      não é uma carteira separada.
--   2. Cada módulo de IA que o médico ativa (secretaria / prontuário /
--      financeiro) ganha 30 dias grátis a partir do primeiro uso daquele
--      módulo — depois disso, cada chamada de IA passa a debitar da
--      carteira.
--   3. Duas ações específicas, mais caras/sensíveis, têm um teto de uso
--      grátis À PARTE, que vale por médico PRA SEMPRE (não renova por mês,
--      não depende dos 30 dias — conta mesmo dentro do período de trial):
--        - analisar prontuário (Módulo 7/8): 3 grátis
--        - enviar confirmação/cobrança pro paciente (Secretaria): 10 grátis
--   4. Depois que o trial de 30 dias de um módulo acaba, o sistema BLOQUEIA
--      o uso de IA daquele módulo e avisa o médico (não deixa continuar
--      "por fora" e cobrar depois).
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso, depois dos outros arquivos sql/.

-- 1. Crédito de boas-vindas: controla se o médico já recebeu (só pode ganhar 1 vez)
alter table medicos add column if not exists ia_trial_creditado boolean not null default false;

-- 2. Estado de ativação de cada módulo de IA, por médico. A linha só
--    existe a partir do primeiro uso — "ativado_em" marca o início da
--    contagem dos 30 dias grátis daquele módulo especificamente.
create table if not exists medico_modulos_ia (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    modulo_slug text not null check (modulo_slug in ('secretaria', 'prontuario', 'financeiro')),
    ativado_em timestamptz not null default now(),
    trial_fim timestamptz not null,  -- calculado na hora de ativar = ativado_em + 30 dias
    unique (medico_id, modulo_slug)
);
create index if not exists idx_medico_modulos_ia_medico on medico_modulos_ia(medico_id);

-- 3. Tetos de uso grátis "pra sempre" (não renovam), por ação específica.
--    Guarda só o contador — o limite de cada ação fica no código
--    (ia_uso_service.py), pra ser fácil de ajustar sem precisar de SQL novo.
create table if not exists medico_ia_contadores (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    acao text not null check (acao in ('prontuario_analise', 'secretaria_envio_paciente')),
    usados integer not null default 0,
    unique (medico_id, acao)
);

-- 4. Extrato completo de cada chamada de IA medida — inclusive as
--    gratuitas (trial/teto), pra dar transparência total no painel do
--    médico e pro admin conseguir acompanhar custo real x cobrado.
create table if not exists ia_uso_log (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    modulo_slug text not null,
    acao text not null,
    provedor text not null,             -- 'gemini' | 'claude'
    modelo text,
    tokens_entrada integer not null default 0,
    tokens_saida integer not null default 0,
    custo_real numeric(10,4) not null default 0,     -- o que o provedor de IA realmente cobrou (estimado)
    custo_cobrado numeric(10,2) not null default 0,   -- o que foi debitado do médico (0 se foi grátis)
    gratuito boolean not null default false,
    motivo_gratuito text,                -- 'credito_boas_vindas' | 'trial_30_dias' | 'teto_uso_gratis' | null
    descricao text,
    criado_em timestamptz not null default now()
);
create index if not exists idx_ia_uso_log_medico on ia_uso_log(medico_id, criado_em desc);

-- 5. Marca, na própria transação da carteira, se foi um gasto de IA ou de
--    horas de consultório — só pra relatório (o saldo continua sendo UM
--    número só, como definido). Não quebra nada que já existe: toda linha
--    antiga vira 'horas' por padrão.
alter table creditos_transacoes add column if not exists categoria text not null default 'horas'
    check (categoria in ('horas', 'ia'));

alter table medico_modulos_ia enable row level security;
alter table medico_ia_contadores enable row level security;
alter table ia_uso_log enable row level security;
