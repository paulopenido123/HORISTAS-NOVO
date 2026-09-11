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
