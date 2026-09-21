-- ============================================================
-- INSTALL_ALL.sql -- GERADO AUTOMATICAMENTE por build_install_all.py
-- NÃO EDITE ESTE ARQUIVO À MÃO -- edite o migration_*.sql
-- correspondente e rode `python3 sql/build_install_all.py` de novo.
--
-- schema.sql primeiro; migrations depois, na ordem que respeita
-- as dependências entre elas (ver EXTRA_DEPS em build_install_all.py).
-- ============================================================

-- ============================================================
-- schema.sql
-- ============================================================

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


-- ============================================================
-- migration_agenda_bloqueios.sql
-- ============================================================

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


-- ============================================================
-- migration_agenda_geral.sql
-- ============================================================

-- Agenda geral do médico — igual à do Google, mas dentro do sistema.
-- Diferente das "reservas" (que são especificamente aluguel de
-- consultório), aqui o médico pode marcar qualquer compromisso.
-- Se ele tiver o Google Agenda conectado, todo evento criado/editado/
-- apagado aqui é automaticamente refletido lá também.

create table if not exists eventos_agenda (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    titulo text not null,
    descricao text,
    data date not null,
    hora_inicio time not null,
    hora_fim time not null,
    google_evento_id text,     -- preenchido se sincronizado com o Google
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create index if not exists idx_eventos_agenda_medico_data on eventos_agenda(medico_id, data);

alter table eventos_agenda enable row level security;


-- ============================================================
-- migration_agenda_medicos_fixos.sql
-- ============================================================

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


-- ============================================================
-- migration_agenda_pacientes.sql
-- ============================================================

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


-- ============================================================
-- migration_agendamento_admin.sql
-- ============================================================

-- Pedido do Paulo em 21/09/2026: botões "Agendar para:" e "Cancelar
-- agendamento" na Agenda Horistas (admin) -- o administrador passa a
-- poder criar ou cancelar reservas EM NOME de um médico avulso. Essas
-- duas colunas marcam quando isso aconteceu, pra Grade de Turnos, Minha
-- Agenda e o extrato de horas do médico poderem avisar claramente que
-- foi o administrador (e não o próprio médico) quem agendou/cancelou.
alter table reservas add column if not exists criado_por_admin boolean not null default false;
alter table reservas add column if not exists cancelado_por_admin boolean not null default false;


-- ============================================================
-- migration_assistente_ativo.sql
-- ============================================================

-- Controla se o assistente de WhatsApp já foi liberado para o médico.
-- Fica falso até o admin clicar em "Ligar assistente" no dashboard —
-- o que só é permitido depois do primeiro pagamento confirmado.

alter table medicos add column if not exists assistente_ativo boolean not null default false;


-- ============================================================
-- migration_assistente_medico_ia.sql
-- ============================================================

-- Módulo 8 — Assistente Médico de IA: analisa o que já está arquivado
-- no Módulo 7 (prontuário/exames) e ajuda o médico na avaliação.
-- Sempre assistivo — o médico decide, nunca o sistema.

create table if not exists analises_medico_ia (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,

    entrada_clinica text not null,        -- o que foi mandado pra IA (criptografado)
    resposta_ia text not null,             -- resposta estruturada (criptografada)
    fontes_consultadas text,               -- JSON com PMIDs/artigos usados, se houve busca

    modelo_ia text not null,               -- ex: 'claude-sonnet-4-6' — registra qual modelo gerou, p/ auditoria
    alertas_backend text,                  -- JSON com alertas da camada de segurança determinística (não-IA)
    avisos_seguranca text,                 -- JSON com o que a camada de segurança pós-resposta corrigiu/bloqueou

    feedback_medico text check (feedback_medico in ('concordo', 'parcial', 'discordo', 'corrigir')),
    feedback_texto text,                   -- se o médico corrigiu algo, o texto da correção (criptografado)
    feedback_em timestamptz,

    criado_em timestamptz not null default now()
);

create index if not exists idx_analises_medico_ia_medico_paciente
    on analises_medico_ia(medico_id, paciente_nome);

alter table analises_medico_ia enable row level security;


-- ============================================================
-- migration_autorizacao_medico.sql
-- ============================================================

-- Liberação manual de acesso pelo admin -- pedido do Paulo em 10/09/2026
-- (mandou print da tela do sistema maior original com o toggle "Usuário
-- autorizado no sistema"): quando um médico se cadastra SOZINHO (ver rota
-- /primeiro-acesso em app/routes/auth.py), o nome dele aparece em
-- VERMELHO na lista de Clientes do admin (app/routes/admin.py, rota
-- /admin/clientes) até o admin clicar em "Liberar acesso". Enquanto não
-- for liberado, ele consegue fazer login normalmente e comprar horas,
-- mas fica BLOQUEADO de reservar consultório (ver a checagem em
-- app/services/reserva_service.py, reservar_turno/reservar_por_hora).
--
-- Coluna nasce com default TRUE (não FALSE) de propósito, por dois
-- motivos:
--   1) Backfill: preenche todo médico que JÁ existia no banco (já usando
--      o sistema normalmente) como autorizado=true, pra ninguém que já
--      estava ativo ser travado de repente por essa mudança.
--   2) Fail-safe pra daqui pra frente: quem cria médico pela função
--      criar_medico() (app/services/supabase_client.py) sempre passa o
--      valor de `autorizado` explicitamente agora -- só a rota de
--      autocadastro público (/primeiro-acesso) passa autorizado=False; o
--      resto (ex: importação de agenda fixa em agenda_fixos_service.py,
--      cadastrado pelo próprio admin a partir de planilha já conferida)
--      continua nascendo autorizado=True. Deixar o DEFAULT da coluna
--      também em TRUE significa que se algum caminho novo esquecer de
--      passar esse campo no futuro, o comportamento "falha aberto" é
--      igual ao de sempre (médico consegue usar o sistema normalmente)
--      em vez de um bloqueio silencioso e difícil de rastrear.
alter table medicos add column if not exists autorizado boolean not null default true;


-- ============================================================
-- migration_cancelado_em.sql
-- ============================================================

-- Guarda o instante em que uma reserva foi CANCELADA (distinto de
-- criado_em, que é sempre o instante em que ela foi feita) -- pedido do
-- Paulo em 10/09/2026, junto com o botão "Cancelar" na Grade de Turnos e
-- em "Minha Agenda": sem essa coluna não dava pra saber QUANDO o
-- cancelamento aconteceu, o que é necessário pro relatório de
-- "Agendamentos" (aba Relatórios do admin) mostrar a ocorrência do
-- cancelamento na linha do tempo certa.
alter table reservas add column if not exists cancelado_em timestamptz;


-- ============================================================
-- migration_clientes_medico.sql
-- ============================================================

-- Cadastro rápido de clientes/contatos de cada médico (Nome, endereço,
-- e-mail e telefone/WhatsApp) -- pedido do Paulo em 10/09/2026, botão
-- "Incluir dados cliente" na página do médico (área do cliente).
--
-- OBS: isso é só um cadastro de contato solto, sem vínculo com
-- consulta/prontuário -- esse pacote (Reserva por Hora) não inclui a
-- Agenda de Pacientes/Prontuários do sistema maior da Lifemax.

create table if not exists clientes_medico (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    nome text not null,
    endereco text,
    email text,
    telefone text,
    criado_em timestamptz not null default now()
);

create index if not exists idx_clientes_medico_medico_id on clientes_medico(medico_id);

alter table clientes_medico enable row level security;


-- ============================================================
-- migration_contabilidade_medica.sql
-- ============================================================

-- Módulo 4 — Contabilidade Médica. Escopo do MVP (seção 26 do
-- documento de arquitetura): Receitas, Despesas, Livro Caixa,
-- Documentos (com OCR/IA), Dashboard, Relatório pro contador.
--
-- Dado sensível (CPF/CNPJ, valores financeiros) — os campos de
-- identificação ficam criptografados, igual já fazemos no Módulo 6
-- (Prontuário).

create table if not exists receitas_medicas (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),

    data date not null,                    -- data do serviço
    data_recebimento date,                 -- pode ser diferente da data do serviço (regime de caixa)
    paciente_nome text,                    -- opcional — nem toda receita tem paciente associado

    tipo_pagador text not null check (tipo_pagador in
        ('pessoa_fisica', 'pessoa_juridica', 'plano_saude', 'convenio', 'hospital', 'clinica', 'particular', 'exterior', 'outro')),
    nome_pagador text not null,
    cpf_cnpj_pagador text,                  -- criptografado

    tipo_servico text,
    descricao text,

    valor_bruto numeric(12,2) not null,
    desconto numeric(12,2) not null default 0,
    valor_liquido numeric(12,2) not null,

    -- Retenções (só relevante quando o pagador é Pessoa Jurídica — seção 5 do documento)
    irrf numeric(12,2) default 0,
    inss_retido numeric(12,2) default 0,
    iss_retido numeric(12,2) default 0,
    outros_tributos_retidos numeric(12,2) default 0,

    forma_pagamento text,
    numero_recibo text,

    -- Receita Saúde (obrigatório para PF desde 01/01/2025 — seção 4)
    numero_receita_saude text,
    receita_saude_status text default 'pendente' check (receita_saude_status in ('pendente', 'emitido', 'nao_aplicavel')),

    documento_origem_id uuid,               -- referência opcional a um documento anexado
    status text not null default 'confirmado' check (status in ('confirmado', 'pendente', 'cancelado')),

    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);
create index if not exists idx_receitas_medicas_medico_data on receitas_medicas(medico_id, data);

create table if not exists despesas_medicas (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),

    data date not null,
    data_pagamento date,
    fornecedor text not null,
    cpf_cnpj_fornecedor text,               -- criptografado

    descricao text,
    categoria text not null,
    subcategoria text,

    valor_bruto numeric(12,2) not null,
    forma_pagamento text,

    -- Classificação fiscal (seção 6, 9, 10, 12, 13)
    dedutibilidade text not null default 'revisao_necessaria'
        check (dedutibilidade in ('dedutivel', 'nao_dedutivel', 'revisao_necessaria')),
    motivo_classificacao text,
    regra_fiscal_id uuid,                   -- qual regra do FiscalRulesEngine gerou essa classificação
    percentual_uso_profissional numeric(5,2) default 100,   -- ex: imóvel residencial usado em parte (seção 10)
    valor_dedutivel numeric(12,2) default 0,
    valor_nao_dedutivel numeric(12,2) default 0,

    -- Rastreabilidade da IA (seção 23 — nunca decide sozinha)
    ai_confidence numeric(4,2),
    ai_sugestao_categoria text,
    ai_sugestao_dedutibilidade text,
    ai_justificativa text,
    usuario_confirmou boolean not null default false,

    tipo_documento text,
    numero_documento text,
    documento_id uuid,

    observacoes text,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);
create index if not exists idx_despesas_medicas_medico_data on despesas_medicas(medico_id, data);

-- DocumentVault (seção 11) — arquivo de qualquer documento fiscal,
-- vinculado (ou não) a uma receita/despesa específica
create table if not exists documentos_fiscais (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),

    transacao_tipo text check (transacao_tipo in ('receita', 'despesa', null)),
    transacao_id uuid,

    tipo_documento text not null,           -- nota fiscal, recibo, boleto, comprovante, contrato, etc
    storage_path text not null,             -- caminho no bucket privado (criptografado, igual Módulo 6)
    nome_arquivo text not null,

    data_emissao date,
    fornecedor_extraido text,               -- o que o OCR/IA extraiu, pra conferência
    cpf_cnpj_extraido text,
    valor_extraido numeric(12,2),

    status text not null default 'pendente_revisao' check (status in ('pendente_revisao', 'confirmado', 'descartado')),
    criado_em timestamptz not null default now()
);
create index if not exists idx_documentos_fiscais_medico on documentos_fiscais(medico_id);

-- FiscalRulesEngine (seção 13) — regras configuráveis, sem valor/lógica fiscal fixo no código
create table if not exists regras_fiscais (
    id uuid primary key default uuid_generate_v4(),
    categoria text not null,                -- bate com o plano de contas (seção 7)
    subcategoria text,
    classificacao_padrao text not null check (classificacao_padrao in ('dedutivel', 'nao_dedutivel', 'revisao_necessaria')),
    descricao text not null,
    referencia_legal text,
    vigencia_inicio date not null default '2026-01-01',
    vigencia_fim date,
    status text not null default 'ativa' check (status in ('ativa', 'inativa')),
    criado_em timestamptz not null default now()
);

-- Configuração de tabela de imposto por ano (seção 16, 24) — nenhuma
-- alíquota fica hardcoded no código
create table if not exists tabela_imposto_anual (
    id uuid primary key default uuid_generate_v4(),
    ano integer not null unique,
    faixas_json text not null,              -- JSON com as faixas de alíquota daquele ano (preenchido manualmente por enquanto)
    criado_em timestamptz not null default now()
);

-- Livro Caixa — controle mensal de excesso de despesa dedutível
-- (seção 15): quando despesa dedutível > receita do mês, o excedente
-- fica "guardado" pra compensar nos meses seguintes, até dezembro —
-- nunca passa pro ano seguinte automaticamente.
create table if not exists livro_caixa_mensal (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    ano integer not null,
    mes integer not null check (mes between 1 and 12),

    receita_do_mes numeric(12,2) not null default 0,
    despesa_dedutivel_do_mes numeric(12,2) not null default 0,
    excesso_recebido_de_meses_anteriores numeric(12,2) not null default 0,
    deducao_utilizada_no_mes numeric(12,2) not null default 0,
    excesso_a_compensar numeric(12,2) not null default 0,   -- o que sobra pro mês seguinte (zera em janeiro)

    calculado_em timestamptz not null default now(),
    unique (medico_id, ano, mes)
);

alter table receitas_medicas enable row level security;
alter table despesas_medicas enable row level security;
alter table documentos_fiscais enable row level security;
alter table regras_fiscais enable row level security;
alter table tabela_imposto_anual enable row level security;
alter table livro_caixa_mensal enable row level security;


-- ============================================================
-- migration_creditos.sql
-- ============================================================

-- Migração: sistema de créditos, autenticação de médicos, preços
-- configuráveis e histórico de pagamentos PIX (Asaas).
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso (depois dos outros arquivos sql/).

-- Médicos ganham login (senha), saldo de créditos e email opcional
-- (usado como alternativa de notificação quando o WhatsApp ainda não
-- estiver configurado)
alter table medicos add column if not exists senha_hash text;
alter table medicos add column if not exists saldo_creditos numeric(10,2) not null default 0;
alter table medicos add column if not exists alerta_saldo_baixo_enviado boolean not null default false;
alter table medicos add column if not exists email text;

-- Preços configuráveis pelo admin (uma linha só, sempre atualizada)
create table if not exists precos (
    id uuid primary key default uuid_generate_v4(),
    preco_hora numeric(10,2) not null default 0,
    preco_turno numeric(10,2) not null default 0,
    atualizado_em timestamptz not null default now()
);
insert into precos (preco_hora, preco_turno)
select 50.00, 150.00
where not exists (select 1 from precos);

-- Histórico de créditos: toda compra e todo consumo fica registrado aqui
create table if not exists creditos_transacoes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    tipo text not null check (tipo in ('compra', 'consumo', 'ajuste')),
    valor numeric(10,2) not null,          -- positivo p/ compra e ajuste positivo, negativo p/ consumo
    saldo_apos numeric(10,2) not null,
    descricao text,
    reserva_id uuid references reservas(id),
    pagamento_id uuid,                      -- referencia pagamentos_pix, quando for uma compra
    criado_em timestamptz not null default now()
);
create index if not exists idx_creditos_transacoes_medico on creditos_transacoes(medico_id, criado_em desc);

-- Cobranças PIX geradas via Asaas
create table if not exists pagamentos_pix (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    asaas_payment_id text unique,
    asaas_customer_id text,
    valor numeric(10,2) not null,
    status text not null default 'pendente' check (status in ('pendente', 'pago', 'expirado', 'cancelado')),
    qr_code_base64 text,
    copia_e_cola text,
    criado_em timestamptz not null default now(),
    pago_em timestamptz
);
create index if not exists idx_pagamentos_pix_medico on pagamentos_pix(medico_id, criado_em desc);
create index if not exists idx_pagamentos_pix_asaas_id on pagamentos_pix(asaas_payment_id);

alter table precos enable row level security;
alter table creditos_transacoes enable row level security;
alter table pagamentos_pix enable row level security;


-- ============================================================
-- migration_dados_pessoais_e_consentimento.sql
-- ============================================================

-- "Dados Pessoais" do médico -- campos que hoje só existem na planilha
-- de 74 médicos (lida só pro WhatsApp responder perguntas, nunca
-- editável pelo próprio médico). Agora viram campos de verdade no
-- cadastro dele, editáveis na nova tela "Dados Pessoais".

alter table medicos add column if not exists valor_consulta numeric(10,2);
alter table medicos add column if not exists tempo_consulta text;
alter table medicos add column if not exists formas_pagamento text;
alter table medicos add column if not exists politica_cancelamento text;
alter table medicos add column if not exists retorno_particular text;
alter table medicos add column if not exists retorno_convenio text;
alter table medicos add column if not exists observacoes_atendimento text;
alter table medicos add column if not exists idade_minima text;

comment on column medicos.valor_consulta is 'Valor da consulta particular -- editável pelo médico em "Dados Pessoais"';
comment on column medicos.tempo_consulta is 'Tempo médio de consulta (ex: "30 minutos")';
comment on column medicos.formas_pagamento is 'Formas de pagamento aceitas (texto livre, ex: "Pix, cartão, dinheiro")';
comment on column medicos.politica_cancelamento is 'Política de cancelamento/remarcação';
comment on column medicos.retorno_particular is 'Regra de retorno pra paciente particular (ex: "Grátis em até 30 dias")';
comment on column medicos.retorno_convenio is 'Regra de retorno pra paciente de convênio';
comment on column medicos.observacoes_atendimento is 'Observações gerais sobre o atendimento';
comment on column medicos.idade_minima is 'Idade mínima atendida, se houver restrição';

-- ---------------------------------------------------------------------
-- Dados para Rede Social (Rede Lifemax): telefone PÚBLICO, separado do
-- telefone de login (esse nunca é exibido publicamente -- é a
-- credencial de acesso do médico) + consentimento explícito de
-- divulgação (LGPD).
-- ---------------------------------------------------------------------
alter table medicos add column if not exists telefone_publico text;
alter table medicos add column if not exists rede_lifemax_consentimento boolean not null default false;
alter table medicos add column if not exists rede_lifemax_consentimento_em timestamptz;

comment on column medicos.telefone_publico is 'Telefone de contato exibido no perfil público da Rede Lifemax -- diferente do telefone de login, nunca exibido';
comment on column medicos.rede_lifemax_consentimento is 'Médico marcou "Autorizo a Lifemax a divulgar os dados por mim aqui inseridos" -- LGPD';


-- ============================================================
-- migration_endereco_medico.sql
-- ============================================================

-- Endereço completo do médico (CEP, cidade, etc.).
--
-- Paulo pediu pra guardar o endereço completo de cada médico no
-- cadastro (tanto o cadastro feito pelo admin quanto o feito pela
-- secretária em Agenda Fixos). É só informativo por enquanto -- não
-- muda nenhuma regra de negócio, nenhuma cobrança, nenhuma agenda.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

alter table medicos add column if not exists endereco_cep varchar(9);
alter table medicos add column if not exists endereco_rua text;
alter table medicos add column if not exists endereco_numero varchar(20);
alter table medicos add column if not exists endereco_complemento text;
alter table medicos add column if not exists endereco_bairro text;
alter table medicos add column if not exists endereco_cidade text;
alter table medicos add column if not exists endereco_estado varchar(2);

comment on column medicos.endereco_cep is 'CEP do médico, só números ou com hífen (ex: 30130-000)';
comment on column medicos.endereco_rua is 'Rua/Avenida do endereço do médico';
comment on column medicos.endereco_numero is 'Número do endereço do médico';
comment on column medicos.endereco_complemento is 'Complemento do endereço (apto, sala, bloco, etc.)';
comment on column medicos.endereco_bairro is 'Bairro do endereço do médico';
comment on column medicos.endereco_cidade is 'Cidade do endereço do médico';
comment on column medicos.endereco_estado is 'UF (sigla do estado) do endereço do médico';


-- ============================================================
-- migration_endereco_padrao_lifemax.sql
-- ============================================================

-- Endereço padrão da Lifemax, salvo como CONFIGURAÇÃO permanente (não
-- mais uma ação em lote manual) -- pedido do Paulo: o pino do mapa
-- tem que aparecer pra QUALQUER médico sem endereço próprio, agora e
-- no futuro (um médico novo, cadastrado daqui a 6 meses, também tem
-- que aparecer no mapa sem precisar de nenhuma ação manual do admin).
--
-- Guardado na mesma tabela `precos` de sempre (linha única, já usada
-- pra preço de hora/turno e pra config de IA).

alter table precos add column if not exists endereco_padrao_cep text;
alter table precos add column if not exists endereco_padrao_rua text;
alter table precos add column if not exists endereco_padrao_numero text;
alter table precos add column if not exists endereco_padrao_complemento text;
alter table precos add column if not exists endereco_padrao_bairro text;
alter table precos add column if not exists endereco_padrao_cidade text;
alter table precos add column if not exists endereco_padrao_estado text;
alter table precos add column if not exists endereco_padrao_latitude numeric(9,6);
alter table precos add column if not exists endereco_padrao_longitude numeric(9,6);

comment on column precos.endereco_padrao_rua is 'Endereço padrão da Lifemax (ex: prédio da sede) -- usado automaticamente no mapa/perfil de QUALQUER médico que ainda não tem endereço próprio cadastrado';


-- ============================================================
-- migration_financeiro_medico.sql
-- ============================================================

-- Módulo Financeiro do médico — emissão de recibos, leitura de despesa
-- por foto (IA Luna) e exportação para a contabilidade. Rode depois de
-- migration_contabilidade_medica.sql.

-- CRM do médico — necessário para aparecer no recibo emitido para o paciente.
alter table medicos add column if not exists crm text;

-- Bucket de storage para os PDFs de recibo (público, pelo mesmo motivo
-- do bucket 'consultorios': o WhatsApp Cloud API só consegue mandar um
-- documento a partir de uma URL que ele mesmo consiga baixar sem login).
--
-- ⚠️ Migração pra Neon (10/09/2026): o schema "storage" (com as tabelas
-- storage.buckets/storage.objects e as "policies" de storage) é uma
-- coisa específica do Supabase -- não existe em Postgres puro nem no
-- Neon. O bloco abaixo só roda se esse schema existir (ou seja: se você
-- algum dia reinstalar esse SQL contra um projeto Supabase de novo) --
-- no Neon, o bucket de recibos (se/quando esse módulo for usado por
-- este pacote) deve ser criado direto no Neon Console ou via `neon
-- buckets create`, não por SQL. Veja app/services/neon_storage.py.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('recibos', 'recibos', true)
    on conflict (id) do nothing;

    -- Postgres não aceita "create policy if not exists" (essa cláusula não
    -- existe para policy) -- por isso apaga antes de recriar, o que também
    -- deixa essa migração segura de rodar de novo sem dar erro.
    drop policy if exists "Recibos sao publicos para leitura" on storage.objects;
    create policy "Recibos sao publicos para leitura"
    on storage.objects for select
    using (bucket_id = 'recibos');

    drop policy if exists "Somente service role gerencia recibos" on storage.objects;
    create policy "Somente service role gerencia recibos"
    on storage.objects for all
    using (bucket_id = 'recibos' and auth.role() = 'service_role');
  end if;
end $$;


-- ============================================================
-- migration_funcionarios.sql
-- ============================================================

-- Tabela que faltava no pacote (achado em 10/09/2026, testando a troca de
-- preços de ponta a ponta): supabase_client.listar_funcionarios_ativos()
-- e reserva_service._pos_reserva() já dependiam de verdade de uma tabela
-- `funcionarios` (só guarda e-mails pra avisar quando um médico reserva
-- um turno/hora avulsa -- é citada até no comentário de
-- migration_secretarias.sql como "a tabela funcionarios, que só guarda
-- e-mails pra notificação"), mas nenhuma migração deste pacote criava
-- essa tabela. Resultado: toda reserva por hora ou por turno quebrava
-- com 500 (UndefinedTable) DEPOIS de já ter debitado o crédito do
-- médico e criado a reserva -- ver o try/except adicionado em
-- reserva_service._pos_reserva, que agora protege contra isso mesmo se
-- essa tabela ficar vazia ou indisponível de novo no futuro.
--
-- Não existe tela admin pra cadastrar esses e-mails ainda -- por
-- enquanto, insira direto pelo SQL Editor do Neon, por exemplo:
--   insert into funcionarios (nome, email) values ('Recepção', 'recepcao@lifemax.com.br');

create table if not exists funcionarios (
    id uuid primary key default uuid_generate_v4(),
    nome text not null,
    email text not null,
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

alter table funcionarios enable row level security;


-- ============================================================
-- migration_google_calendar.sql
-- ============================================================

-- Guarda a conexão OAuth de cada médico com o Google Agenda dele.
-- Os tokens ficam só no backend (nunca expostos ao navegador) — são
-- usados pelo servidor para checar conflito e criar eventos em nome
-- do médico, com a autorização que ele deu no fluxo do Google.

alter table medicos add column if not exists google_calendar_conectado boolean not null default false;
alter table medicos add column if not exists google_access_token text;
alter table medicos add column if not exists google_refresh_token text;
alter table medicos add column if not exists google_token_expira_em timestamptz;
alter table medicos add column if not exists google_calendar_id text default 'primary';

-- Guarda o ID do evento criado no Google Agenda, para conseguir
-- cancelar/atualizar o evento se a reserva for cancelada depois.
alter table reservas add column if not exists google_evento_id text;


-- ============================================================
-- migration_horas_transacoes.sql
-- ============================================================

-- Guarda a quantidade de horas de cada reserva diretamente na
-- transação de crédito, para os relatórios do dashboard poderem
-- somar horas consumidas com precisão (em vez de estimar a partir do
-- valor em R$, que é impreciso com preço escalonado).

alter table creditos_transacoes add column if not exists quantidade_horas integer;


-- ============================================================
-- migration_horistas.sql
-- ============================================================

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


-- ============================================================
-- migration_ia_precos.sql
-- ============================================================

-- Preço por token e margem da IA paga (OpenAI), editáveis direto no
-- Dashboard Admin (painel "IA — Consumo de tokens e faturamento") em
-- vez de só por variável de ambiente. Guardado na mesma tabela
-- `precos` de sempre (linha única, junto com preço de hora/turno).
--
-- Os valores padrão abaixo são os mesmos que já estavam valendo hoje
-- (env var / tabela PRECOS_USD_POR_1K do gpt-5.6-luna em
-- ia_uso_service.py) -- rodar essa migração não muda nenhuma cobrança
-- que já estava acontecendo, só passa a deixar isso editável.

alter table precos add column if not exists ia_percentual_aumento numeric not null default 400;
alter table precos add column if not exists ia_preco_entrada_usd_1k numeric not null default 0.00020;
alter table precos add column if not exists ia_preco_saida_usd_1k numeric not null default 0.00120;
alter table precos add column if not exists ia_usd_para_brl numeric not null default 5.16;

comment on column precos.ia_percentual_aumento is 'Percentual de aumento (ganho da empresa) sobre o custo real da IA -- 400 = cobra 5x o custo (1 + 400/100)';
comment on column precos.ia_preco_entrada_usd_1k is 'Preço em USD por 1.000 tokens de ENTRADA (prompt) do modelo de IA pago -- confira em platform.openai.com/docs/pricing';
comment on column precos.ia_preco_saida_usd_1k is 'Preço em USD por 1.000 tokens de SAÍDA (resposta) do modelo de IA pago';
comment on column precos.ia_usd_para_brl is 'Cotação do dólar usada pra converter o custo da IA (sempre em USD) pra reais';


-- ============================================================
-- migration_ia_percentual_200.sql
-- ============================================================

-- Ajusta o percentual de aumento cobrado sobre o custo real da IA para
-- 200% (pedido do Paulo em 21/09/2026, junto com a recriação da compra
-- de créditos de IA): cobrar 200% em cima do que o GPT/Luna custou de
-- verdade, ou seja, 3x o custo real (1 + 200/100). O valor anterior era
-- o default de migration_ia_precos.sql (400 = 5x). A partir daqui isso
-- também fica editável na tela admin "Controle de IA" (ver
-- app/routes/admin.py / app/templates/admin_controle_ia.html), então
-- essa atualização aqui é só o ponto de partida -- o Paulo pode mudar
-- de novo a qualquer momento pela tela, sem precisar rodar SQL.
update precos set ia_percentual_aumento = 200;


-- ============================================================
-- migration_ia_uso.sql
-- ============================================================

-- Sistema de cobrança por uso de IA (Gemini) — "calculador de consumo".
--
-- Ideia geral, confirmada com o Paulo:
--   1. No primeiro acesso, o médico ganha um crédito único de teste
--      (ex: R$ 5,00) na MESMA carteira que já existe hoje (saldo_creditos) —
--      não é uma carteira separada.
--   2. Cada módulo de IA que o médico ativa (secretaria / prontuário /
--      financeiro) ganha 30 dias grátis a partir do primeiro uso daquele
--      módulo — depois disso, cada chamada de IA passa a debitar da
--      carteira.
--   3. Duas ações específicas, mais caras/sensíveis, têm um teto de uso
--      grátis À PARTE, que vale por médico PRA SEMPRE (não renova por mês,
--      não depende dos 30 dias — conta mesmo dentro do período de trial):
--        - analisar prontuário (Módulo 7/8): 3 grátis
--        - enviar confirmação/cobrança pro paciente (Secretaria): 10 grátis
--   4. Depois que o trial de 30 dias de um módulo acaba, o sistema BLOQUEIA
--      o uso de IA daquele módulo e avisa o médico (não deixa continuar
--      "por fora" e cobrar depois).
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso, depois dos outros arquivos sql/.

-- 1. Crédito de boas-vindas: controla se o médico já recebeu (só pode ganhar 1 vez)
alter table medicos add column if not exists ia_trial_creditado boolean not null default false;

-- 2. Estado de ativação de cada módulo de IA, por médico. A linha só
--    existe a partir do primeiro uso — "ativado_em" marca o início da
--    contagem dos 30 dias grátis daquele módulo especificamente.
create table if not exists medico_modulos_ia (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    modulo_slug text not null check (modulo_slug in ('secretaria', 'prontuario', 'financeiro')),
    ativado_em timestamptz not null default now(),
    trial_fim timestamptz not null,  -- calculado na hora de ativar = ativado_em + 30 dias
    unique (medico_id, modulo_slug)
);
create index if not exists idx_medico_modulos_ia_medico on medico_modulos_ia(medico_id);

-- 3. Tetos de uso grátis "pra sempre" (não renovam), por ação específica.
--    Guarda só o contador — o limite de cada ação fica no código
--    (ia_uso_service.py), pra ser fácil de ajustar sem precisar de SQL novo.
create table if not exists medico_ia_contadores (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    acao text not null check (acao in ('prontuario_analise', 'secretaria_envio_paciente')),
    usados integer not null default 0,
    unique (medico_id, acao)
);

-- 4. Extrato completo de cada chamada de IA medida — inclusive as
--    gratuitas (trial/teto), pra dar transparência total no painel do
--    médico e pro admin conseguir acompanhar custo real x cobrado.
create table if not exists ia_uso_log (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    modulo_slug text not null,
    acao text not null,
    provedor text not null,             -- 'gemini' | 'claude'
    modelo text,
    tokens_entrada integer not null default 0,
    tokens_saida integer not null default 0,
    custo_real numeric(10,4) not null default 0,     -- o que o provedor de IA realmente cobrou (estimado)
    custo_cobrado numeric(10,2) not null default 0,   -- o que foi debitado do médico (0 se foi grátis)
    gratuito boolean not null default false,
    motivo_gratuito text,                -- 'credito_boas_vindas' | 'trial_30_dias' | 'teto_uso_gratis' | null
    descricao text,
    criado_em timestamptz not null default now()
);
create index if not exists idx_ia_uso_log_medico on ia_uso_log(medico_id, criado_em desc);

-- 5. Marca, na própria transação da carteira, se foi um gasto de IA ou de
--    horas de consultório — só pra relatório (o saldo continua sendo UM
--    número só, como definido). Não quebra nada que já existe: toda linha
--    antiga vira 'horas' por padrão.
alter table creditos_transacoes add column if not exists categoria text not null default 'horas'
    check (categoria in ('horas', 'ia'));

alter table medico_modulos_ia enable row level security;
alter table medico_ia_contadores enable row level security;
alter table ia_uso_log enable row level security;


-- ============================================================
-- migration_matriz_template.sql
-- ============================================================

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


-- ============================================================
-- migration_medicos_convenios.sql
-- ============================================================

-- Lista de convênios aceitos por cada médico -- cadastrada pela
-- secretária/admin no cadastro/edição do médico (uma lista fixa, não
-- calculada a partir do histórico de consultas). Usada pelo botão
-- "Convênios" na tela Agenda Fixos, que só mostra essa lista.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

alter table medicos add column if not exists convenios text[] not null default '{}';


-- ============================================================
-- migration_modulos.sql
-- ============================================================

-- Sistema de módulos: cada funcionalidade grande do sistema (Assistente
-- Pessoal, Recibos, Contabilidade, Nota Fiscal, Videoconferência,
-- Prescrição, Prontuário, Marketing) vira uma linha aqui, com um status.
--
-- Médicos "beta tester" (por enquanto, só você) veem TODOS os módulos,
-- inclusive os "em desenvolvimento" (aparecem como "em breve" na tela).
-- Médicos comuns só veem os módulos com status 'ativo'.

alter table medicos add column if not exists is_beta_tester boolean not null default false;

create table if not exists modulos (
    id uuid primary key default uuid_generate_v4(),
    numero integer not null unique,
    slug text not null unique,
    nome text not null,
    descricao text,
    icone text,
    status text not null default 'em_desenvolvimento' check (status in ('em_desenvolvimento', 'beta', 'ativo')),
    rota text,          -- caminho dentro do sistema, quando já existir (ex: '/painel')
    ordem integer not null default 0
);

insert into modulos (numero, slug, nome, descricao, icone, status, rota, ordem) values
(1, 'assistente-pessoal', 'Assistente Pessoal',
   'Contato com paciente, agenda, reservas de consultório e créditos — via WhatsApp e painel web.',
   '🤖', 'ativo', '/painel', 1),
(2, 'recibos', 'Recibos de Pagamento',
   'Gerar recibo em PDF para os pagamentos recebidos de pacientes.',
   '🧾', 'em_desenvolvimento', null, 2),
(3, 'contabilidade', 'Preparação Contábil',
   'Relatório mensal/anual pronto para entregar ao contador do médico.',
   '📊', 'em_desenvolvimento', null, 3),
(4, 'nota-fiscal-nfse', 'Nota Fiscal (Receita Federal)',
   'Emissão de nota fiscal de serviço eletrônica, integrada a um provedor homologado.',
   '📄', 'em_desenvolvimento', null, 4),
(5, 'videoconferencia', 'Videoconferência',
   'Consulta por vídeo com o paciente, direto pelo painel web (fora do WhatsApp).',
   '🎥', 'em_desenvolvimento', null, 5),
(6, 'prescricao', 'Prescrição Médica Digital',
   'Emissão de receita digital com validade jurídica, via parceiro homologado (ex: Memed).',
   '💊', 'em_desenvolvimento', null, 6),
(7, 'prontuario', 'Prontuário e Exames',
   'Receber exames do paciente e comparar com o histórico do prontuário.',
   '🗂️', 'em_desenvolvimento', null, 7),
(8, 'marketing', 'Análise Mercadológica',
   'Sugestões de captação de pacientes com base nos dados do próprio sistema.',
   '📈', 'em_desenvolvimento', null, 8)
on conflict (numero) do nothing;

alter table modulos enable row level security;


-- ============================================================
-- migration_modulos_renomear.sql
-- ============================================================

-- Reorganiza a numeração e os nomes dos módulos conforme definição do
-- Paulo: Módulo 1 fica só com a venda de horas/turnos avulsos (o que já
-- está funcionando), e entra um novo Módulo 2 — Integração para
-- Clientes Fixos. Os demais módulos são renumerados em sequência.
--
-- Como não existe nenhuma outra tabela referenciando modulos.id por
-- chave estrangeira, é seguro apagar e recriar a lista inteira.

delete from modulos;

insert into modulos (numero, slug, nome, descricao, icone, status, rota, ordem) values

(1, 'venda-horas-avulsas', 'Venda de Horas Avulsas',
   'Venda de horas e turnos avulsos de consultório — reservas, créditos, PIX/cartão, '
   'confirmação de consulta e assistente via WhatsApp e painel web.',
   '🤖', 'ativo', '/painel', 1),

(2, 'clientes-fixos', 'Integração para Clientes Fixos',
   'Modelo de plano/assinatura fixa para médicos com uso recorrente do coworking — '
   'faturamento e agenda diferenciados de quem usa por hora avulsa.',
   '🔁', 'em_desenvolvimento', null, 2),

(3, 'recibos', 'Recibos de Pagamento',
   'Gerar recibo em PDF para os pagamentos recebidos de pacientes.',
   '🧾', 'em_desenvolvimento', null, 3),

(4, 'contabilidade', 'Preparação Contábil',
   'Relatório mensal/anual pronto para entregar ao contador do médico.',
   '📊', 'em_desenvolvimento', null, 4),

(5, 'nota-fiscal-nfse', 'Nota Fiscal (Receita Federal)',
   'Emissão de nota fiscal de serviço eletrônica, integrada a um provedor homologado.',
   '📄', 'em_desenvolvimento', null, 5),

(6, 'videoconferencia', 'Videoconferência e Prescrição',
   'Ambiente fechado de vídeo entre médico e paciente (dois ou mais usuários), com '
   'emissão de receita digital direto durante a chamada.',
   '🎥', 'em_desenvolvimento', null, 6),

(7, 'prescricao', 'Prescrição Médica Digital',
   'Emissão de receita digital com validade jurídica, via parceiro homologado (ex: Memed) — '
   'usada tanto dentro do Módulo 6 (vídeo) quanto de forma avulsa. '
   'Ideia futura: comparação de preços/disponibilidade de medicamentos entre farmácias — '
   'sem influenciar a escolha clínica do médico, por causa da vedação do CFM a comissão por indicação.',
   '💊', 'em_desenvolvimento', null, 7),

(8, 'prontuario', 'Prontuário e Exames',
   'Receber exames do paciente e comparar com o histórico do prontuário.',
   '🗂️', 'em_desenvolvimento', null, 8),

(9, 'marketing', 'Análise Mercadológica',
   'Sugestões de captação de pacientes com base nos dados do próprio sistema.',
   '📈', 'em_desenvolvimento', null, 9),

(10, 'suprimentos', 'Fornecimento de Medicamentos e Suprimentos',
   'Marketplace conectando fabricantes e fornecedores aos médicos, como intermediário '
   'de compra de equipamentos e suprimentos médicos.',
   '📦', 'em_desenvolvimento', null, 10);


-- ============================================================
-- migration_notas_fiscais.sql
-- ============================================================

-- Migração: campos de nota fiscal nos pagamentos, e CPF/CNPJ do médico
-- (necessário para emitir a nota). Rode depois de migration_creditos.sql.

alter table pagamentos_pix add column if not exists nota_fiscal_status text
    not null default 'nao_emitida' check (nota_fiscal_status in ('nao_emitida', 'emitida', 'enviada'));
alter table pagamentos_pix add column if not exists nota_fiscal_numero text;
alter table pagamentos_pix add column if not exists nota_fiscal_url text;
alter table pagamentos_pix add column if not exists nota_fiscal_emitida_em timestamptz;
alter table pagamentos_pix add column if not exists nota_fiscal_enviada_em timestamptz;

-- CPF ou CNPJ do médico — necessário para emitir a nota fiscal em nome dele
alter table medicos add column if not exists cpf_cnpj text;


-- ============================================================
-- migration_notificacoes_email.sql
-- ============================================================

-- Avisos automáticos por e-mail -- pedido do Paulo em 11/09/2026:
--   1) confirmação do e-mail do médico (link que ele clica; depois disso
--      aparece uma ⭐ do lado do e-mail na lista de Clientes do admin);
--   2) aviso ao admin por e-mail quando um médico novo se autocadastra
--      pelo site e precisa ser liberado;
--   3) aviso ao médico por e-mail quando o admin libera o acesso dele;
--   4) recibo por e-mail quando o médico compra horas;
--   5) confirmação de agendamento/cancelamento pro médico + e-mail pro
--      paciente com dia, endereço e consultório -- inclui campo de
--      "confirmação da hora" (pro médico bater o horário exato antes de
--      mandar, já que reserva de TURNO cobre um período inteiro) e
--      suporte a mais de um paciente na mesma reserva.
--
-- Os tokens de confirmação de e-mail reaproveitam a MESMA tabela
-- `tokens_recuperacao_senha` (ver migration_recuperacao_senha.sql) que já
-- existe pra "esqueci minha senha"/primeiro acesso -- só usa um
-- `contexto` novo ('confirmar_email'), sem precisar de tabela nova.

alter table medicos add column if not exists email_confirmado boolean not null default false;

-- O token de confirmação de e-mail reaproveita a coluna `contexto` de
-- tokens_recuperacao_senha (ver migration_primeiro_acesso_admin.sql),
-- que só aceitava ('recuperacao', 'primeiro_acesso') até aqui -- precisa
-- liberar o valor novo 'confirmar_email' no check constraint.
alter table tokens_recuperacao_senha drop constraint if exists tokens_recuperacao_senha_contexto_check;
alter table tokens_recuperacao_senha add constraint tokens_recuperacao_senha_contexto_check
    check (contexto in ('recuperacao', 'primeiro_acesso', 'confirmar_email'));

-- Confirmação de horário da reserva (pro médico bater o olho e confirmar
-- a hora exata da consulta antes de mandar o e-mail pro paciente -- útil
-- principalmente pra reserva de TURNO, que cobre um período inteiro em
-- vez de um horário exato).
alter table reservas add column if not exists hora_confirmada text;

-- Pacientes de uma mesma reserva que devem receber o e-mail de
-- confirmação de agendamento -- por padrão só o paciente marcado em
-- "Incluir/alterar paciente" (reservas.paciente_id), mas o médico pode
-- incluir mais de um com o botão "+ Adicionar paciente" na tela "Minha
-- agenda" (ex: mais de um paciente marcado pro mesmo horário/turno).
-- `email_enviado_em` fica preenchido depois que o e-mail é mandado pra
-- ESSE paciente especificamente -- cada paciente tem seu próprio
-- controle de envio (pode reenviar quantas vezes quiser, não some).
create table if not exists reserva_pacientes (
    id uuid primary key default uuid_generate_v4(),
    reserva_id uuid not null references reservas(id),
    paciente_id uuid not null references pacientes(id),
    email_enviado_em timestamptz,
    criado_em timestamptz not null default now(),
    unique (reserva_id, paciente_id)
);

create index if not exists idx_reserva_pacientes_reserva on reserva_pacientes(reserva_id);

alter table reserva_pacientes enable row level security;

-- Preenche o endereço padrão da Lifemax (colunas já existiam desde
-- migration_endereco_padrao_lifemax.sql, mas nenhuma tela usava ainda --
-- agora usado no e-mail de agendamento pro paciente) só se ainda
-- estiver vazio, pra não sobrescrever se o admin já tiver preenchido
-- outra coisa por conta própria entretanto. Editável em Admin > Horas.
update precos set
    endereco_padrao_rua = 'Gonçalves Dias',
    endereco_padrao_numero = '82',
    endereco_padrao_bairro = 'Funcionários',
    endereco_padrao_cidade = 'Belo Horizonte',
    endereco_padrao_estado = 'MG'
where coalesce(endereco_padrao_rua, '') = '';


-- ============================================================
-- migration_pacientes.sql
-- ============================================================

-- Cadastro completo de pacientes de cada médico -- pedido do Paulo em
-- 11/09/2026: botão "Cadastre o seu paciente" no painel do médico, com
-- ficha completa (dados pessoais, endereço e responsável), e vínculo do
-- paciente escolhido com um horário já reservado (botão "Incluir/alterar
-- paciente" na própria agenda do médico).
--
-- Diferente de `clientes_medico` (cadastro rápido de contato solto, sem
-- ficha completa) e de `agenda_pacientes`/`consultas_pacientes` (lembrete
-- automático de WhatsApp, não fazem parte deste pacote) -- esta tabela é
-- a ficha de cadastro de verdade do paciente, sempre presa a um médico
-- (cada médico só vê/edita os próprios pacientes).

create table if not exists pacientes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),

    -- Informações pessoais
    nome_completo text not null,
    nome_pai text,
    nome_mae text,
    data_nascimento date,
    cpf text,
    rg text,
    email text,
    sexo text,                 -- "Masculino" | "Feminino"
    estado_civil text,         -- "Solteiro" | "Casado" | "Divorciado" | "Viúvo" | "União estável"
    cor text,                  -- "Leucoderma" | "Faioderma" | "Melanoderma"
    convenio text,
    profissao text,
    indicacao text,

    -- Endereço
    endereco text,
    bairro text,
    cep text,
    cidade text,
    estado text,

    -- Informações do responsável
    responsavel_nome text,
    responsavel_tipo text,     -- "Mãe" | "Pai" | "Cônjuge" | "Filho" | "Filha" | "Avô" | "Avó" | "Tio" | "Tia" | "Parceiro" | "Outro"
    responsavel_telefone text,

    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create index if not exists idx_pacientes_medico on pacientes(medico_id);

alter table pacientes enable row level security;

-- Qual paciente (dos cadastrados pelo médico) está marcado pra ocupar um
-- horário já reservado -- aparece na tabela "Minha agenda" do painel do
-- médico. Fica nulo até o médico escolher (botão "Incluir/alterar
-- paciente"); trocar o valor é só clicar de novo e escolher outro.
alter table reservas add column if not exists paciente_id uuid references pacientes(id);


-- ============================================================
-- migration_pacotes_horas_avulsas.sql
-- ============================================================

-- Substitui o modelo antigo de preço escalonado (1ª/2ª/3ª hora + "turno de
-- 4h", em creditos_service.calcular_preco_horas) pelo modelo de pacotes
-- fechados pedido pelo Paulo em 10/09/2026: o médico AVULSO compra um
-- bloco fixo de horas (6/12/24/48) com desconto por volume, pagando de
-- verdade via PIX/cartão, em vez de comprar um valor livre em R$.
--
-- ⚠️ NOME DA TABELA: já existe uma tabela `pacotes_horas` (criada por
-- migration_horistas.sql) com um propósito BEM diferente -- é só a lista
-- de quantidades (6/12/24/48h, sem preço) que aparece no formulário da
-- secretária pra CREDITAR horas manualmente ao médico HORISTA (sem
-- cobrança, sem PIX). Por isso esta tabela nova tem outro nome
-- (`pacotes_horas_avulsas`) -- reaproveitar o nome antigo faria o
-- "create table if not exists" não fazer nada (a tabela já existe) e o
-- resto desta migração quebrar tentando inserir colunas que não existem
-- nela.
--
-- A tabela `precos` (preco_hora_1/2/3, preco_turno) continua existindo no
-- banco (não apagamos coluna nenhuma, pra não quebrar nada que já rodou),
-- mas o código PAROU de ler esses campos -- ver creditos_service.py. Só
-- `precos.horas_minimas` continua em uso (mínimo de horas por reserva).
--
-- O preço da HORA AVULSA (usado para debitar reservas feitas por hora, e
-- para o turno de 4h da Grade de Turnos) passa a ser o valor por hora do
-- MENOR pacote (hoje, o de 6h = R$ 65,00/h) -- ver
-- creditos_service.preco_hora_avulsa(). Assim só existe UM lugar (esta
-- tabela) definindo todos os preços de venda de horas avulsas.

create table if not exists pacotes_horas_avulsas (
    id uuid primary key default uuid_generate_v4(),
    horas integer not null unique,
    valor_hora numeric(10,2) not null,
    valor_total numeric(10,2) not null,
    max_parcelas integer not null default 1,
    ativo boolean not null default true,
    atualizado_em timestamptz not null default now()
);

insert into pacotes_horas_avulsas (horas, valor_hora, valor_total, max_parcelas) values
    (6,  65.00,  390.00, 1),
    (12, 58.00,  696.00, 1),
    (24, 49.00, 1176.00, 2),
    (48, 45.00, 2160.00, 3)
on conflict (horas) do update set
    valor_hora   = excluded.valor_hora,
    valor_total  = excluded.valor_total,
    max_parcelas = excluded.max_parcelas,
    atualizado_em = now();

-- Guarda, no próprio registro do pagamento, qual pacote foi comprado (se
-- foi um pacote fechado) e em quantas parcelas -- é o que permite creditar
-- a quantidade EXATA de horas quando o Asaas confirma o pagamento (ver
-- webhooks_asaas.confirmar_pagamento_e_creditar), em vez de estimar a
-- partir do valor pago.
alter table pagamentos_pix add column if not exists horas_pacote integer;
alter table pagamentos_pix add column if not exists parcelas integer not null default 1;

alter table pacotes_horas_avulsas enable row level security;


-- ============================================================
-- migration_pagamento_cartao.sql
-- ============================================================

-- Suporte a pagamento por cartão de crédito (além do PIX já existente).
-- Guarda a forma de pagamento e o link da fatura do Asaas (onde o
-- médico digita os dados do cartão, numa página segura do próprio
-- Asaas — o nosso sistema nunca vê o número do cartão).

alter table pagamentos_pix add column if not exists forma_pagamento text not null default 'pix'
    check (forma_pagamento in ('pix', 'cartao'));
alter table pagamentos_pix add column if not exists invoice_url text;


-- ============================================================
-- migration_precos_horas.sql
-- ============================================================

-- Migração: precificação escalonada por hora (1ª, 2ª, 3ª hora + turno = 4h)
-- e suporte a reservas avulsas por hora (além das reservas por turno).
-- Rode depois de migration_creditos.sql.

alter table precos add column if not exists preco_hora_1 numeric(10,2) not null default 0;
alter table precos add column if not exists preco_hora_2 numeric(10,2) not null default 0;
alter table precos add column if not exists preco_hora_3 numeric(10,2) not null default 0;
alter table precos add column if not exists horas_minimas integer not null default 1;

-- Se você já tinha um preco_hora único configurado antes, usa ele como
-- ponto de partida nas 3 faixas (ajuste depois em /admin/precos)
update precos
set preco_hora_1 = coalesce(preco_hora, 0),
    preco_hora_2 = coalesce(preco_hora, 0),
    preco_hora_3 = coalesce(preco_hora, 0)
where preco_hora_1 = 0 and preco_hora_2 = 0 and preco_hora_3 = 0;

-- Reservas por turno continuam como sempre. Reservas por hora avulsa
-- usam hora_inicio/hora_fim/quantidade_horas em vez de período fixo.
alter table reservas alter column periodo drop not null;
alter table reservas add column if not exists tipo_reserva text not null default 'turno'
    check (tipo_reserva in ('turno', 'hora'));
alter table reservas add column if not exists hora_inicio time;
alter table reservas add column if not exists hora_fim time;
alter table reservas add column if not exists quantidade_horas integer;


-- ============================================================
-- migration_prontuarios.sql
-- ============================================================

-- Armazenamento de PRONTUÁRIO ELETRÔNICO e EXAMES — dado sensível
-- (LGPD), por isso tudo aqui é privado por padrão: bucket sem acesso
-- público, link de acesso sempre temporário (gerado na hora, expira em
-- minutos), e toda visualização fica registrada em auditoria.

-- Bucket PRIVADO (public=false, diferente do bucket de fotos dos
-- consultórios, que é público de propósito)
--
-- ⚠️ Migração pra Neon (10/09/2026): este pacote (Reserva de Horas) não
-- usa o módulo de prontuário -- o bloco abaixo só roda se o schema
-- "storage" existir (Supabase). Se o módulo de prontuário for
-- implantado no futuro sobre o Neon, este bucket precisa ser recriado
-- no Neon Object Storage (privado) em vez de por SQL.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('prontuarios', 'prontuarios', false)
    on conflict (id) do nothing;

    -- Só o backend (service_role) acessa esse bucket — nem sequer os
    -- usuários autenticados via anon key conseguem ler direto; todo acesso
    -- passa pelo nosso sistema, que decide se libera ou não.
    drop policy if exists "Somente service role acessa prontuarios" on storage.objects;
    create policy "Somente service role acessa prontuarios"
    on storage.objects for all
    using (bucket_id = 'prontuarios' and auth.role() = 'service_role');
  end if;
end $$;

-- Anotações de prontuário eletrônico (texto) feitas pelo médico
create table if not exists prontuarios (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_telefone text,
    conteudo text not null,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);
create index if not exists idx_prontuarios_medico_paciente on prontuarios(medico_id, paciente_nome);

-- Arquivos de exame (fotos, PDFs de resultado, etc.) — o arquivo em si
-- fica no bucket privado 'prontuarios', aqui só ficam os metadados
create table if not exists exames_arquivos (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    nome_arquivo text not null,
    storage_path text not null,        -- caminho dentro do bucket privado
    tipo_arquivo text,                  -- ex: 'image/jpeg', 'application/pdf'
    tamanho_bytes bigint,
    criado_em timestamptz not null default now()
);
create index if not exists idx_exames_medico_paciente on exames_arquivos(medico_id, paciente_nome);

-- Auditoria: quem acessou o quê e quando — praticamente exigido pela
-- LGPD para dado sensível de saúde, e te protege numa eventual disputa
create table if not exists auditoria_acessos (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    tipo_recurso text not null check (tipo_recurso in ('prontuario', 'exame')),
    recurso_id uuid not null,
    acao text not null check (acao in ('visualizar', 'criar', 'editar', 'baixar')),
    ip text,
    criado_em timestamptz not null default now()
);
create index if not exists idx_auditoria_medico on auditoria_acessos(medico_id, criado_em desc);

alter table prontuarios enable row level security;
alter table exames_arquivos enable row level security;
alter table auditoria_acessos enable row level security;


-- ============================================================
-- migration_prontuario_melhorias.sql
-- ============================================================

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


-- ============================================================
-- migration_protecao_conflito.sql
-- ============================================================

-- Garante, a nível de BANCO DE DADOS, que nenhum consultório pode ter
-- dois horários sobrepostos reservados ao mesmo tempo — mesmo se dois
-- médicos clicarem em "reservar" no exato mesmo instante.
--
-- A reserva de TURNO já era protegida pela trava 'unique' em schema.sql.
-- Esta migração fecha a mesma proteção para reservas AVULSAS POR HORA,
-- que até agora só eram checadas em código Python (seguro na prática,
-- mas tecnicamente vulnerável a uma condição de corrida em alta
-- concorrência). Com isso, mesmo bilhões de cliques simultâneos não
-- conseguiriam gerar uma reserva duplicada — o banco rejeita de forma
-- atômica.

create extension if not exists btree_gist;

-- Coluna calculada automaticamente: o intervalo de tempo que a reserva
-- ocupa, seja ela por turno (horário fixo do período) ou por hora
-- (hora_inicio/hora_fim). Os horários de turno aqui precisam ser os
-- MESMOS usados em app/services/supabase_client.py (PERIODOS_HORARIOS)
-- — se um dia você mudar os horários dos turnos, ajuste os dois lugares.
alter table reservas add column if not exists intervalo_ocupado tsrange
    generated always as (
        case
            when tipo_reserva = 'turno' and periodo = 'manha' then tsrange(data + time '07:00', data + time '11:00')
            when tipo_reserva = 'turno' and periodo = 'tarde' then tsrange(data + time '13:00', data + time '17:00')
            when tipo_reserva = 'turno' and periodo = 'noite' then tsrange(data + time '18:00', data + time '22:00')
            when tipo_reserva = 'hora' and hora_inicio is not null and hora_fim is not null
                then tsrange(data + hora_inicio, data + hora_fim)
            else null
        end
    ) stored;

alter table reservas drop constraint if exists reservas_sem_sobreposicao;
alter table reservas add constraint reservas_sem_sobreposicao
    exclude using gist (consultorio_id with =, intervalo_ocupado with &&)
    where (status <> 'cancelada');


-- ============================================================
-- migration_horarios_turno_v2.sql
-- ============================================================

-- Atualiza os horários padrão dos turnos:
--   manhã: 08:00–12:00 (era 07:00–11:00)
--   tarde: 13:00–17:00 (sem mudança)
--   noite: 17:00–20:00 (era 18:00–22:00 — agora só 3 horas, não 4)
--
-- Precisa recriar a coluna gerada + a trava de sobreposição de
-- sql/migration_protecao_conflito.sql, porque colunas geradas não
-- podem ser alteradas diretamente no Postgres — só recriadas.
-- Rode isso DEPOIS de migration_protecao_conflito.sql.
--
-- Usa tsrange (sem fuso horário) em vez de tstzrange — a conta
-- "data + hora" já gera um horário sem fuso, e o Postgres exige que
-- colunas geradas usem só contas "imutáveis" (que não dependem de
-- configuração do servidor, como fuso horário).

create extension if not exists btree_gist;

alter table reservas drop constraint if exists reservas_sem_sobreposicao;
alter table reservas drop column if exists intervalo_ocupado;

alter table reservas add column intervalo_ocupado tsrange
    generated always as (
        case
            when tipo_reserva = 'turno' and periodo = 'manha' then tsrange(data + time '08:00', data + time '12:00')
            when tipo_reserva = 'turno' and periodo = 'tarde' then tsrange(data + time '13:00', data + time '17:00')
            when tipo_reserva = 'turno' and periodo = 'noite' then tsrange(data + time '17:00', data + time '20:00')
            when tipo_reserva = 'hora' and hora_inicio is not null and hora_fim is not null
                then tsrange(data + hora_inicio, data + hora_fim)
            else null
        end
    ) stored;

alter table reservas add constraint reservas_sem_sobreposicao
    exclude using gist (consultorio_id with =, intervalo_ocupado with &&)
    where (status <> 'cancelada');


-- ============================================================
-- migration_rede_lifemax.sql
-- ============================================================

-- Rede Lifemax: perfil público do médico (site novo, outro domínio,
-- mesmo banco) + avaliações de pacientes com confirmação por e-mail.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

-- 1) Campos novos no cadastro do médico -- tudo opcional/desligado por
--    padrão: o médico só aparece na Rede Lifemax depois de ele mesmo
--    ativar (visivel_rede_lifemax), na aba nova do painel dele.
alter table medicos add column if not exists foto_perfil_url text;
alter table medicos add column if not exists bio_publica text;
alter table medicos add column if not exists especialidades_publicas text[] not null default '{}';
alter table medicos add column if not exists visivel_rede_lifemax boolean not null default false;
-- latitude/longitude calculados automaticamente a partir do endereço
-- (endereco_cep/rua/numero/bairro/cidade/estado, que já existem desde
-- migration_endereco_medico.sql) -- usados só para posicionar o pino
-- no mapa da Rede Lifemax.
alter table medicos add column if not exists latitude numeric(9,6);
alter table medicos add column if not exists longitude numeric(9,6);

comment on column medicos.foto_perfil_url is 'Foto de perfil pública (Rede Lifemax) -- bucket perfis-medicos';
comment on column medicos.bio_publica is 'Texto "Sobre" exibido no perfil público da Rede Lifemax';
comment on column medicos.especialidades_publicas is 'Áreas de atuação/tags extras exibidas no perfil público, além da especialidade principal';
comment on column medicos.visivel_rede_lifemax is 'Se true, o médico aparece na busca e tem perfil público na Rede Lifemax';
comment on column medicos.latitude is 'Latitude calculada a partir do endereço, para o mapa da Rede Lifemax';
comment on column medicos.longitude is 'Longitude calculada a partir do endereço, para o mapa da Rede Lifemax';

-- 2) Avaliações de pacientes sobre o médico (estrelas de 1 a 5).
--    Só fica pública (confirmado = true) depois que o paciente clica no
--    link de confirmação mandado por e-mail -- evita avaliação fake
--    feita em nome de outra pessoa. O hash do token segue o mesmo
--    padrão de segurança de tokens_recuperacao_senha (nunca guardamos
--    o token em texto puro).
create table if not exists avaliacoes_medico (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_email text not null,
    nota integer not null check (nota between 1 and 5),
    comentario text,
    confirmado boolean not null default false,
    visivel boolean not null default true,   -- admin pode ocultar uma avaliação problemática sem apagar o histórico
    token_hash text,
    token_expira_em timestamptz,
    criado_em timestamptz not null default now(),
    confirmado_em timestamptz
);

create index if not exists idx_avaliacoes_medico_id on avaliacoes_medico(medico_id);
create index if not exists idx_avaliacoes_confirmado on avaliacoes_medico(medico_id, confirmado, visivel);

-- Evita duas avaliações CONFIRMADAS do mesmo paciente (mesmo e-mail)
-- pro mesmo médico -- o serviço também confere isso antes de criar,
-- mas o índice único garante isso mesmo em caso de corrida.
create unique index if not exists idx_avaliacoes_unica_confirmada
    on avaliacoes_medico(medico_id, paciente_email)
    where confirmado;

alter table avaliacoes_medico enable row level security;

-- 3) Bucket de storage para as fotos de perfil dos médicos (Rede Lifemax).
--
-- ⚠️ Migração pra Neon (10/09/2026): este pacote (Reserva de Horas) não
-- usa o módulo Rede Lifemax -- o bloco abaixo só roda se o schema
-- "storage" existir (Supabase). Se a Rede Lifemax for implantada no
-- futuro sobre o Neon, este bucket precisa ser recriado no Neon Object
-- Storage (público) em vez de por SQL.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('perfis-medicos', 'perfis-medicos', true)
    on conflict (id) do nothing;

    drop policy if exists "Fotos de perfil sao publicas" on storage.objects;
    create policy "Fotos de perfil sao publicas"
    on storage.objects for select
    using (bucket_id = 'perfis-medicos');

    drop policy if exists "Somente service role gerencia fotos de perfil" on storage.objects;
    create policy "Somente service role gerencia fotos de perfil"
    on storage.objects for all
    using (bucket_id = 'perfis-medicos' and auth.role() = 'service_role');
  end if;
end $$;


-- ============================================================
-- migration_rede_lifemax_visivel_por_padrao.sql
-- ============================================================

-- Mudança de comportamento pedida pelo Paulo: o médico precisa aparecer
-- na busca da Rede Lifemax (nome + especialidade) MESMO sem nunca ter
-- ativado a própria conta -- o cadastro básico já existe no banco (veio
-- da planilha dos 74 médicos), então não faz sentido esconder isso
-- atrás de um "aparecer" que só quem já entrou no sistema consegue
-- ligar. Depois que o médico ativa a conta, ele só COMPLETA o perfil
-- (foto, "sobre", endereço) -- não é isso que decide se ele aparece.
--
-- Antes: `visivel_rede_lifemax` (default false) = tinha que ligar pra aparecer.
-- Agora: `rede_lifemax_oculto` (default false) = aparece sempre, a
-- menos que o PRÓPRIO médico peça pra se esconder depois de ativar a
-- conta (opt-out, não opt-in).

alter table medicos add column if not exists rede_lifemax_oculto boolean not null default false;

comment on column medicos.rede_lifemax_oculto is
    'Se true, o médico pediu pra NÃO aparecer na Rede Lifemax -- por padrão todo médico ativo aparece (nome + especialidade), mesmo sem ter ativado a conta ainda';

-- a coluna antiga (visivel_rede_lifemax) fica no banco sem uso a partir
-- de agora -- não precisa apagar, só não é mais consultada pelo sistema.


-- ============================================================
-- migration_saldo_ia_separado.sql
-- ============================================================

-- Pedido do Paulo (08/09/2026): separar em DUAS carteiras o que antes
-- era um saldo único (decisão de 03/09/2026, revertida agora por
-- pedido explícito):
--   - saldo_creditos (já existia) = "Saldo para reserva de salas"
--   - saldo_ia (novo)             = "Saldo para IA"
-- Cada uma só é debitada pelo que é dela (sala nunca consome saldo de
-- IA, e vice-versa) e cada uma tem seu próprio alerta de saldo baixo.

alter table medicos add column if not exists saldo_ia numeric(10,2) not null default 0;
alter table medicos add column if not exists alerta_saldo_ia_baixo_enviado boolean not null default false;
comment on column medicos.saldo_ia is 'Saldo em R$ exclusivo pra uso de IA (secretária virtual, análise de prontuário, voz, contábil) -- separado do saldo_creditos (reserva de salas)';

alter table creditos_transacoes add column if not exists carteira text not null default 'salas'
    check (carteira in ('salas', 'ia'));
comment on column creditos_transacoes.carteira is 'Qual saldo essa transação mexeu: salas (saldo_creditos) ou ia (saldo_ia)';
update creditos_transacoes set carteira = 'ia' where categoria = 'ia' and carteira = 'salas';

-- ---------------------------------------------------------------------
-- Toggle EXPLÍCITO de cada módulo de IA, controlado pelo médico em
-- "Painel de IA" -- diferente de medico_modulos_ia (que só registra
-- quando o médico usou pela primeira vez, pra contar o trial de 30
-- dias). Sem marcar aqui, o médico só pode usar o crédito de teste
-- grátis (R$ 10, uma vez), nunca gastar saldo de verdade.
-- ---------------------------------------------------------------------
create table if not exists ia_modulos_ativados (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    modulo_slug text not null check (modulo_slug in ('secretaria', 'prontuario', 'prontuario_voz', 'financeiro')),
    ativado boolean not null default false,
    ativado_em timestamptz,
    atualizado_em timestamptz not null default now(),
    unique (medico_id, modulo_slug)
);
alter table ia_modulos_ativados enable row level security;

-- ---------------------------------------------------------------------
-- O médico pode comprar crédito de sala e/ou de IA no mesmo pagamento
-- -- guarda quanto de cada, pra saber como dividir quando o Asaas
-- confirmar que foi pago (ver webhooks_asaas.py).
-- ---------------------------------------------------------------------
alter table pagamentos_pix add column if not exists valor_salas numeric(10,2) not null default 0;
alter table pagamentos_pix add column if not exists valor_ia numeric(10,2) not null default 0;
comment on column pagamentos_pix.valor_salas is 'Parte do pagamento destinada ao saldo de reserva de salas';
comment on column pagamentos_pix.valor_ia is 'Parte do pagamento destinada ao saldo de IA';

-- Pagamentos já existentes: tudo que já foi pago até hoje era 100% pra
-- salas (a opção de comprar IA separadamente não existia ainda).
update pagamentos_pix set valor_salas = valor, valor_ia = 0 where valor_salas = 0 and valor_ia = 0 and valor > 0;

-- ---------------------------------------------------------------------
-- 4º módulo de IA: "Análise de voz para preenchimento automático de
-- prontuário" -- a restrição antiga só aceitava 3 valores.
-- ---------------------------------------------------------------------
alter table medico_modulos_ia drop constraint if exists medico_modulos_ia_modulo_slug_check;
alter table medico_modulos_ia add constraint medico_modulos_ia_modulo_slug_check
    check (modulo_slug in ('secretaria', 'prontuario', 'prontuario_voz', 'financeiro'));


-- ============================================================
-- migration_secretarias.sql
-- ============================================================

-- Login individual de secretária, com acesso restrito à tela "Agenda
-- Fixos" (agenda de médicos fixos/horistas, crédito de horas de
-- horista, matriz de liberação e relatórios) -- NÃO tem acesso ao
-- resto do painel admin (preços, cadastro de médico, backup,
-- módulos, notas fiscais, fotos de consultório).
--
-- É separado da tabela `funcionarios` (que só guarda e-mails pra
-- notificação de turno reservado, sem login nenhum).
--
-- O cadastro é feito pelo admin (nome + telefone) em /admin -- depois
-- disso a própria secretária define a senha em /secretaria/criar-senha,
-- igual ao "primeiro acesso" dos médicos. Não existe auto-cadastro
-- aberto pra secretária (diferente do médico), porque essa conta já
-- nasce com acesso a agendamentos e crédito de horas.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

create table if not exists secretarias (
    id uuid primary key default uuid_generate_v4(),
    nome text not null,
    telefone text unique not null,
    senha_hash text,
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

alter table secretarias enable row level security;


-- ============================================================
-- migration_recuperacao_senha.sql
-- ============================================================

-- "Esqueci minha senha" por e-mail, para médico e secretária (o admin
-- continua de fora -- a senha dele é a variável ADMIN_PASSWORD no Render,
-- trocada direto lá, sem fluxo de recuperação próprio).
--
-- Guardamos só o HASH do token (sha256, não o werkzeug/bcrypt lento de
-- senha) -- um token de recuperação é um valor de alta entropia gerado
-- por nós (secrets.token_urlsafe), então não precisa de um hash lento
-- pra resistir a força bruta; e precisa dar pra buscar por igualdade
-- exata direto no banco, o que um hash bcrypt-like não permite (o
-- salt é diferente a cada chamada).
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

alter table secretarias add column if not exists email text;

create table if not exists tokens_recuperacao_senha (
    id uuid primary key default uuid_generate_v4(),
    tipo text not null check (tipo in ('medico', 'secretaria')),
    usuario_id uuid not null,
    token_hash text not null unique,
    expira_em timestamptz not null,
    usado boolean not null default false,
    criado_em timestamptz not null default now()
);

create index if not exists idx_tokens_recuperacao_hash on tokens_recuperacao_senha (token_hash);
create index if not exists idx_tokens_recuperacao_usuario on tokens_recuperacao_senha (tipo, usuario_id);

alter table tokens_recuperacao_senha enable row level security;


-- ============================================================
-- migration_primeiro_acesso_admin.sql
-- ============================================================

-- Link de "primeiro acesso" enviado pelo admin direto pra um médico já
-- cadastrado (Agenda dos Médicos Fixos -> selecionar médico -> "Enviar
-- link de acesso") -- usa a MESMA tabela/mecanismo do "esqueci minha
-- senha" (token só em hash, validade, uso único), só que amarrado ao
-- medico_id certo desde o início, sem precisar que o médico digite o
-- próprio telefone -- isso é o que evita o risco de duplicar cadastro
-- se ele digitar um telefone diferente do que já está no sistema.

alter table tokens_recuperacao_senha add column if not exists contexto text not null default 'recuperacao'
    check (contexto in ('recuperacao', 'primeiro_acesso'));

comment on column tokens_recuperacao_senha.contexto is
    '"recuperacao" = o próprio usuário pediu (esqueci minha senha); "primeiro_acesso" = admin gerou e mandou pra um médico já cadastrado criar a senha dele pela primeira vez';


-- ============================================================
-- migration_semana_padrao.sql
-- ============================================================

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


-- ============================================================
-- migration_storage_fotos.sql
-- ============================================================

-- Bucket de storage para as fotos dos consultórios.
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso (depois do schema.sql).
--
-- ⚠️ Migração pra Neon (10/09/2026): o bucket 'consultorios' (fotos dos
-- consultórios) foi migrado pro Neon Object Storage -- ele NÃO é
-- configurado por SQL, mas direto no Neon Console (ou `neon buckets
-- create`). Veja app/services/neon_storage.py e INSTALAR.md. O bloco
-- abaixo só roda se o schema "storage" existir (ou seja: só se esse SQL
-- for aplicado contra um projeto Supabase -- no Neon ele é ignorado sem
-- dar erro, de propósito).
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('consultorios', 'consultorios', true)
    on conflict (id) do nothing;

    -- Permite leitura pública das fotos (necessário para elas aparecerem
    -- no WhatsApp e na página pública sem precisar de autenticação)
    -- Postgres não aceita "create policy if not exists" -- por isso apaga
    -- antes de recriar, o que também deixa essa migração segura de rodar
    -- de novo sem dar erro.
    drop policy if exists "Fotos de consultorios sao publicas" on storage.objects;
    create policy "Fotos de consultorios sao publicas"
    on storage.objects for select
    using (bucket_id = 'consultorios');

    -- Só o backend (service_role key) pode enviar/apagar fotos —
    -- o upload é feito pelo admin do sistema, não diretamente pelo navegador
    drop policy if exists "Somente service role gerencia fotos" on storage.objects;
    create policy "Somente service role gerencia fotos"
    on storage.objects for all
    using (bucket_id = 'consultorios' and auth.role() = 'service_role');
  end if;
end $$;


-- ============================================================
-- migration_tax_profile_nfse.sql
-- ============================================================

-- Módulo de configuração tributária para NFS-e (especificação enviada
-- pelo Paulo em 08/09/2026). Três peças, como o documento pede:
--
--   tax_rules            -> regras gerais, cadastradas pelo admin/contador
--                            (município + serviço + regime -> alíquota),
--                            NUNCA fixas no código, sempre com vigência
--   tax_profiles         -> a configuração tributária DE CADA MÉDICO
--                            (pode ter sido preenchida com base numa
--                            tax_rule, mas é o registro final dele)
--   invoice_tax_snapshot -> a "foto" da tributação usada em cada nota
--                            emitida -- se uma regra mudar depois, as
--                            notas antigas continuam com o cálculo que
--                            valia na hora que foram emitidas

-- ---------------------------------------------------------------------
-- 1) tax_rules -- regras gerais (seção 10 do documento)
-- ---------------------------------------------------------------------
create table if not exists tax_rules (
    id uuid primary key default uuid_generate_v4(),
    uf text,
    municipio text,
    codigo_servico text,
    codigo_nbs text,
    tipo_emitente text check (tipo_emitente in ('pf_autonomo', 'pj')),
    regime_tributario text check (regime_tributario in ('simples', 'lucro_presumido', 'lucro_real')),
    anexo text check (anexo in ('iii', 'v')),
    tributo text not null check (tributo in (
        'ISS', 'IRPF', 'IRPJ', 'CSLL', 'PIS', 'COFINS', 'INSS', 'IRRF',
        'PIS_RETIDO', 'COFINS_RETIDO', 'CSLL_RETIDO', 'INSS_RETIDO', 'IBS', 'CBS'
    )),
    tipo_calculo text not null check (tipo_calculo in (
        'PERCENTUAL', 'VALOR_FIXO', 'TABELA', 'REGRA', 'INCLUIDO_NO_DAS', 'NAO_APLICAVEL'
    )),
    aliquota numeric(8,4),
    percentual_reducao numeric(6,3),
    retencao_permitida boolean not null default false,
    retencao_obrigatoria boolean not null default false,
    base_calculo_regra text,
    inicio_vigencia date not null default current_date,
    fim_vigencia date,
    fonte_regra text,
    observacao text,
    ativo boolean not null default true,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);
create index if not exists idx_tax_rules_busca on tax_rules(municipio, tipo_emitente, regime_tributario, tributo, ativo);
alter table tax_rules enable row level security;

-- ---------------------------------------------------------------------
-- 2) tax_profiles -- configuração tributária de cada médico (seção 9)
-- ---------------------------------------------------------------------
create table if not exists tax_profiles (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),

    tipo_emitente text not null check (tipo_emitente in ('pf_autonomo', 'pj')),
    tipo_estabelecimento text,  -- ex: 'clinica' -- é o tipo de estabelecimento, não regime (nota do documento)

    -- Pessoa Jurídica
    regime_tributario text check (regime_tributario in ('simples', 'lucro_presumido', 'lucro_real')),
    pj_razao_social text,
    pj_cnpj text,

    -- Simples Nacional
    anexo_simples text check (anexo_simples in ('iii', 'v')),
    usa_fator_r boolean not null default false,
    fator_r numeric(6,3),
    aliquota_simples numeric(6,3),
    iss_dentro_das boolean not null default false,

    -- Lucro Presumido / Lucro Real
    presuncao_irpj numeric(6,3),
    presuncao_csll numeric(6,3),
    irpj_aliquota numeric(6,3),
    csll_aliquota numeric(6,3),
    pis_aliquota numeric(6,3),
    cofins_aliquota numeric(6,3),

    -- Pessoa Física Autônoma
    irpf_regra text,
    inss_regra text,
    inss_retido boolean not null default false,

    -- ISS (comum a todos)
    municipio_iss text,
    codigo_servico text,
    codigo_nbs text,
    iss_aliquota numeric(6,3),
    iss_retido boolean not null default false,

    -- Retenções gerais pelo tomador
    irrf_retido boolean not null default false,
    pis_retido boolean not null default false,
    cofins_retido boolean not null default false,
    csll_retido boolean not null default false,

    -- IBS/CBS (reforma tributária -- seção 12, nunca alíquota universal fixa)
    ibs_regra text,
    ibs_aliquota numeric(6,3),
    cbs_regra text,
    cbs_aliquota numeric(6,3),
    ibs_cbs_destacar boolean not null default false,

    -- Vigência e rastreabilidade (seção 11)
    data_inicio_vigencia date not null default current_date,
    data_fim_vigencia date,
    fonte_regra text,
    observacao_contador text,
    tax_rule_ids uuid[] not null default '{}',  -- quais tax_rules foram usadas pra sugerir esses valores

    ativo boolean not null default true,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);
create index if not exists idx_tax_profiles_medico on tax_profiles(medico_id, ativo);
alter table tax_profiles enable row level security;

-- ---------------------------------------------------------------------
-- 3) invoice_tax_snapshot -- a tributação USADA em cada nota (seção 15)
-- ---------------------------------------------------------------------
create table if not exists invoice_tax_snapshot (
    id uuid primary key default uuid_generate_v4(),
    receita_id uuid not null references receitas_medicas(id),
    tax_profile_id uuid not null references tax_profiles(id),
    tax_rule_ids uuid[] not null default '{}',

    valor_bruto numeric(12,2) not null,

    iss_base numeric(12,2),
    iss_rate numeric(6,3),
    iss_value numeric(12,2),

    irpf_value numeric(12,2),
    irpj_value numeric(12,2),
    csll_value numeric(12,2),
    pis_value numeric(12,2),
    cofins_value numeric(12,2),
    inss_value numeric(12,2),

    irrf_withheld numeric(12,2),
    iss_withheld numeric(12,2),
    pis_withheld numeric(12,2),
    cofins_withheld numeric(12,2),
    csll_withheld numeric(12,2),
    inss_withheld numeric(12,2),

    ibs_base numeric(12,2),
    ibs_rate numeric(6,3),
    ibs_value numeric(12,2),
    cbs_base numeric(12,2),
    cbs_rate numeric(6,3),
    cbs_value numeric(12,2),

    valor_liquido numeric(12,2) not null,
    calculated_at timestamptz not null default now()
);
create index if not exists idx_invoice_tax_snapshot_receita on invoice_tax_snapshot(receita_id);
alter table invoice_tax_snapshot enable row level security;

-- ---------------------------------------------------------------------
-- 4) Auditoria de alteração da configuração tributária (seção 16)
-- ---------------------------------------------------------------------
create table if not exists tax_profile_audit (
    id uuid primary key default uuid_generate_v4(),
    tax_profile_id uuid not null,
    medico_id uuid not null references medicos(id),
    usuario_tipo text not null check (usuario_tipo in ('medico', 'admin', 'secretaria')),
    usuario_id text,
    campo_alterado text not null,
    valor_anterior text,
    valor_novo text,
    data_hora timestamptz not null default now()
);
create index if not exists idx_tax_profile_audit_medico on tax_profile_audit(medico_id, data_hora desc);
alter table tax_profile_audit enable row level security;

-- ---------------------------------------------------------------------
-- 5) Certificado digital do médico (A1) -- pra assinar a NFS-e
--    automaticamente quando o provedor de emissão for conectado.
--    Guardado CRIPTOGRAFADO (mesmo ENCRYPTION_KEY do prontuário) --
--    nunca em texto puro, nem o arquivo nem a senha.
-- ---------------------------------------------------------------------
alter table medicos add column if not exists certificado_a1_arquivo_criptografado text;
alter table medicos add column if not exists certificado_a1_senha_criptografada text;
alter table medicos add column if not exists certificado_a1_nome_arquivo text;
alter table medicos add column if not exists certificado_a1_validade date;
alter table medicos add column if not exists certificado_a1_enviado_em timestamptz;

comment on column medicos.certificado_a1_arquivo_criptografado is
    'Certificado digital A1 (.pfx/.p12) do médico, em base64 e criptografado -- usado para assinar a NFS-e quando o provedor de emissão estiver conectado';
comment on column medicos.certificado_a1_senha_criptografada is
    'Senha do certificado A1, criptografada -- nunca fica em texto puro no banco';

-- ---------------------------------------------------------------------
-- 6) Vínculo do e-mail da nota fiscal e "por período" -- pra mandar em
--    lote pro contador. Reaproveita receitas_medicas (já existe).
-- ---------------------------------------------------------------------
alter table receitas_medicas add column if not exists nota_fiscal_status text not null default 'nao_emitida'
    check (nota_fiscal_status in ('nao_emitida', 'emitida', 'enviada_paciente', 'enviada_contador', 'cancelada'));
alter table receitas_medicas add column if not exists nota_fiscal_numero text;
alter table receitas_medicas add column if not exists nota_fiscal_url text;
alter table receitas_medicas add column if not exists nota_fiscal_emitida_em timestamptz;
alter table receitas_medicas add column if not exists nota_fiscal_enviada_paciente_em timestamptz;
alter table receitas_medicas add column if not exists nota_fiscal_enviada_contador_em timestamptz;
alter table receitas_medicas add column if not exists paciente_email text;


-- ============================================================
-- migration_telao_por_andar.sql
-- ============================================================

-- Telão de chamada de pacientes por ANDAR (antes só existia um telão
-- único pra recepção inteira). O andar de cada consultório já existe
-- (coluna `consultorios.andar`, de migration_agenda_medicos_fixos.sql)
-- -- essa migração só guarda esse andar também no histórico de
-- chamados, pra dar pra filtrar o telão de cada andar sem precisar de
-- join toda hora.

alter table chamados_recepcao add column if not exists andar text;

comment on column chamados_recepcao.andar is
    'Andar do consultório no momento da chamada (copiado de consultorios.andar) -- usado pra cada telão mostrar só as chamadas do próprio andar';

create index if not exists idx_chamados_recepcao_andar on chamados_recepcao(andar, chamado_em desc);


-- ============================================================
-- migration_termo_uso.sql
-- ============================================================

-- Guarda se e quando o médico aceitou o Termo de Uso — necessário para
-- ter prova do aceite (data/hora + IP) em caso de disputa jurídica.

alter table medicos add column if not exists termo_aceito boolean not null default false;
alter table medicos add column if not exists termo_aceito_em timestamptz;
alter table medicos add column if not exists termo_aceito_ip text;


-- ============================================================
-- migration_termo_versao.sql
-- ============================================================

-- Guarda qual VERSÃO do Contrato Digital (app/services/contrato_service.py,
-- CONTRATO_VERSAO) cada médico aceitou -- pedido do Paulo em 10/09/2026,
-- junto com o botão de baixar o contrato em PDF a qualquer momento
-- (rota /contrato/baixar). Sem isso, se o texto do contrato mudar no
-- futuro, não teria como saber com certeza qual versão um médico
-- específico realmente aceitou no passado.

alter table medicos add column if not exists termo_versao text;


-- ============================================================
-- migration_tryout_medico.sql
-- ============================================================

-- Pedido do Paulo em 21/09/2026: "tryout" pro médico avulso conhecer o
-- sistema -- as 3 primeiras reservas de consultório (por hora) não
-- debitam saldo, em qualquer canal (site ou assistente de WhatsApp
-- Dora). Da 4ª reserva em diante, precisa ter crédito normalmente.
-- `tryout=true` marca quais reservas usaram essa cortesia -- o "quanto
-- ainda falta" é sempre CALCULADO contando reservas tryout NÃO
-- canceladas desse médico (ver creditos_service.tryout_restante), não
-- guardado num contador separado, pra cancelar uma reserva de teste
-- devolver a cortesia automaticamente (mesma lógica de sempre).
alter table reservas add column if not exists tryout boolean not null default false;


-- ============================================================
-- migration_video.sql
-- ============================================================

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


-- ============================================================
-- migration_matriz_admin_reservas.sql
-- ============================================================

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

