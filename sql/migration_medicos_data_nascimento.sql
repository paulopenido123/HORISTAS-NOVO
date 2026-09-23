-- Data de nascimento do médico -- pedido do Paulo em 23/09/2026 (item 2):
-- passa a ser um dos campos obrigatórios pra completar o cadastro antes
-- de poder reservar (junto com endereço, telefone, e-mail, especialidade
-- e CPF -- ver reserva_service._CAMPOS_OBRIGATORIOS_PARA_RESERVAR), e
-- também entra no PDF do contrato aceito (ver pdf_service.gerar_pdf_contrato).
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

alter table medicos add column if not exists data_nascimento date;
