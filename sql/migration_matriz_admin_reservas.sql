-- Reservas/blocos definidos manualmente pelo administrador na Matriz.
-- Se não houver registro aqui e o horário não estiver bloqueado na Semana Padrão,
-- o horário aparece em VERDE para o médico.
create table if not exists matriz_reservas_admin (
    id uuid primary key default uuid_generate_v4(),
    consultorio_id uuid not null references consultorios(id) on delete cascade,
    data date not null,
    horario time not null,
    descricao text,
    criado_por text,
    criado_em timestamptz not null default now(),
    unique (consultorio_id, data, horario)
);
create index if not exists idx_matriz_admin_consultorio_data on matriz_reservas_admin(consultorio_id, data);
alter table matriz_reservas_admin enable row level security;
