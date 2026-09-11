-- Controla se o assistente de WhatsApp já foi liberado para o médico.
-- Fica falso até o admin clicar em "Ligar assistente" no dashboard —
-- o que só é permitido depois do primeiro pagamento confirmado.

alter table medicos add column if not exists assistente_ativo boolean not null default false;
