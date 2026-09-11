-- Migração: sistema de créditos, autenticação de médicos, preços
-- configuráveis e histórico de pagamentos PIX (Asaas).
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso (depois dos outros arquivos sql/).

-- Médicos ganham login (senha), saldo de créditos e email opcional
-- (usado como alternativa de notificação quando o WhatsApp ainda não
-- estiver configurado)
alter table medicos add column if not exists senha_hash text;
alter table medicos add column if not exists saldo_creditos numeric(10,2) not null default 0;
alter table medicos add column if not exists alerta_saldo_baixo_enviado boolean not null default false;
alter table medicos add column if not exists email text;

-- Preços configuráveis pelo admin (uma linha só, sempre atualizada)
create table if not exists precos (
    id uuid primary key default uuid_generate_v4(),
    preco_hora numeric(10,2) not null default 0,
    preco_turno numeric(10,2) not null default 0,
    atualizado_em timestamptz not null default now()
);
insert into precos (preco_hora, preco_turno)
select 50.00, 150.00
where not exists (select 1 from precos);

-- Histórico de créditos: toda compra e todo consumo fica registrado aqui
create table if not exists creditos_transacoes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    tipo text not null check (tipo in ('compra', 'consumo', 'ajuste')),
    valor numeric(10,2) not null,          -- positivo p/ compra e ajuste positivo, negativo p/ consumo
    saldo_apos numeric(10,2) not null,
    descricao text,
    reserva_id uuid references reservas(id),
    pagamento_id uuid,                      -- referencia pagamentos_pix, quando for uma compra
    criado_em timestamptz not null default now()
);
create index if not exists idx_creditos_transacoes_medico on creditos_transacoes(medico_id, criado_em desc);

-- Cobranças PIX geradas via Asaas
create table if not exists pagamentos_pix (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    asaas_payment_id text unique,
    asaas_customer_id text,
    valor numeric(10,2) not null,
    status text not null default 'pendente' check (status in ('pendente', 'pago', 'expirado', 'cancelado')),
    qr_code_base64 text,
    copia_e_cola text,
    criado_em timestamptz not null default now(),
    pago_em timestamptz
);
create index if not exists idx_pagamentos_pix_medico on pagamentos_pix(medico_id, criado_em desc);
create index if not exists idx_pagamentos_pix_asaas_id on pagamentos_pix(asaas_payment_id);

alter table precos enable row level security;
alter table creditos_transacoes enable row level security;
alter table pagamentos_pix enable row level security;
