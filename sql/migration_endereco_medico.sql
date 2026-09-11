-- Endereço completo do médico (CEP, cidade, etc.).
--
-- Paulo pediu pra guardar o endereço completo de cada médico no
-- cadastro (tanto o cadastro feito pelo admin quanto o feito pela
-- secretária em Agenda Fixos). É só informativo por enquanto -- não
-- muda nenhuma regra de negócio, nenhuma cobrança, nenhuma agenda.
--
-- Rode isso no SQL Editor do Neon (ou psql) -- mas o mais simples é rodar sql/INSTALL_ALL.sql direto, que já inclui isso.

alter table medicos add column if not exists endereco_cep varchar(9);
alter table medicos add column if not exists endereco_rua text;
alter table medicos add column if not exists endereco_numero varchar(20);
alter table medicos add column if not exists endereco_complemento text;
alter table medicos add column if not exists endereco_bairro text;
alter table medicos add column if not exists endereco_cidade text;
alter table medicos add column if not exists endereco_estado varchar(2);

comment on column medicos.endereco_cep is 'CEP do médico, só números ou com hífen (ex: 30130-000)';
comment on column medicos.endereco_rua is 'Rua/Avenida do endereço do médico';
comment on column medicos.endereco_numero is 'Número do endereço do médico';
comment on column medicos.endereco_complemento is 'Complemento do endereço (apto, sala, bloco, etc.)';
comment on column medicos.endereco_bairro is 'Bairro do endereço do médico';
comment on column medicos.endereco_cidade is 'Cidade do endereço do médico';
comment on column medicos.endereco_estado is 'UF (sigla do estado) do endereço do médico';
