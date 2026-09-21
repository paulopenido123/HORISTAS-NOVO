-- Pedido do Paulo em 21/09/2026: "tryout" pro médico avulso conhecer o
-- sistema -- as 3 primeiras reservas de consultório (por hora) não
-- debitam saldo, em qualquer canal (site ou assistente de WhatsApp
-- Dora). Da 4ª reserva em diante, precisa ter crédito normalmente.
-- `tryout=true` marca quais reservas usaram essa cortesia -- o "quanto
-- ainda falta" é sempre CALCULADO contando reservas tryout NÃO
-- canceladas desse médico (ver creditos_service.tryout_restante), não
-- guardado num contador separado, pra cancelar uma reserva de teste
-- devolver a cortesia automaticamente (mesma lógica de sempre).
alter table reservas add column if not exists tryout boolean not null default false;
