-- v101: contrato digital (Autentique). Rodar no Neon (SQL Editor).
-- exige_contrato: só o médico que se cadastra SOZINHO (auto-cadastro) precisa assinar para reservar.
-- Quem já existia, ou é cadastrado/importado pelo admin, nasce/permanece com false (dispensado).
alter table medicos add column if not exists exige_contrato boolean not null default false;
alter table medicos add column if not exists contrato_autentique_id text;
alter table medicos add column if not exists contrato_link text;
alter table medicos add column if not exists contrato_enviado_em timestamptz;
alter table medicos add column if not exists contrato_assinado_em timestamptz;
-- v107: marca se o documento foi criado em MODO TESTE (sandbox, sem valor jurídico). Ao passar o sistema para o modo
-- definitivo (AUTENTIQUE_SANDBOX=0), contratos de teste deixam de valer e o médico recebe um novo, definitivo.
alter table medicos add column if not exists contrato_sandbox boolean;
-- tudo que existia antes desta coluna foi criado em modo teste:
update medicos set contrato_sandbox = true where contrato_autentique_id is not null and contrato_sandbox is null;
