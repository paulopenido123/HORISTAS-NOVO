-- Schema para o Assistente de WhatsApp — Lifemax
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

create extension if not exists "uuid-ossp";

-- Médicos que usam o coworking
create table if not exists medicos (
    id uuid primary key default uuid_generate_v4(),
    nome text not null,
    telefone text unique not null,       -- formato E.164 sem '+', ex: 5531999999999
    especialidade text,
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

-- Consultórios disponíveis para reserva
create table if not exists consultorios (
    id uuid primary key default uuid_generate_v4(),
    nome text not null,                   -- ex: "Sala 12"
    descricao text,
    preco_periodo numeric(10,2) not null,
    fotos text[] default '{}',            -- urls públicas (Supabase Storage)
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

-- Reservas de consultório feitas pelos médicos
create table if not exists reservas (
    id uuid primary key default uuid_generate_v4(),
    consultorio_id uuid not null references consultorios(id),
    medico_id uuid not null references medicos(id),
    data date not null,
    periodo text not null check (periodo in ('manha', 'tarde', 'noite')),
    status text not null default 'pendente' check (status in ('pendente', 'confirmada', 'cancelada')),
    criado_em timestamptz not null default now(),
    -- evita duas reservas ativas no mesmo consultório/data/período
    unique (consultorio_id, data, periodo)
);

-- Agenda de pacientes de cada médico (para lembretes automáticos)
-- OBS: isso é um placeholder — se você já tem um sistema de agenda de
-- pacientes em outro lugar, esta tabela pode não ser necessária.
create table if not exists agenda_pacientes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_telefone text not null,      -- formato E.164 sem '+'
    data_consulta date not null,
    horario time,
    lembrete_enviado boolean not null default false,
    criado_em timestamptz not null default now()
);

-- Índices para as consultas mais comuns
create index if not exists idx_reservas_data_periodo on reservas(data, periodo);
create index if not exists idx_reservas_medico on reservas(medico_id);
create index if not exists idx_agenda_medico_data on agenda_pacientes(medico_id, data_consulta);

-- Row Level Security: como o backend usa a service_role key, RLS não
-- bloqueia o backend, mas é boa prática deixar ativado para proteger
-- contra uso indevido da anon key em outros contextos (ex: se um dia
-- você expuser alguma consulta direto pro frontend).
alter table medicos enable row level security;
alter table consultorios enable row level security;
alter table reservas enable row level security;
alter table agenda_pacientes enable row level security;
