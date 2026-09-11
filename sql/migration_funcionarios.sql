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
