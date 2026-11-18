-- v99: registro de todo e-mail que o sistema tenta enviar (alimenta o botão
-- "Histórico contato" em Admin > Clientes). Rodar no Neon (SQL Editor).
create table if not exists emails_enviados (
    id uuid primary key default uuid_generate_v4(),
    destinatarios text not null,            -- endereços separados por vírgula, em minúsculas
    assunto text,
    status text not null check (status in ('enviado', 'falhou', 'nao_configurado')),
    erro text,
    criado_em timestamptz not null default now()
);
create index if not exists idx_emails_enviados_criado on emails_enviados (criado_em desc);
alter table emails_enviados enable row level security;
