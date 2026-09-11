-- Guarda a conexão OAuth de cada médico com o Google Agenda dele.
-- Os tokens ficam só no backend (nunca expostos ao navegador) — são
-- usados pelo servidor para checar conflito e criar eventos em nome
-- do médico, com a autorização que ele deu no fluxo do Google.

alter table medicos add column if not exists google_calendar_conectado boolean not null default false;
alter table medicos add column if not exists google_access_token text;
alter table medicos add column if not exists google_refresh_token text;
alter table medicos add column if not exists google_token_expira_em timestamptz;
alter table medicos add column if not exists google_calendar_id text default 'primary';

-- Guarda o ID do evento criado no Google Agenda, para conseguir
-- cancelar/atualizar o evento se a reserva for cancelada depois.
alter table reservas add column if not exists google_evento_id text;
