-- Pedido do Paulo em 21/09/2026: a Matriz de Agendamento deixou de ser
-- editada semana a semana (com setas "<" ">") e passou a ser um ÚNICO
-- padrão semanal (igual à Semana Padrão em template_semanal_bloqueios,
-- só que aqui marca "reservado" em vez de "bloqueado"). Esse padrão é
-- depois "replicado" (aplicado) em cima de datas reais do calendário
-- através dos botões "Replicar matriz por período" / "por mês", que
-- criam os registros de verdade em matriz_reservas_admin (já existente)
-- para cada data que cai no dia da semana marcado aqui.
create table if not exists matriz_template (
    id uuid primary key default uuid_generate_v4(),
    consultorio_id uuid not null references consultorios(id) on delete cascade,
    dia_semana integer not null check (dia_semana between 0 and 6),  -- 0=domingo...6=sábado
    horario text not null,  -- um dos 11 horários fixos do dia (ex: '08:00')
    criado_em timestamptz not null default now(),
    unique (consultorio_id, dia_semana, horario)
);
alter table matriz_template enable row level security;

-- Histórico de cada "replicação" feita (botão Relatório) -- pedido do
-- Paulo: mostrar data de quando a matriz foi aplicada e qual período do
-- calendário ela cobriu, mais recente primeiro.
create table if not exists matriz_replicacoes (
    id uuid primary key default uuid_generate_v4(),
    tipo text not null,  -- 'periodo' ou 'mes'
    data_inicio date not null,
    data_fim date not null,
    aplicados integer not null default 0,
    conflitos integer not null default 0,
    criado_em timestamptz not null default now()
);
alter table matriz_replicacoes enable row level security;
create index if not exists idx_matriz_replicacoes_criado_em on matriz_replicacoes(criado_em desc);
