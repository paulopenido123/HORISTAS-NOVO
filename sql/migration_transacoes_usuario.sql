-- Quem (usuário do admin) fez cada alteração manual de saldo de horas.
-- Usado em Admin > Relatórios > Transações (coluna "Usuário").
-- Seguro rodar mais de uma vez. Sem isso o sistema continua funcionando,
-- mas as novas alterações de saldo não registram o nome de quem as fez.
alter table creditos_transacoes add column if not exists criado_por text;
