-- Guarda o instante em que uma reserva foi CANCELADA (distinto de
-- criado_em, que é sempre o instante em que ela foi feita) -- pedido do
-- Paulo em 10/09/2026, junto com o botão "Cancelar" na Grade de Turnos e
-- em "Minha Agenda": sem essa coluna não dava pra saber QUANDO o
-- cancelamento aconteceu, o que é necessário pro relatório de
-- "Agendamentos" (aba Relatórios do admin) mostrar a ocorrência do
-- cancelamento na linha do tempo certa.
alter table reservas add column if not exists cancelado_em timestamptz;
