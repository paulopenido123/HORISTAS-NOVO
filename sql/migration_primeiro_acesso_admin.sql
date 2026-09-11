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
