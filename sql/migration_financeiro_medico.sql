-- Módulo Financeiro do médico — emissão de recibos, leitura de despesa
-- por foto (IA Luna) e exportação para a contabilidade. Rode depois de
-- migration_contabilidade_medica.sql.

-- CRM do médico — necessário para aparecer no recibo emitido para o paciente.
alter table medicos add column if not exists crm text;

-- Bucket de storage para os PDFs de recibo (público, pelo mesmo motivo
-- do bucket 'consultorios': o WhatsApp Cloud API só consegue mandar um
-- documento a partir de uma URL que ele mesmo consiga baixar sem login).
--
-- ⚠️ Migração pra Neon (10/09/2026): o schema "storage" (com as tabelas
-- storage.buckets/storage.objects e as "policies" de storage) é uma
-- coisa específica do Supabase -- não existe em Postgres puro nem no
-- Neon. O bloco abaixo só roda se esse schema existir (ou seja: se você
-- algum dia reinstalar esse SQL contra um projeto Supabase de novo) --
-- no Neon, o bucket de recibos (se/quando esse módulo for usado por
-- este pacote) deve ser criado direto no Neon Console ou via `neon
-- buckets create`, não por SQL. Veja app/services/neon_storage.py.
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('recibos', 'recibos', true)
    on conflict (id) do nothing;

    -- Postgres não aceita "create policy if not exists" (essa cláusula não
    -- existe para policy) -- por isso apaga antes de recriar, o que também
    -- deixa essa migração segura de rodar de novo sem dar erro.
    drop policy if exists "Recibos sao publicos para leitura" on storage.objects;
    create policy "Recibos sao publicos para leitura"
    on storage.objects for select
    using (bucket_id = 'recibos');

    drop policy if exists "Somente service role gerencia recibos" on storage.objects;
    create policy "Somente service role gerencia recibos"
    on storage.objects for all
    using (bucket_id = 'recibos' and auth.role() = 'service_role');
  end if;
end $$;
