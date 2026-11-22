-- v118: gênero do médico (M ou F) para o quadro "Especialidades" do admin. Opcional: sem preencher, o sistema deduz pelo
-- primeiro nome e o admin pode corrigir na própria tela. Rodar no Neon (SQL Editor); pode rodar mais de uma vez.
alter table medicos add column if not exists genero text;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'medicos_genero_check') then
    alter table medicos add constraint medicos_genero_check check (genero is null or genero in ('M', 'F'));
  end if;
end $$;
