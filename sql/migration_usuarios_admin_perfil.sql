-- Perfis do painel admin (22/10/2026): 'admin' (acesso total) e 'secretaria'
-- (tudo, exceto Horas, Relatórios e Usuários).
alter table usuarios_admin add column if not exists perfil text not null default 'admin';
alter table usuarios_admin drop constraint if exists usuarios_admin_perfil_check;
alter table usuarios_admin add constraint usuarios_admin_perfil_check check (perfil in ('admin', 'secretaria'));
