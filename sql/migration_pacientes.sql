-- Cadastro completo de pacientes de cada médico -- pedido do Paulo em
-- 11/09/2026: botão "Cadastre o seu paciente" no painel do médico, com
-- ficha completa (dados pessoais, endereço e responsável), e vínculo do
-- paciente escolhido com um horário já reservado (botão "Incluir/alterar
-- paciente" na própria agenda do médico).
--
-- Diferente de `clientes_medico` (cadastro rápido de contato solto, sem
-- ficha completa) e de `agenda_pacientes`/`consultas_pacientes` (lembrete
-- automático de WhatsApp, não fazem parte deste pacote) -- esta tabela é
-- a ficha de cadastro de verdade do paciente, sempre presa a um médico
-- (cada médico só vê/edita os próprios pacientes).

create table if not exists pacientes (
    id uuid primary key default uuid_generate_v4(),
    medico_id uuid not null references medicos(id),

    -- Informações pessoais
    nome_completo text not null,
    nome_pai text,
    nome_mae text,
    data_nascimento date,
    cpf text,
    rg text,
    email text,
    sexo text,                 -- "Masculino" | "Feminino"
    estado_civil text,         -- "Solteiro" | "Casado" | "Divorciado" | "Viúvo" | "União estável"
    cor text,                  -- "Leucoderma" | "Faioderma" | "Melanoderma"
    convenio text,
    profissao text,
    indicacao text,

    -- Endereço
    endereco text,
    bairro text,
    cep text,
    cidade text,
    estado text,

    -- Informações do responsável
    responsavel_nome text,
    responsavel_tipo text,     -- "Mãe" | "Pai" | "Cônjuge" | "Filho" | "Filha" | "Avô" | "Avó" | "Tio" | "Tia" | "Parceiro" | "Outro"
    responsavel_telefone text,

    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create index if not exists idx_pacientes_medico on pacientes(medico_id);

alter table pacientes enable row level security;

-- Qual paciente (dos cadastrados pelo médico) está marcado pra ocupar um
-- horário já reservado -- aparece na tabela "Minha agenda" do painel do
-- médico. Fica nulo até o médico escolher (botão "Incluir/alterar
-- paciente"); trocar o valor é só clicar de novo e escolher outro.
alter table reservas add column if not exists paciente_id uuid references pacientes(id);
