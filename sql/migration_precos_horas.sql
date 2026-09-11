-- Migração: precificação escalonada por hora (1ª, 2ª, 3ª hora + turno = 4h)
-- e suporte a reservas avulsas por hora (além das reservas por turno).
-- Rode depois de migration_creditos.sql.

alter table precos add column if not exists preco_hora_1 numeric(10,2) not null default 0;
alter table precos add column if not exists preco_hora_2 numeric(10,2) not null default 0;
alter table precos add column if not exists preco_hora_3 numeric(10,2) not null default 0;
alter table precos add column if not exists horas_minimas integer not null default 1;

-- Se você já tinha um preco_hora único configurado antes, usa ele como
-- ponto de partida nas 3 faixas (ajuste depois em /admin/precos)
update precos
set preco_hora_1 = coalesce(preco_hora, 0),
    preco_hora_2 = coalesce(preco_hora, 0),
    preco_hora_3 = coalesce(preco_hora, 0)
where preco_hora_1 = 0 and preco_hora_2 = 0 and preco_hora_3 = 0;

-- Reservas por turno continuam como sempre. Reservas por hora avulsa
-- usam hora_inicio/hora_fim/quantidade_horas em vez de período fixo.
alter table reservas alter column periodo drop not null;
alter table reservas add column if not exists tipo_reserva text not null default 'turno'
    check (tipo_reserva in ('turno', 'hora'));
alter table reservas add column if not exists hora_inicio time;
alter table reservas add column if not exists hora_fim time;
alter table reservas add column if not exists quantidade_horas integer;
