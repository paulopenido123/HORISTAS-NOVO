-- Agenda dos médicos fixos (Módulo 2): 74 médicos com horário fixo no
-- coworking, em turnos de segunda a sábado:
--   manhã  08:00–12:00 | tarde 13:00–17:00 | noite 17:30–20:30 (seg a sex)
--   sábado 08:00–12:00 (só manhã)
-- A grade em si é dividida por hora, mas cada consulta ocupa só 15min
-- dentro do turno -- por isso o horário fica solto (não fixo em blocos
-- de hora), e quem trava conflito é o banco (igual já fazemos em
-- 'reservas', com tsrange + EXCLUDE USING gist).
--
-- Esse médico fixo é um 'medicos' de verdade (mesmo login/senha, mesmo
-- prontuário) -- só ganha uma marcação (tipo_vinculo) pra diferenciar
-- do médico avulso que aluga consultório por hora (Grade de Turnos).
-- Assim, quando a secretária agenda um paciente com dados completos,
-- o médico fixo já pode usar isso no prontuário dele, sem duplicar cadastro.
--
-- Cada médico fixo fica vinculado a uma 'empresa' (Lifemax roda várias
-- empresas diferentes atendendo grupos de clientes distintos) -- esse
-- cadastro de empresas/médicos serve o restante do ecossistema também,
-- não só essa agenda.

create extension if not exists "uuid-ossp";
create extension if not exists btree_gist;

-- ---------- 0. Empresas: Lifemax opera várias empresas diferentes, cada uma
-- atendendo um grupo de clientes (ex: Biomax, Life M...) -- todo médico fixo
-- fica vinculado a uma delas. Esse cadastro serve o restante do "ecossistema"
-- também (não só essa agenda).
create table if not exists empresas (
    id uuid primary key default uuid_generate_v4(),
    nome text not null unique,
    criado_em timestamptz not null default now()
);
alter table empresas enable row level security;

-- ---------- 1. Marca quais médicos são "fixos" ----------
alter table medicos add column if not exists tipo_vinculo text not null default 'avulso'
    check (tipo_vinculo in ('avulso', 'fixo'));
comment on column medicos.tipo_vinculo is
    'avulso = aluga consultório por hora/turno (Grade de Turnos) | fixo = tem sala e turno fixos, agenda de pacientes própria';

alter table medicos add column if not exists empresa_id uuid references empresas(id) on delete set null;

-- ---------- 1b. Andar do consultório (só informativo, vem da planilha real de salas) ----------
alter table consultorios add column if not exists andar text;

-- ---------- 2. Grade semanal: em qual sala cada médico fixo atende, por dia e turno ----------
-- A sala PODE mudar de um turno/dia pra outro (não precisa ser sempre a
-- mesma) -- por isso é uma linha por combinação médico+dia+turno, não
-- uma coluna "sala" fixa no médico.
create table if not exists grade_medico_fixo (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id) on delete cascade,
    consultorio_id uuid not null references consultorios(id) on delete restrict,
    dia_semana text not null check (dia_semana in ('segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado')),
    turno text not null check (turno in ('manha', 'tarde', 'noite')),
    ativo boolean not null default true,
    criado_em timestamptz not null default now(),
    -- sábado só tem turno da manhã
    constraint grade_medico_fixo_sabado_so_manha check (dia_semana <> 'sabado' or turno = 'manha'),
    -- um médico só pode estar em UMA sala por dia+turno
    unique (medico_id, dia_semana, turno),
    -- uma sala só pode ter UM médico fixo por dia+turno
    unique (consultorio_id, dia_semana, turno)
);

create index if not exists idx_grade_medico_fixo_medico on grade_medico_fixo(medico_id);

-- ---------- 3. Consultas agendadas (paciente + médico fixo) ----------
create table if not exists agenda_consultas (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id) on delete cascade,
    consultorio_id uuid references consultorios(id) on delete set null,

    -- dados completos do paciente, preenchidos pela secretária (ou, no
    -- futuro, pelo próprio paciente via WhatsApp) -- ficam disponíveis
    -- pro médico usar no prontuário, se ele quiser
    paciente_nome text not null,
    paciente_telefone text,
    paciente_data_nascimento date,
    paciente_cpf text,
    convenio text,                    -- nome do convênio, ou 'Particular'
    valor_consulta numeric,
    forma_pagamento text,
    observacoes text,

    data date not null,
    turno text not null check (turno in ('manha', 'tarde', 'noite')),
    horario time not null,            -- múltiplo de 15min dentro do turno

    -- legenda igual à agenda mensalistas (mesmos 7 itens que aparecem embaixo
    -- do calendário na tela): Agendado, Confirmado, Chegou, Em atendimento,
    -- Finalizado, Cancelado, Faltou
    status text not null default 'agendado'
        check (status in ('agendado', 'confirmado', 'chegou', 'em_atendimento', 'finalizado', 'cancelado', 'faltou')),
    origem text not null default 'secretaria' check (origem in ('secretaria', 'whatsapp')),

    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    confirmado_em timestamptz,
    chegou_em timestamptz,
    chamado_em timestamptz,
    finalizado_em timestamptz,

    -- ocupa só 15 minutos a partir do horário marcado -- é isso que o
    -- banco usa pra travar conflito (dois pacientes no mesmo médico,
    -- no mesmo horário)
    intervalo_ocupado tsrange generated always as (
        tsrange(data + horario, data + horario + interval '15 minutes')
    ) stored,

    constraint agenda_consultas_sem_conflito
        exclude using gist (medico_id with =, intervalo_ocupado with &&)
        where (status not in ('cancelado', 'faltou'))
);

create index if not exists idx_agenda_consultas_medico_data on agenda_consultas(medico_id, data);
create index if not exists idx_agenda_consultas_data_status on agenda_consultas(data, status);

-- ---------- 4. Log de chamadas (telão da recepção) ----------
-- Registro à parte (não só o status 'chamado' em agenda_consultas)
-- porque o telão precisa mostrar as ÚLTIMAS 10 chamadas mesmo depois
-- que o paciente já foi atendido e o status da consulta mudou.
create table if not exists chamados_recepcao (
    id uuid primary key default uuid_generate_v4(),
    agenda_consulta_id uuid references agenda_consultas(id) on delete set null,
    medico_id uuid references medicos(id) on delete set null,
    medico_nome text not null,
    sala_nome text not null,
    paciente_nome text not null,
    chamado_em timestamptz not null default now()
);

create index if not exists idx_chamados_recepcao_chamado_em on chamados_recepcao(chamado_em desc);

alter table grade_medico_fixo enable row level security;
alter table agenda_consultas enable row level security;
alter table chamados_recepcao enable row level security;
