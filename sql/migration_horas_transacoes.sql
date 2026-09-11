-- Guarda a quantidade de horas de cada reserva diretamente na
-- transação de crédito, para os relatórios do dashboard poderem
-- somar horas consumidas com precisão (em vez de estimar a partir do
-- valor em R$, que é impreciso com preço escalonado).

alter table creditos_transacoes add column if not exists quantidade_horas integer;
