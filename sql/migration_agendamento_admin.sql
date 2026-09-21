-- Pedido do Paulo em 21/09/2026: botões "Agendar para:" e "Cancelar
-- agendamento" na Agenda Horistas (admin) -- o administrador passa a
-- poder criar ou cancelar reservas EM NOME de um médico avulso. Essas
-- duas colunas marcam quando isso aconteceu, pra Grade de Turnos, Minha
-- Agenda e o extrato de horas do médico poderem avisar claramente que
-- foi o administrador (e não o próprio médico) quem agendou/cancelou.
alter table reservas add column if not exists criado_por_admin boolean not null default false;
alter table reservas add column if not exists cancelado_por_admin boolean not null default false;
