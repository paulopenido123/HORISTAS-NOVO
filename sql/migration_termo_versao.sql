-- Guarda qual VERSÃO do Contrato Digital (app/services/contrato_service.py,
-- CONTRATO_VERSAO) cada médico aceitou -- pedido do Paulo em 10/09/2026,
-- junto com o botão de baixar o contrato em PDF a qualquer momento
-- (rota /contrato/baixar). Sem isso, se o texto do contrato mudar no
-- futuro, não teria como saber com certeza qual versão um médico
-- específico realmente aceitou no passado.

alter table medicos add column if not exists termo_versao text;
