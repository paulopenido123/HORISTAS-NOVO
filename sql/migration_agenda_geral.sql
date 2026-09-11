-- Agenda geral do médico — igual à do Google, mas dentro do sistema.
-- Diferente das "reservas" (que são especificamente aluguel de
-- consultório), aqui o médico pode marcar qualquer compromisso.
-- Se ele tiver o Google Agenda conectado, todo evento criado/editado/
-- apagado aqui é automaticamente refletido lá também.

create table if not exists eventos_agenda (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    titulo text not null,
    descricao text,
    data date not null,
    hora_inicio time not null,
    hora_fim time not null,
    google_evento_id text,     -- preenchido se sincronizado com o Google
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create index if not exists idx_eventos_agenda_medico_data on eventos_agenda(medico_id, data);

alter table eventos_agenda enable row level security;
