-- Substitui o modelo antigo de preço escalonado (1ª/2ª/3ª hora + "turno de
-- 4h", em creditos_service.calcular_preco_horas) pelo modelo de pacotes
-- fechados pedido pelo Paulo em 10/09/2026: o médico AVULSO compra um
-- bloco fixo de horas (6/12/24/48) com desconto por volume, pagando de
-- verdade via PIX/cartão, em vez de comprar um valor livre em R$.
--
-- ⚠️ NOME DA TABELA: já existe uma tabela `pacotes_horas` (criada por
-- migration_horistas.sql) com um propósito BEM diferente -- é só a lista
-- de quantidades (6/12/24/48h, sem preço) que aparece no formulário da
-- secretária pra CREDITAR horas manualmente ao médico HORISTA (sem
-- cobrança, sem PIX). Por isso esta tabela nova tem outro nome
-- (`pacotes_horas_avulsas`) -- reaproveitar o nome antigo faria o
-- "create table if not exists" não fazer nada (a tabela já existe) e o
-- resto desta migração quebrar tentando inserir colunas que não existem
-- nela.
--
-- A tabela `precos` (preco_hora_1/2/3, preco_turno) continua existindo no
-- banco (não apagamos coluna nenhuma, pra não quebrar nada que já rodou),
-- mas o código PAROU de ler esses campos -- ver creditos_service.py. Só
-- `precos.horas_minimas` continua em uso (mínimo de horas por reserva).
--
-- O preço da HORA AVULSA (usado para debitar reservas feitas por hora, e
-- para o turno de 4h da Grade de Turnos) passa a ser o valor por hora do
-- MENOR pacote (hoje, o de 6h = R$ 65,00/h) -- ver
-- creditos_service.preco_hora_avulsa(). Assim só existe UM lugar (esta
-- tabela) definindo todos os preços de venda de horas avulsas.

create table if not exists pacotes_horas_avulsas (
    id uuid primary key default uuid_generate_v4(),
    horas integer not null unique,
    valor_hora numeric(10,2) not null,
    valor_total numeric(10,2) not null,
    max_parcelas integer not null default 1,
    ativo boolean not null default true,
    atualizado_em timestamptz not null default now()
);

insert into pacotes_horas_avulsas (horas, valor_hora, valor_total, max_parcelas) values
    (6,  65.00,  390.00, 1),
    (12, 58.00,  696.00, 1),
    (24, 49.00, 1176.00, 2),
    (48, 45.00, 2160.00, 3)
on conflict (horas) do update set
    valor_hora   = excluded.valor_hora,
    valor_total  = excluded.valor_total,
    max_parcelas = excluded.max_parcelas,
    atualizado_em = now();

-- Guarda, no próprio registro do pagamento, qual pacote foi comprado (se
-- foi um pacote fechado) e em quantas parcelas -- é o que permite creditar
-- a quantidade EXATA de horas quando o Asaas confirma o pagamento (ver
-- webhooks_asaas.confirmar_pagamento_e_creditar), em vez de estimar a
-- partir do valor pago.
alter table pagamentos_pix add column if not exists horas_pacote integer;
alter table pagamentos_pix add column if not exists parcelas integer not null default 1;

alter table pacotes_horas_avulsas enable row level security;
