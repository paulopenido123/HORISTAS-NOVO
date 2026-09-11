-- Semana Padrão: agora bloqueia por HORÁRIO INDIVIDUAL (não turno
-- inteiro), para bater com o formato de grade por hora que o Lifemax
-- já usa. Substitui a versão anterior (que era por turno).
--
-- Se você já rodou a versão anterior de migration_semana_padrao.sql,
-- pode rodar este arquivo por cima sem problema — ele recria a tabela
-- do zero (não existe dado de reserva de médico aqui, só configuração
-- do admin, então não tem risco de perder histórico).

drop table if exists template_semanal_bloqueios;

create table template_semanal_bloqueios (
    id uuid primary key default uuid_generate_v4(),
    consultorio_id uuid not null references consultorios(id) on delete cascade,
    dia_semana integer not null check (dia_semana between 0 and 6),  -- 0=domingo...6=sábado
    hora_inicio text not null,  -- ex: '08:00', '09:00' ... um dos 11 horários fixos do dia
    criado_em timestamptz not null default now(),
    unique (consultorio_id, dia_semana, hora_inicio)
);

alter table template_semanal_bloqueios enable row level security;
