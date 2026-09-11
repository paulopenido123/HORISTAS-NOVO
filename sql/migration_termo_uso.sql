-- Guarda se e quando o médico aceitou o Termo de Uso — necessário para
-- ter prova do aceite (data/hora + IP) em caso de disputa jurídica.

alter table medicos add column if not exists termo_aceito boolean not null default false;
alter table medicos add column if not exists termo_aceito_em timestamptz;
alter table medicos add column if not exists termo_aceito_ip text;
