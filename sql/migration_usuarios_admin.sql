-- Usuários do painel admin (22/10/2026): login por e-mail ou telefone + senha.
create table if not exists usuarios_admin (
    id uuid primary key default uuid_generate_v4(),
    nome text not null,
    email text not null,
    telefone text,
    senha_hash text,
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);
create unique index if not exists uq_usuarios_admin_email on usuarios_admin (lower(email));

create table if not exists tokens_admin_usuarios (
    id uuid primary key default uuid_generate_v4(),
    usuario_id uuid not null references usuarios_admin(id) on delete cascade,
    token_hash text not null unique,
    expira_em timestamptz not null,
    usado boolean not null default false,
    criado_em timestamptz not null default now()
);
alter table usuarios_admin enable row level security;
alter table tokens_admin_usuarios enable row level security;
