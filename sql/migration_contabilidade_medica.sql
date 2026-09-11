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
