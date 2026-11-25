-- v128: HISTÓRICO AUTOMÁTICO de cópias completas dos dados (uma por hora, guardadas por 48 horas).
-- Rode UMA vez no SQL Editor do Neon. É seguro rodar de novo (não apaga nada).
-- Cada linha é um arquivo de backup compactado (o mesmo formato do Admin > Backup). Origem:
--   'automatico' (a cada hora) | 'manual' (botão "Guardar cópia agora") | 'antes_restaurar' (feita sozinha antes de uma restauração)
--   | 'bloqueado' (a cópia NÃO foi feita porque os dados atuais estavam muito menores que a anterior; sem arquivo).
create table if not exists historico_dados (
    id bigserial primary key,
    criado_em timestamptz not null default now(),
    origem text not null default 'automatico',
    total_linhas integer not null default 0,
    resumo jsonb,
    tamanho_bytes integer not null default 0,
    observacao text,
    arquivo bytea
);
create index if not exists idx_historico_dados_criado on historico_dados (criado_em desc);
alter table historico_dados enable row level security;
