-- Telefone do paciente (cadastro simplificado: nome, telefone e e-mail) --
-- 22/10/2026. Idempotente.
alter table pacientes add column if not exists telefone text;
