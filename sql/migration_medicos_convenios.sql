-- Lista de convênios aceitos por cada médico -- cadastrada pela
-- secretária/admin no cadastro/edição do médico (uma lista fixa, não
-- calculada a partir do histórico de consultas). Usada pelo botão
-- "Convênios" na tela Agenda Fixos, que só mostra essa lista.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

alter table medicos add column if not exists convenios text[] not null default '{}';
