-- Bloqueio de agenda (feriados e viagens do médico fixo): antes disso,
-- a única forma de "tirar" um médico da agenda num dia era cancelar
-- consulta por consulta na mão. Agora dá pra bloquear de uma vez um dia
-- inteiro, um período de vários dias (viagem), ou só um turno específico
-- dentro de um dia (ex: médico sai mais cedo numa quinta) -- a célula
-- fica preta na tela e ninguém consegue agendar ali enquanto o bloqueio
-- existir.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso, depois de já ter rodado
-- sql/migration_agenda_medicos_fixos.sql (que cria a tabela `medicos`
-- usada aqui).

create table if not exists agenda_bloqueios (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id) on delete cascade,
    data_inicio date not null,
    data_fim date not null,
    -- turno = null bloqueia o dia inteiro (manhã+tarde+noite); um turno
    -- específico ('manha'/'tarde'/'noite') bloqueia só aquele turno, em
    -- todos os dias do período
    turno text check (turno in ('manha', 'tarde', 'noite')),
    motivo text,
    criado_em timestamptz not null default now(),
    constraint agenda_bloqueios_periodo_valido check (data_fim >= data_inicio)
);

create index if not exists idx_agenda_bloqueios_medico on agenda_bloqueios(medico_id);
create index if not exists idx_agenda_bloqueios_periodo on agenda_bloqueios(data_inicio, data_fim);

alter table agenda_bloqueios enable row level security;
