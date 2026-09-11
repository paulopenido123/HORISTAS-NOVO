-- Endereço padrão da Lifemax, salvo como CONFIGURAÇÃO permanente (não
-- mais uma ação em lote manual) -- pedido do Paulo: o pino do mapa
-- tem que aparecer pra QUALQUER médico sem endereço próprio, agora e
-- no futuro (um médico novo, cadastrado daqui a 6 meses, também tem
-- que aparecer no mapa sem precisar de nenhuma ação manual do admin).
--
-- Guardado na mesma tabela `precos` de sempre (linha única, já usada
-- pra preço de hora/turno e pra config de IA).

alter table precos add column if not exists endereco_padrao_cep text;
alter table precos add column if not exists endereco_padrao_rua text;
alter table precos add column if not exists endereco_padrao_numero text;
alter table precos add column if not exists endereco_padrao_complemento text;
alter table precos add column if not exists endereco_padrao_bairro text;
alter table precos add column if not exists endereco_padrao_cidade text;
alter table precos add column if not exists endereco_padrao_estado text;
alter table precos add column if not exists endereco_padrao_latitude numeric(9,6);
alter table precos add column if not exists endereco_padrao_longitude numeric(9,6);

comment on column precos.endereco_padrao_rua is 'Endereço padrão da Lifemax (ex: prédio da sede) -- usado automaticamente no mapa/perfil de QUALQUER médico que ainda não tem endereço próprio cadastrado';
