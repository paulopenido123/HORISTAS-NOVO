-- Reorganiza a numeração e os nomes dos módulos conforme definição do
-- Paulo: Módulo 1 fica só com a venda de horas/turnos avulsos (o que já
-- está funcionando), e entra um novo Módulo 2 — Integração para
-- Clientes Fixos. Os demais módulos são renumerados em sequência.
--
-- Como não existe nenhuma outra tabela referenciando modulos.id por
-- chave estrangeira, é seguro apagar e recriar a lista inteira.

delete from modulos;

insert into modulos (numero, slug, nome, descricao, icone, status, rota, ordem) values

(1, 'venda-horas-avulsas', 'Venda de Horas Avulsas',
   'Venda de horas e turnos avulsos de consultório — reservas, créditos, PIX/cartão, '
   'confirmação de consulta e assistente via WhatsApp e painel web.',
   '🤖', 'ativo', '/painel', 1),

(2, 'clientes-fixos', 'Integração para Clientes Fixos',
   'Modelo de plano/assinatura fixa para médicos com uso recorrente do coworking — '
   'faturamento e agenda diferenciados de quem usa por hora avulsa.',
   '🔁', 'em_desenvolvimento', null, 2),

(3, 'recibos', 'Recibos de Pagamento',
   'Gerar recibo em PDF para os pagamentos recebidos de pacientes.',
   '🧾', 'em_desenvolvimento', null, 3),

(4, 'contabilidade', 'Preparação Contábil',
   'Relatório mensal/anual pronto para entregar ao contador do médico.',
   '📊', 'em_desenvolvimento', null, 4),

(5, 'nota-fiscal-nfse', 'Nota Fiscal (Receita Federal)',
   'Emissão de nota fiscal de serviço eletrônica, integrada a um provedor homologado.',
   '📄', 'em_desenvolvimento', null, 5),

(6, 'videoconferencia', 'Videoconferência e Prescrição',
   'Ambiente fechado de vídeo entre médico e paciente (dois ou mais usuários), com '
   'emissão de receita digital direto durante a chamada.',
   '🎥', 'em_desenvolvimento', null, 6),

(7, 'prescricao', 'Prescrição Médica Digital',
   'Emissão de receita digital com validade jurídica, via parceiro homologado (ex: Memed) — '
   'usada tanto dentro do Módulo 6 (vídeo) quanto de forma avulsa. '
   'Ideia futura: comparação de preços/disponibilidade de medicamentos entre farmácias — '
   'sem influenciar a escolha clínica do médico, por causa da vedação do CFM a comissão por indicação.',
   '💊', 'em_desenvolvimento', null, 7),

(8, 'prontuario', 'Prontuário e Exames',
   'Receber exames do paciente e comparar com o histórico do prontuário.',
   '🗂️', 'em_desenvolvimento', null, 8),

(9, 'marketing', 'Análise Mercadológica',
   'Sugestões de captação de pacientes com base nos dados do próprio sistema.',
   '📈', 'em_desenvolvimento', null, 9),

(10, 'suprimentos', 'Fornecimento de Medicamentos e Suprimentos',
   'Marketplace conectando fabricantes e fornecedores aos médicos, como intermediário '
   'de compra de equipamentos e suprimentos médicos.',
   '📦', 'em_desenvolvimento', null, 10);
