-- Cadastro rápido de clientes/contatos de cada médico (Nome, endereço,
-- e-mail e telefone/WhatsApp) -- pedido do Paulo em 10/09/2026, botão
-- "Incluir dados cliente" na página do médico (área do cliente).
--
-- OBS: isso é só um cadastro de contato solto, sem vínculo com
-- consulta/prontuário -- esse pacote (Reserva por Hora) não inclui a
-- Agenda de Pacientes/Prontuários do sistema maior da Lifemax.

create table if not exists clientes_medico (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),
    nome text not null,
    endereco text,
    email text,
    telefone text,
    criado_em timestamptz not null default now()
);

create index if not exists idx_clientes_medico_medico_id on clientes_medico(medico_id);

alter table clientes_medico enable row level security;
