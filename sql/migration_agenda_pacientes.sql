-- Agenda de pacientes: quando o médico pede pro assistente confirmar
-- uma consulta com um paciente, isso fica registrado aqui — permite
-- mandar o lembrete de 24h antes automaticamente (via job em segundo
-- plano) sem depender do médico pedir de novo.

create table if not exists consultas_pacientes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_telefone text not null,       -- formato E.164 sem '+', ex: 5531988887777
    data_consulta date not null,
    horario time not null,
    observacoes text,                       -- ex: preço da consulta, remédio a tomar antes
    status text not null default 'confirmada' check (status in ('confirmada', 'cancelada')),
    lembrete_24h_enviado boolean not null default false,
    criado_em timestamptz not null default now()
);

create index if not exists idx_consultas_pacientes_lembrete
    on consultas_pacientes(data_consulta, horario) where status = 'confirmada' and lembrete_24h_enviado = false;

alter table consultas_pacientes enable row level security;
