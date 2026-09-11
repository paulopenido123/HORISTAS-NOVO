-- Atualiza os horários padrão dos turnos:
--   manhã: 08:00–12:00 (era 07:00–11:00)
--   tarde: 13:00–17:00 (sem mudança)
--   noite: 17:00–20:00 (era 18:00–22:00 — agora só 3 horas, não 4)
--
-- Precisa recriar a coluna gerada + a trava de sobreposição de
-- sql/migration_protecao_conflito.sql, porque colunas geradas não
-- podem ser alteradas diretamente no Postgres — só recriadas.
-- Rode isso DEPOIS de migration_protecao_conflito.sql.
--
-- Usa tsrange (sem fuso horário) em vez de tstzrange — a conta
-- "data + hora" já gera um horário sem fuso, e o Postgres exige que
-- colunas geradas usem só contas "imutáveis" (que não dependem de
-- configuração do servidor, como fuso horário).

create extension if not exists btree_gist;

alter table reservas drop constraint if exists reservas_sem_sobreposicao;
alter table reservas drop column if exists intervalo_ocupado;

alter table reservas add column intervalo_ocupado tsrange
    generated always as (
        case
            when tipo_reserva = 'turno' and periodo = 'manha' then tsrange(data + time '08:00', data + time '12:00')
            when tipo_reserva = 'turno' and periodo = 'tarde' then tsrange(data + time '13:00', data + time '17:00')
            when tipo_reserva = 'turno' and periodo = 'noite' then tsrange(data + time '17:00', data + time '20:00')
            when tipo_reserva = 'hora' and hora_inicio is not null and hora_fim is not null
                then tsrange(data + hora_inicio, data + hora_fim)
            else null
        end
    ) stored;

alter table reservas add constraint reservas_sem_sobreposicao
    exclude using gist (consultorio_id with =, intervalo_ocupado with &&)
    where (status <> 'cancelada');
