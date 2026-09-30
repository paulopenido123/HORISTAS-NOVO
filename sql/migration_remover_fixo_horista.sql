-- Remoção das classificações "fixo" e "horista" (pedido do Paulo em
-- 30/09/2026): todo médico passa a ser "avulso", e as telas/rotinas que só
-- existiam pra fixo/horista (Agenda Fixos, Agenda Horistas) foram
-- removidas do código-fonte. Este script cuida do lado do banco.
--
-- PASSO 1 -- reclassifica todo médico existente como avulso. Depois disso,
-- todo médico enxerga a mesma tela (saldo de horas, "+ Comprar horas",
-- "Reservar consultórios"), sem distinção de vínculo.
update medicos set tipo_vinculo = 'avulso' where tipo_vinculo is distinct from 'avulso';

-- PASSO 2 (OPCIONAL) -- apaga as tabelas que existiam só pra sustentar
-- Agenda Fixos / Módulo Horistas. Nenhuma delas é referenciada em nenhum
-- lugar do código atual (conferido por busca em todo o app/ antes de
-- escrever este script) -- ficaram órfãs desde que o código foi removido.
-- É IRREVERSÍVEL: se algum dia vocês quiserem esses dados de volta
-- (histórico de agendamentos de pacientes de médico fixo/horista, por
-- exemplo), faça um backup antes de rodar esta parte. Comentado de
-- propósito -- descomente linha a linha só o que tiver certeza que quer
-- apagar de vez.

-- drop table if exists chamados_recepcao;
-- drop table if exists agenda_consultas;
-- drop table if exists grade_medico_fixo;
-- drop table if exists empresas;
-- drop table if exists agenda_bloqueios;
-- drop table if exists matriz_liberacao;
-- drop table if exists horas_transacoes;
-- drop table if exists pacotes_horas;

-- NÃO apagar (mesmo que pareçam parecidas): pacotes_horas_avulsas,
-- creditos_transacoes, matriz_template, matriz_reservas_admin,
-- matriz_replicacoes -- essas continuam em uso ativo pelo sistema hoje.
-- Também não mexer em eventos_agenda / consultas_pacientes -- são de um
-- módulo diferente (Agenda Geral/Google Agenda), sem relação com
-- fixo/horista.
