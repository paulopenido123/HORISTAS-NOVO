-- Mudança de comportamento pedida pelo Paulo: o médico precisa aparecer
-- na busca da Rede Lifemax (nome + especialidade) MESMO sem nunca ter
-- ativado a própria conta -- o cadastro básico já existe no banco (veio
-- da planilha dos 74 médicos), então não faz sentido esconder isso
-- atrás de um "aparecer" que só quem já entrou no sistema consegue
-- ligar. Depois que o médico ativa a conta, ele só COMPLETA o perfil
-- (foto, "sobre", endereço) -- não é isso que decide se ele aparece.
--
-- Antes: `visivel_rede_lifemax` (default false) = tinha que ligar pra aparecer.
-- Agora: `rede_lifemax_oculto` (default false) = aparece sempre, a
-- menos que o PRÓPRIO médico peça pra se esconder depois de ativar a
-- conta (opt-out, não opt-in).

alter table medicos add column if not exists rede_lifemax_oculto boolean not null default false;

comment on column medicos.rede_lifemax_oculto is
    'Se true, o médico pediu pra NÃO aparecer na Rede Lifemax -- por padrão todo médico ativo aparece (nome + especialidade), mesmo sem ter ativado a conta ainda';

-- a coluna antiga (visivel_rede_lifemax) fica no banco sem uso a partir
-- de agora -- não precisa apagar, só não é mais consultada pelo sistema.
