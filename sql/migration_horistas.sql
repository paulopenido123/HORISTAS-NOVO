-- Módulo 1: Controle de Horistas (profissionais avulsos que compram horas
-- e agendam pacientes só nos horários que a recepção libera).
--
-- Isso é ADITIVO -- não mexe na Grade de Turnos (medicos.tipo_vinculo =
-- 'avulso', saldo_creditos em R$, pagamento via Asaas), que continua
-- funcionando exatamente como está hoje. O horista é um TIPO NOVO de
-- vínculo ('horista'), com moeda própria (horas, não R$) e crédito 100%
-- manual (sem PIX/cartão) -- é a réplica fiel do sistema real da Lifemax
-- (lifemaxconsultorios.com.br), não uma extensão do avulso.
--
-- A agenda de pacientes do horista usa a MESMA tabela agenda_consultas
-- (e a mesma tela "Agendamento Médico") que já existe para os médicos
-- fixos -- só muda a REGRA de disponibilidade: em vez de seguir a grade
-- fixa (grade_medico_fixo), o horário só fica agendável depois que a
-- recepção "libera" aquele consultório+dia+horário explicitamente
-- (matriz_liberacao), igual ao "Gerar Matriz" do sistema real.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso, depois de
-- migration_agenda_medicos_fixos.sql.

create extension if not exists "uuid-ossp";
create extension if not exists btree_gist;

-- ---------- 1. Novo tipo de vínculo: 'horista' ----------
alter table medicos drop constraint if exists medicos_tipo_vinculo_check;
alter table medicos add constraint medicos_tipo_vinculo_check
    check (tipo_vinculo in ('avulso', 'fixo', 'horista'));
comment on column medicos.tipo_vinculo is
    'avulso = aluga consultório por hora/turno, paga em R$ (Grade de Turnos) | '
    'fixo = tem sala e turno fixos, agenda de pacientes própria | '
    'horista = compra pacotes de horas (manual) e agenda pacientes só em horários liberados pela recepção';

-- ---------- 2. Saldo de horas + configuração de atendimento do horista ----------
-- Saldo em horas (não R$) -- fica só nesse profissional; não interfere no
-- saldo_creditos (R$) usado pelo avulso.
alter table medicos add column if not exists saldo_horas numeric(8,2) not null default 0;

-- Cada horista pode ter um horário de entrada/saída e uma duração de
-- consulta próprios (diferente do médico fixo, que usa sempre os 3 turnos
-- fixos de 15 em 15 min) -- isso é só o PADRÃO sugerido pra ele na tela;
-- quem trava o que pode ser agendado de fato é a matriz_liberacao abaixo.
alter table medicos add column if not exists horista_horario_entrada time;
alter table medicos add column if not exists horista_horario_saida time;
alter table medicos add column if not exists horista_duracao_consulta_min integer not null default 30;

-- ---------- 3. Pacotes de horas (6h / 12h / 24h / 48h) ----------
-- Só define as quantidades que aparecem no formulário de "creditar horas"
-- da secretária -- não tem preço (crédito é 100% manual, sem cobrança
-- automática nessa fase).
create table if not exists pacotes_horas (
    id uuid primary key default uuid_generate_v4(),
    nome text not null,
    quantidade_horas numeric(8,2) not null,
    ativo boolean not null default true,
    ordem integer not null default 0
);
insert into pacotes_horas (nome, quantidade_horas, ordem)
select v.nome, v.horas, v.ordem
from (values ('6 horas', 6, 1), ('12 horas', 12, 2), ('24 horas', 24, 3), ('48 horas', 48, 4)) as v(nome, horas, ordem)
where not exists (select 1 from pacotes_horas);

-- ---------- 4. Extrato de horas (crédito, débito, ajuste, estorno) ----------
-- Auditoria completa: toda vez que o saldo de horas de um horista muda,
-- fica um registro aqui -- é o que alimenta o relatório "Transações".
create table if not exists horas_transacoes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id) on delete cascade,
    tipo text not null check (tipo in ('credito', 'debito', 'ajuste', 'estorno')),
    quantidade_horas numeric(8,2) not null,     -- positivo p/ credito/estorno/ajuste-positivo, negativo p/ debito/ajuste-negativo
    saldo_apos numeric(8,2) not null,
    pacote_id uuid references pacotes_horas(id) on delete set null,
    agenda_consulta_id uuid,                    -- referencia agenda_consultas quando for débito/estorno de um agendamento
    descricao text,
    operador text,                              -- nome de quem fez (secretária logada no admin)
    criado_em timestamptz not null default now()
);
create index if not exists idx_horas_transacoes_medico on horas_transacoes(medico_id, criado_em desc);
create index if not exists idx_horas_transacoes_criado_em on horas_transacoes(criado_em desc);

-- ---------- 5. Matriz de liberação de horários (equivalente ao "Gerar Matriz") ----------
-- Um horário só pode ser agendado por um horista se existir uma linha aqui
-- pra aquele consultório+data+horário, com liberado_ate >= hoje. É a
-- réplica do botão "Liberar para usuários até [data]" do sistema real.
create table if not exists matriz_liberacao (
    id uuid primary key default uuid_generate_v4(),
    consultorio_id uuid not null references consultorios(id) on delete cascade,
    data date not null,
    horario time not null,
    duracao_min integer not null default 30,
    liberado_ate date not null,
    liberado_por text,
    criado_em timestamptz not null default now(),
    unique (consultorio_id, data, horario)
);
create index if not exists idx_matriz_liberacao_data on matriz_liberacao(data);
create index if not exists idx_matriz_liberacao_consultorio on matriz_liberacao(consultorio_id, data);

-- ---------- 6. agenda_consultas: acomodar consultas de horistas ----------
-- tipo_agendamento distingue quem gerou a linha (a tela de agendamento é
-- compartilhada, mas a regra de disponibilidade e o efeito colateral --
-- débito de horas -- são diferentes). duracao_min substitui os "15 min
-- fixos" antigos (que continuam sendo o padrão pro médico fixo).
alter table agenda_consultas add column if not exists tipo_agendamento text not null default 'fixo'
    check (tipo_agendamento in ('fixo', 'horista'));
alter table agenda_consultas add column if not exists duracao_min integer not null default 15;

-- turno passa a poder ser nulo -- consulta de horista não segue os 3
-- turnos fixos (manhã/tarde/noite), só o horário liberado na matriz.
alter table agenda_consultas alter column turno drop not null;

-- recria a coluna gerada (e a trava de conflito que depende dela) usando
-- duracao_min em vez do literal fixo de 15 minutos. Isso não apaga
-- nenhum dado real: os dois campos derivados (intervalo e a trava) são
-- recalculados a partir de data/horario/duracao_min, que continuam intactos.
-- make_interval(mins => duracao_min) em vez de (duracao_min || ' minutes')::interval:
-- o cast de texto pra interval usa uma função STABLE (não IMMUTABLE), que o Postgres
-- rejeita dentro de coluna gerada ("generation expression is not immutable").
-- make_interval monta o interval direto a partir do inteiro, sem passar por parser de texto.
alter table agenda_consultas drop column if exists intervalo_ocupado cascade;
alter table agenda_consultas add column intervalo_ocupado tsrange generated always as (
    tsrange(data + horario, data + horario + make_interval(mins => duracao_min))
) stored;
alter table agenda_consultas add constraint agenda_consultas_sem_conflito
    exclude using gist (medico_id with =, intervalo_ocupado with &&)
    where (status not in ('cancelado', 'faltou'));

alter table pacotes_horas enable row level security;
alter table horas_transacoes enable row level security;
alter table matriz_liberacao enable row level security;
