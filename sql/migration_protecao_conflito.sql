-- Garante, a nível de BANCO DE DADOS, que nenhum consultório pode ter
-- dois horários sobrepostos reservados ao mesmo tempo — mesmo se dois
-- médicos clicarem em "reservar" no exato mesmo instante.
--
-- A reserva de TURNO já era protegida pela trava 'unique' em schema.sql.
-- Esta migração fecha a mesma proteção para reservas AVULSAS POR HORA,
-- que até agora só eram checadas em código Python (seguro na prática,
-- mas tecnicamente vulnerável a uma condição de corrida em alta
-- concorrência). Com isso, mesmo bilhões de cliques simultâneos não
-- conseguiriam gerar uma reserva duplicada — o banco rejeita de forma
-- atômica.

create extension if not exists btree_gist;

-- Coluna calculada automaticamente: o intervalo de tempo que a reserva
-- ocupa, seja ela por turno (horário fixo do período) ou por hora
-- (hora_inicio/hora_fim). Os horários de turno aqui precisam ser os
-- MESMOS usados em app/services/supabase_client.py (PERIODOS_HORARIOS)
-- — se um dia você mudar os horários dos turnos, ajuste os dois lugares.
alter table reservas add column if not exists intervalo_ocupado tsrange
    generated always as (
        case
            when tipo_reserva = 'turno' and periodo = 'manha' then tsrange(data + time '07:00', data + time '11:00')
            when tipo_reserva = 'turno' and periodo = 'tarde' then tsrange(data + time '13:00', data + time '17:00')
            when tipo_reserva = 'turno' and periodo = 'noite' then tsrange(data + time '18:00', data + time '22:00')
            when tipo_reserva = 'hora' and hora_inicio is not null and hora_fim is not null
                then tsrange(data + hora_inicio, data + hora_fim)
            else null
        end
    ) stored;

alter table reservas drop constraint if exists reservas_sem_sobreposicao;
alter table reservas add constraint reservas_sem_sobreposicao
    exclude using gist (consultorio_id with =, intervalo_ocupado with &&)
    where (status <> 'cancelada');
