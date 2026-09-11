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
