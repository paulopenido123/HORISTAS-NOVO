-- Primeiro acesso só com e-mail e senha (22/10/2026): o telefone deixa de ser obrigatório no
-- cadastro inicial (continua obrigatório para reservar -- preenchido em "Meus dados").
-- A restrição UNIQUE continua valendo (vários cadastros sem telefone = NULL são permitidos).
alter table medicos alter column telefone drop not null;
