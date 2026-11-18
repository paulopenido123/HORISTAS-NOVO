-- v102: duas unidades (endereços). Rodar no Neon (SQL Editor). Idempotente.
-- Todos os consultórios que já existem ficam na unidade "Funcionários"; os novos do Estoril o admin cadastra em Admin > Consultórios.
create table if not exists unidades (
    id uuid primary key default uuid_generate_v4(),
    nome text not null unique,
    endereco text not null,
    referencia text,
    ordem integer not null default 0,
    ativo boolean not null default true
);
alter table unidades enable row level security;

insert into unidades (nome, endereco, referencia, ordem) values
  ('Funcionários', 'Rua Gonçalves Dias, 82', null, 1),
  ('Estoril', 'Av. Barão Homem de Melo, 4494, Sl 1403', 'Em frente à Avantgarde Motors', 2)
on conflict (nome) do nothing;

alter table consultorios add column if not exists unidade_id uuid references unidades(id);
update consultorios set unidade_id = (select id from unidades where nome = 'Funcionários') where unidade_id is null;
create index if not exists idx_consultorios_unidade on consultorios (unidade_id);

-- v104: fotos da recepção de cada endereço (o admin envia em Admin > Consultórios > "Fotos da recepção") e correção do nome da loja em frente ao Estoril.
alter table unidades add column if not exists fotos text[] not null default '{}';
update unidades set referencia = 'Em frente à Avantgarde Motors' where nome = 'Estoril' and referencia is distinct from 'Em frente à Avantgarde Motors';
