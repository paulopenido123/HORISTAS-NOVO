-- Preço por token e margem da IA paga (OpenAI), editáveis direto no
-- Dashboard Admin (painel "IA — Consumo de tokens e faturamento") em
-- vez de só por variável de ambiente. Guardado na mesma tabela
-- `precos` de sempre (linha única, junto com preço de hora/turno).
--
-- Os valores padrão abaixo são os mesmos que já estavam valendo hoje
-- (env var / tabela PRECOS_USD_POR_1K do gpt-5.6-luna em
-- ia_uso_service.py) -- rodar essa migração não muda nenhuma cobrança
-- que já estava acontecendo, só passa a deixar isso editável.

alter table precos add column if not exists ia_percentual_aumento numeric not null default 400;
alter table precos add column if not exists ia_preco_entrada_usd_1k numeric not null default 0.00020;
alter table precos add column if not exists ia_preco_saida_usd_1k numeric not null default 0.00120;
alter table precos add column if not exists ia_usd_para_brl numeric not null default 5.16;

comment on column precos.ia_percentual_aumento is 'Percentual de aumento (ganho da empresa) sobre o custo real da IA -- 400 = cobra 5x o custo (1 + 400/100)';
comment on column precos.ia_preco_entrada_usd_1k is 'Preço em USD por 1.000 tokens de ENTRADA (prompt) do modelo de IA pago -- confira em platform.openai.com/docs/pricing';
comment on column precos.ia_preco_saida_usd_1k is 'Preço em USD por 1.000 tokens de SAÍDA (resposta) do modelo de IA pago';
comment on column precos.ia_usd_para_brl is 'Cotação do dólar usada pra converter o custo da IA (sempre em USD) pra reais';
