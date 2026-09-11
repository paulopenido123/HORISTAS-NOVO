-- Sessões de videoconferência (Módulo 6): ambiente fechado entre o
-- médico e um ou mais pacientes. A sala em si é criada num provedor
-- externo (ex: Daily.co) — aqui só guardamos o controle de quem tem
-- acesso a qual sala e quando.

create table if not exists sessoes_video (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_telefone text not null,
    room_name text,              -- identificador da sala no provedor externo
    room_url text,                -- link da sala (enviado ao paciente)
    status text not null default 'agendada' check (status in ('agendada', 'em_andamento', 'encerrada', 'cancelada')),
    receita_emitida boolean not null default false,
    criado_em timestamptz not null default now(),
    iniciada_em timestamptz,
    encerrada_em timestamptz
);

alter table sessoes_video enable row level security;
