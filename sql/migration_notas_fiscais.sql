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
