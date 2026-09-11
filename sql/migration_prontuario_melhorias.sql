-- 1. Data do registro (diferente da data/hora que o sistema gravou) —
--    permite ao médico documentar uma data específica do atendimento,
--    mesmo digitando a anotação depois.
alter table prontuarios add column if not exists data_registro date not null default current_date;

-- 2. Email do médico (opcional) — necessário pra confirmação em duas
--    etapas por email, como alternativa ao WhatsApp.
alter table medicos add column if not exists email text;

-- 3. Preferência de confirmação em duas etapas pra acessar prontuário
--    — vem LIGADA por padrão (mais seguro), o médico pode desligar.
alter table medicos add column if not exists prontuario_requer_2fa boolean not null default true;
alter table medicos add column if not exists prontuario_canal_2fa text not null default 'whatsapp'
    check (prontuario_canal_2fa in ('whatsapp', 'email'));

-- 4. Códigos de confirmação temporários (expiram em poucos minutos,
--    de uso único).
create table if not exists prontuario_2fa_codigos (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    codigo text not null,
    expira_em timestamptz not null,
    usado boolean not null default false,
    criado_em timestamptz not null default now()
);
create index if not exists idx_prontuario_2fa_medico on prontuario_2fa_codigos(medico_id, criado_em desc);

alter table prontuario_2fa_codigos enable row level security;
