-- Telão de chamada de pacientes por ANDAR (antes só existia um telão
-- único pra recepção inteira). O andar de cada consultório já existe
-- (coluna `consultorios.andar`, de migration_agenda_medicos_fixos.sql)
-- -- essa migração só guarda esse andar também no histórico de
-- chamados, pra dar pra filtrar o telão de cada andar sem precisar de
-- join toda hora.

alter table chamados_recepcao add column if not exists andar text;

comment on column chamados_recepcao.andar is
    'Andar do consultório no momento da chamada (copiado de consultorios.andar) -- usado pra cada telão mostrar só as chamadas do próprio andar';

create index if not exists idx_chamados_recepcao_andar on chamados_recepcao(andar, chamado_em desc);
