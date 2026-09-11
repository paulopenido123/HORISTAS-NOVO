-- Bucket de storage para as fotos dos consultórios.
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso (depois do schema.sql).
--
-- ⚠️ Migração pra Neon (10/09/2026): o bucket 'consultorios' (fotos dos
-- consultórios) foi migrado pro Neon Object Storage -- ele NÃO é
-- configurado por SQL, mas direto no Neon Console (ou `neon buckets
-- create`). Veja app/services/neon_storage.py e INSTALAR.md. O bloco
-- abaixo só roda se o schema "storage" existir (ou seja: só se esse SQL
-- for aplicado contra um projeto Supabase -- no Neon ele é ignorado sem
-- dar erro, de propósito).
do $$
begin
  if exists (select 1 from pg_namespace where nspname = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('consultorios', 'consultorios', true)
    on conflict (id) do nothing;

    -- Permite leitura pública das fotos (necessário para elas aparecerem
    -- no WhatsApp e na página pública sem precisar de autenticação)
    -- Postgres não aceita "create policy if not exists" -- por isso apaga
    -- antes de recriar, o que também deixa essa migração segura de rodar
    -- de novo sem dar erro.
    drop policy if exists "Fotos de consultorios sao publicas" on storage.objects;
    create policy "Fotos de consultorios sao publicas"
    on storage.objects for select
    using (bucket_id = 'consultorios');

    -- Só o backend (service_role key) pode enviar/apagar fotos —
    -- o upload é feito pelo admin do sistema, não diretamente pelo navegador
    drop policy if exists "Somente service role gerencia fotos" on storage.objects;
    create policy "Somente service role gerencia fotos"
    on storage.objects for all
    using (bucket_id = 'consultorios' and auth.role() = 'service_role');
  end if;
end $$;
