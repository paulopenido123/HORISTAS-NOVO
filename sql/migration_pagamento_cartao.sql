-- Suporte a pagamento por cartão de crédito (além do PIX já existente).
-- Guarda a forma de pagamento e o link da fatura do Asaas (onde o
-- médico digita os dados do cartão, numa página segura do próprio
-- Asaas — o nosso sistema nunca vê o número do cartão).

alter table pagamentos_pix add column if not exists forma_pagamento text not null default 'pix'
    check (forma_pagamento in ('pix', 'cartao'));
alter table pagamentos_pix add column if not exists invoice_url text;
