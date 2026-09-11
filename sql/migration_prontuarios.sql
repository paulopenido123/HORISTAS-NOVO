-- Armazenamento de PRONTUÁRIO ELETRÔNICO e EXAMES — dado sensível
-- (LGPD), por isso tudo aqui é privado por padrão: bucket sem acesso
-- público, link de acesso sempre temporário (gerado na hora, expira em
-- minutos), e toda visualização fica registrada em auditoria.

-- Bucket PRIVADO (public=false, diferente do bucket de fotos dos
-- consultórios, que é público de propósito)
--
-- ⚠️ Migração pra Neon (10/09/2026): este pacote (Reserva de Horas) não
-- usa o módulo de prontuário -- o bloco abaixo só roda se o schema
-- "storage" existir (Supabase). Se o módulo de prontuário for
-- implantado no futuro sobre o Neon, este bucket precisa ser recriado
-- no Neon Object Storage (privado) em vez de por SQL.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('prontuarios', 'prontuarios', false)
    on conflict (id) do nothing;

    -- Só o backend (service_role) acessa esse bucket — nem sequer os
    -- usuários autenticados via anon key conseguem ler direto; todo acesso
    -- passa pelo nosso sistema, que decide se libera ou não.
    drop policy if exists "Somente service role acessa prontuarios" on storage.objects;
    create policy "Somente service role acessa prontuarios"
    on storage.objects for all
    using (bucket_id = 'prontuarios' and auth.role() = 'service_role');
  end if;
end $$;

-- Anotações de prontuário eletrônico (texto) feitas pelo médico
create table if not exists prontuarios (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_telefone text,
    conteudo text not null,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);
create index if not exists idx_prontuarios_medico_paciente on prontuarios(medico_id, paciente_nome);

-- Arquivos de exame (fotos, PDFs de resultado, etc.) — o arquivo em si
-- fica no bucket privado 'prontuarios', aqui só ficam os metadados
create table if not exists exames_arquivos (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    nome_arquivo text not null,
    storage_path text not null,        -- caminho dentro do bucket privado
    tipo_arquivo text,                  -- ex: 'image/jpeg', 'application/pdf'
    tamanho_bytes bigint,
    criado_em timestamptz not null default now()
);
create index if not exists idx_exames_medico_paciente on exames_arquivos(medico_id, paciente_nome);

-- Auditoria: quem acessou o quê e quando — praticamente exigido pela
-- LGPD para dado sensível de saúde, e te protege numa eventual disputa
create table if not exists auditoria_acessos (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    tipo_recurso text not null check (tipo_recurso in ('prontuario', 'exame')),
    recurso_id uuid not null,
    acao text not null check (acao in ('visualizar', 'criar', 'editar', 'baixar')),
    ip text,
    criado_em timestamptz not null default now()
);
create index if not exists idx_auditoria_medico on auditoria_acessos(medico_id, criado_em desc);

alter table prontuarios enable row level security;
alter table exames_arquivos enable row level security;
alter table auditoria_acessos enable row level security;
