-- Matriz v2 (pedido do Paulo em 21/10/2026):
--   * "Matrizes geradas" + "Desfazer a matriz": cada replicação passa a guardar,
--     item a item, o que ela CRIOU e o que ela LIBEROU em matriz_reservas_admin,
--     para poder ser desfeita depois (as últimas 5 aparecem na tela);
--   * "ocultar dia" em Visualizar agenda: dias_ocultos guarda as datas que
--     ficam invisíveis (e não reserváveis) para os médicos.
-- Idempotente: pode rodar mais de uma vez sem erro.

alter table matriz_replicacoes add column if not exists desfeita_em timestamptz;
alter table matriz_replicacoes add column if not exists liberados integer not null default 0;
alter table matriz_replicacoes add column if not exists canceladas_medico integer not null default 0;
-- true só nas replicações feitas depois desta migração (as antigas não têm
-- registro item a item, então não dá pra desfazer com segurança).
alter table matriz_replicacoes add column if not exists com_registro boolean not null default false;

create table if not exists matriz_replicacao_itens (
    id uuid primary key default uuid_generate_v4(),
    replicacao_id uuid not null references matriz_replicacoes(id) on delete cascade,
    acao text not null check (acao in ('criou', 'liberou')),
    consultorio_id uuid not null,
    data date not null,
    horario time not null,
    descricao text,
    criado_em timestamptz not null default now()
);
create index if not exists idx_matriz_itens_replicacao on matriz_replicacao_itens(replicacao_id);
create index if not exists idx_matriz_itens_data on matriz_replicacao_itens(data);
alter table matriz_replicacao_itens enable row level security;

create table if not exists dias_ocultos (
    data date primary key,
    criado_em timestamptz not null default now()
);
alter table dias_ocultos enable row level security;
