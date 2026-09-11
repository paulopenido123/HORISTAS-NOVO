-- Sistema de módulos: cada funcionalidade grande do sistema (Assistente
-- Pessoal, Recibos, Contabilidade, Nota Fiscal, Videoconferência,
-- Prescrição, Prontuário, Marketing) vira uma linha aqui, com um status.
--
-- Médicos "beta tester" (por enquanto, só você) veem TODOS os módulos,
-- inclusive os "em desenvolvimento" (aparecem como "em breve" na tela).
-- Médicos comuns só veem os módulos com status 'ativo'.

alter table medicos add column if not exists is_beta_tester boolean not null default false;

create table if not exists modulos (
    id uuid primary key default uuid_generate_v4(),
    numero integer not null unique,
    slug text not null unique,
    nome text not null,
    descricao text,
    icone text,
    status text not null default 'em_desenvolvimento' check (status in ('em_desenvolvimento', 'beta', 'ativo')),
    rota text,          -- caminho dentro do sistema, quando já existir (ex: '/painel')
    ordem integer not null default 0
);

insert into modulos (numero, slug, nome, descricao, icone, status, rota, ordem) values
(1, 'assistente-pessoal', 'Assistente Pessoal',
   'Contato com paciente, agenda, reservas de consultório e créditos — via WhatsApp e painel web.',
   '🤖', 'ativo', '/painel', 1),
(2, 'recibos', 'Recibos de Pagamento',
   'Gerar recibo em PDF para os pagamentos recebidos de pacientes.',
   '🧾', 'em_desenvolvimento', null, 2),
(3, 'contabilidade', 'Preparação Contábil',
   'Relatório mensal/anual pronto para entregar ao contador do médico.',
   '📊', 'em_desenvolvimento', null, 3),
(4, 'nota-fiscal-nfse', 'Nota Fiscal (Receita Federal)',
   'Emissão de nota fiscal de serviço eletrônica, integrada a um provedor homologado.',
   '📄', 'em_desenvolvimento', null, 4),
(5, 'videoconferencia', 'Videoconferência',
   'Consulta por vídeo com o paciente, direto pelo painel web (fora do WhatsApp).',
   '🎥', 'em_desenvolvimento', null, 5),
(6, 'prescricao', 'Prescrição Médica Digital',
   'Emissão de receita digital com validade jurídica, via parceiro homologado (ex: Memed).',
   '💊', 'em_desenvolvimento', null, 6),
(7, 'prontuario', 'Prontuário e Exames',
   'Receber exames do paciente e comparar com o histórico do prontuário.',
   '🗂️', 'em_desenvolvimento', null, 7),
(8, 'marketing', 'Análise Mercadológica',
   'Sugestões de captação de pacientes com base nos dados do próprio sistema.',
   '📈', 'em_desenvolvimento', null, 8)
on conflict (numero) do nothing;

alter table modulos enable row level security;
