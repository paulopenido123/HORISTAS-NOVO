-- "Dados Pessoais" do médico -- campos que hoje só existem na planilha
-- de 74 médicos (lida só pro WhatsApp responder perguntas, nunca
-- editável pelo próprio médico). Agora viram campos de verdade no
-- cadastro dele, editáveis na nova tela "Dados Pessoais".

alter table medicos add column if not exists valor_consulta numeric(10,2);
alter table medicos add column if not exists tempo_consulta text;
alter table medicos add column if not exists formas_pagamento text;
alter table medicos add column if not exists politica_cancelamento text;
alter table medicos add column if not exists retorno_particular text;
alter table medicos add column if not exists retorno_convenio text;
alter table medicos add column if not exists observacoes_atendimento text;
alter table medicos add column if not exists idade_minima text;

comment on column medicos.valor_consulta is 'Valor da consulta particular -- editável pelo médico em "Dados Pessoais"';
comment on column medicos.tempo_consulta is 'Tempo médio de consulta (ex: "30 minutos")';
comment on column medicos.formas_pagamento is 'Formas de pagamento aceitas (texto livre, ex: "Pix, cartão, dinheiro")';
comment on column medicos.politica_cancelamento is 'Política de cancelamento/remarcação';
comment on column medicos.retorno_particular is 'Regra de retorno pra paciente particular (ex: "Grátis em até 30 dias")';
comment on column medicos.retorno_convenio is 'Regra de retorno pra paciente de convênio';
comment on column medicos.observacoes_atendimento is 'Observações gerais sobre o atendimento';
comment on column medicos.idade_minima is 'Idade mínima atendida, se houver restrição';

-- ---------------------------------------------------------------------
-- Dados para Rede Social (Rede Lifemax): telefone PÚBLICO, separado do
-- telefone de login (esse nunca é exibido publicamente -- é a
-- credencial de acesso do médico) + consentimento explícito de
-- divulgação (LGPD).
-- ---------------------------------------------------------------------
alter table medicos add column if not exists telefone_publico text;
alter table medicos add column if not exists rede_lifemax_consentimento boolean not null default false;
alter table medicos add column if not exists rede_lifemax_consentimento_em timestamptz;

comment on column medicos.telefone_publico is 'Telefone de contato exibido no perfil público da Rede Lifemax -- diferente do telefone de login, nunca exibido';
comment on column medicos.rede_lifemax_consentimento is 'Médico marcou "Autorizo a Lifemax a divulgar os dados por mim aqui inseridos" -- LGPD';
