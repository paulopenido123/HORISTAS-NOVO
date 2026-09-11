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
