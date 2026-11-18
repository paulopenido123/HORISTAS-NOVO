-- v100: documento de identidade/profissional do médico (CRM, RG, CNH...), enviado por ele em
-- "Meus dados" e visível SOMENTE para o administrador. Guardado no próprio banco (bytea), nunca em
-- bucket público. Um documento por médico (reenviar substitui). Rodar no Neon (SQL Editor).
create table if not exists documentos_medico (
    medico_id uuid primary key references medicos(id) on delete cascade,
    nome_arquivo text not null,
    content_type text not null,
    tamanho integer not null,
    conteudo bytea not null,
    enviado_em timestamptz not null default now()
);
alter table documentos_medico enable row level security;
