-- Avisos automáticos por e-mail -- pedido do Paulo em 11/09/2026:
--   1) confirmação do e-mail do médico (link que ele clica; depois disso
--      aparece uma ⭐ do lado do e-mail na lista de Clientes do admin);
--   2) aviso ao admin por e-mail quando um médico novo se autocadastra
--      pelo site e precisa ser liberado;
--   3) aviso ao médico por e-mail quando o admin libera o acesso dele;
--   4) recibo por e-mail quando o médico compra horas;
--   5) confirmação de agendamento/cancelamento pro médico + e-mail pro
--      paciente com dia, endereço e consultório -- inclui campo de
--      "confirmação da hora" (pro médico bater o horário exato antes de
--      mandar, já que reserva de TURNO cobre um período inteiro) e
--      suporte a mais de um paciente na mesma reserva.
--
-- Os tokens de confirmação de e-mail reaproveitam a MESMA tabela
-- `tokens_recuperacao_senha` (ver migration_recuperacao_senha.sql) que já
-- existe pra "esqueci minha senha"/primeiro acesso -- só usa um
-- `contexto` novo ('confirmar_email'), sem precisar de tabela nova.

alter table medicos add column if not exists email_confirmado boolean not null default false;

-- O token de confirmação de e-mail reaproveita a coluna `contexto` de
-- tokens_recuperacao_senha (ver migration_primeiro_acesso_admin.sql),
-- que só aceitava ('recuperacao', 'primeiro_acesso') até aqui -- precisa
-- liberar o valor novo 'confirmar_email' no check constraint.
alter table tokens_recuperacao_senha drop constraint if exists tokens_recuperacao_senha_contexto_check;
alter table tokens_recuperacao_senha add constraint tokens_recuperacao_senha_contexto_check
    check (contexto in ('recuperacao', 'primeiro_acesso', 'confirmar_email'));

-- Confirmação de horário da reserva (pro médico bater o olho e confirmar
-- a hora exata da consulta antes de mandar o e-mail pro paciente -- útil
-- principalmente pra reserva de TURNO, que cobre um período inteiro em
-- vez de um horário exato).
alter table reservas add column if not exists hora_confirmada text;

-- Pacientes de uma mesma reserva que devem receber o e-mail de
-- confirmação de agendamento -- por padrão só o paciente marcado em
-- "Incluir/alterar paciente" (reservas.paciente_id), mas o médico pode
-- incluir mais de um com o botão "+ Adicionar paciente" na tela "Minha
-- agenda" (ex: mais de um paciente marcado pro mesmo horário/turno).
-- `email_enviado_em` fica preenchido depois que o e-mail é mandado pra
-- ESSE paciente especificamente -- cada paciente tem seu próprio
-- controle de envio (pode reenviar quantas vezes quiser, não some).
create table if not exists reserva_pacientes (
    id uuid primary key default uuid_generate_v4(),
    reserva_id uuid not null references reservas(id),
    paciente_id uuid not null references pacientes(id),
    email_enviado_em timestamptz,
    criado_em timestamptz not null default now(),
    unique (reserva_id, paciente_id)
);

create index if not exists idx_reserva_pacientes_reserva on reserva_pacientes(reserva_id);

alter table reserva_pacientes enable row level security;

-- Preenche o endereço padrão da Lifemax (colunas já existiam desde
-- migration_endereco_padrao_lifemax.sql, mas nenhuma tela usava ainda --
-- agora usado no e-mail de agendamento pro paciente) só se ainda
-- estiver vazio, pra não sobrescrever se o admin já tiver preenchido
-- outra coisa por conta própria entretanto. Editável em Admin > Horas.
update precos set
    endereco_padrao_rua = 'Gonçalves Dias',
    endereco_padrao_numero = '82',
    endereco_padrao_bairro = 'Funcionários',
    endereco_padrao_cidade = 'Belo Horizonte',
    endereco_padrao_estado = 'MG'
where coalesce(endereco_padrao_rua, '') = '';
