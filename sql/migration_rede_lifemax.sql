-- Rede Lifemax: perfil público do médico (site novo, outro domínio,
-- mesmo banco) + avaliações de pacientes com confirmação por e-mail.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

-- 1) Campos novos no cadastro do médico -- tudo opcional/desligado por
--    padrão: o médico só aparece na Rede Lifemax depois de ele mesmo
--    ativar (visivel_rede_lifemax), na aba nova do painel dele.
alter table medicos add column if not exists foto_perfil_url text;
alter table medicos add column if not exists bio_publica text;
alter table medicos add column if not exists especialidades_publicas text[] not null default '{}';
alter table medicos add column if not exists visivel_rede_lifemax boolean not null default false;
-- latitude/longitude calculados automaticamente a partir do endereço
-- (endereco_cep/rua/numero/bairro/cidade/estado, que já existem desde
-- migration_endereco_medico.sql) -- usados só para posicionar o pino
-- no mapa da Rede Lifemax.
alter table medicos add column if not exists latitude numeric(9,6);
alter table medicos add column if not exists longitude numeric(9,6);

comment on column medicos.foto_perfil_url is 'Foto de perfil pública (Rede Lifemax) -- bucket perfis-medicos';
comment on column medicos.bio_publica is 'Texto "Sobre" exibido no perfil público da Rede Lifemax';
comment on column medicos.especialidades_publicas is 'Áreas de atuação/tags extras exibidas no perfil público, além da especialidade principal';
comment on column medicos.visivel_rede_lifemax is 'Se true, o médico aparece na busca e tem perfil público na Rede Lifemax';
comment on column medicos.latitude is 'Latitude calculada a partir do endereço, para o mapa da Rede Lifemax';
comment on column medicos.longitude is 'Longitude calculada a partir do endereço, para o mapa da Rede Lifemax';

-- 2) Avaliações de pacientes sobre o médico (estrelas de 1 a 5).
--    Só fica pública (confirmado = true) depois que o paciente clica no
--    link de confirmação mandado por e-mail -- evita avaliação fake
--    feita em nome de outra pessoa. O hash do token segue o mesmo
--    padrão de segurança de tokens_recuperacao_senha (nunca guardamos
--    o token em texto puro).
create table if not exists avaliacoes_medico (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    paciente_nome text not null,
    paciente_email text not null,
    nota integer not null check (nota between 1 and 5),
    comentario text,
    confirmado boolean not null default false,
    visivel boolean not null default true,   -- admin pode ocultar uma avaliação problemática sem apagar o histórico
    token_hash text,
    token_expira_em timestamptz,
    criado_em timestamptz not null default now(),
    confirmado_em timestamptz
);

create index if not exists idx_avaliacoes_medico_id on avaliacoes_medico(medico_id);
create index if not exists idx_avaliacoes_confirmado on avaliacoes_medico(medico_id, confirmado, visivel);

-- Evita duas avaliações CONFIRMADAS do mesmo paciente (mesmo e-mail)
-- pro mesmo médico -- o serviço também confere isso antes de criar,
-- mas o índice único garante isso mesmo em caso de corrida.
create unique index if not exists idx_avaliacoes_unica_confirmada
    on avaliacoes_medico(medico_id, paciente_email)
    where confirmado;

alter table avaliacoes_medico enable row level security;

-- 3) Bucket de storage para as fotos de perfil dos médicos (Rede Lifemax).
--
-- ⚠️ Migração pra Neon (10/09/2026): este pacote (Reserva de Horas) não
-- usa o módulo Rede Lifemax -- o bloco abaixo só roda se o schema
-- "storage" existir (Supabase). Se a Rede Lifemax for implantada no
-- futuro sobre o Neon, este bucket precisa ser recriado no Neon Object
-- Storage (público) em vez de por SQL.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('perfis-medicos', 'perfis-medicos', true)
    on conflict (id) do nothing;

    drop policy if exists "Fotos de perfil sao publicas" on storage.objects;
    create policy "Fotos de perfil sao publicas"
    on storage.objects for select
    using (bucket_id = 'perfis-medicos');

    drop policy if exists "Somente service role gerencia fotos de perfil" on storage.objects;
    create policy "Somente service role gerencia fotos de perfil"
    on storage.objects for all
    using (bucket_id = 'perfis-medicos' and auth.role() = 'service_role');
  end if;
end $$;
