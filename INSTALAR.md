# Lifemax Consultórios — Reserva por Hora (produção)

Pacote baseado no sistema Lifemax existente, com:
- página pública;
- login / primeiro acesso / recuperação de senha;
- dashboard do médico;
- reserva por hora;
- pagamento Asaas já existente;
- painel admin;
- cadastro/edição/exclusão de consultórios;
- upload de fotos no Neon Object Storage;
- Matriz de Agendamento por consultório;
- verde = disponível; rosa = reservado pelo admin/outro profissional; cinza = indisponível; teal = reserva própria.

## Neon (banco de dados)
Migrado do Supabase para o Neon (Postgres serverless) em 10/09/2026, a pedido do Paulo — mesmo
Postgres por baixo, então o schema/migrations continuam os mesmos `.sql`, só sem o SDK do
Supabase por cima.

1. Crie o projeto no [Neon Console](https://console.neon.tech) (região recomendada: a mais
   próxima do seu servidor — este projeto foi criado em AWS US East 2, Ohio).
2. Rode `sql/INSTALL_ALL.sql` no SQL Editor do Neon Console (ou via `psql`) — esse arquivo já
   tem `schema.sql` + todas as migrations concatenadas, na ordem certa. **Não precisa mais rodar
   os `migration_*.sql` um por um** (era assim no Supabase); se algum dia precisar regenerar esse
   arquivo depois de editar uma migration, rode `python3 sql/build_install_all.py`.
3. Copie a **connection string** do projeto (Neon Console → seu projeto → *Connect*) — é o valor
   de `DATABASE_URL` (veja abaixo).
4. Ative o **Object Storage** do projeto (Neon Console → seu projeto → *Object Storage*) e crie
   um bucket com visibilidade **Public** (usado neste pacote: `lifemax-reserva-horas`) — é o que
   substitui o antigo bucket `consultorios` do Supabase Storage para as fotos dos consultórios.
   Gere as credenciais de acesso (*Object Storage → Credentials*) — são os valores de
   `NEON_S3_ACCESS_KEY_ID`/`NEON_S3_SECRET_ACCESS_KEY` abaixo.
5. Se você já tinha dados reais no Supabase (médicos/consultórios/reservas) e quer trazê-los para
   o Neon, veja a seção **Migrando dados reais do Supabase**, mais abaixo.

## Render / servidor
Comando de build:
`pip install -r requirements.txt`

Comando de start:
`python run.py`

## Variáveis obrigatórias
- `DATABASE_URL` (connection string do Neon)
- `FLASK_SECRET_KEY`
- `ADMIN_PASSWORD`

## Variáveis recomendadas (fotos dos consultórios)
- `NEON_S3_ENDPOINT_URL`
- `NEON_S3_REGION`
- `NEON_S3_ACCESS_KEY_ID`
- `NEON_S3_SECRET_ACCESS_KEY`
- `NEON_S3_BUCKET` (padrão: `lifemax-reserva-horas`)

Sem essas 5, o resto do sistema funciona normalmente — só o upload de foto de consultório mostra
um erro amigável até serem configuradas.

Para pagamentos reais:
- `ASAAS_API_KEY`
- `ASAAS_ENV=production`
- `ASAAS_WEBHOOK_TOKEN`

Para login Google, preencha as variáveis Google já existentes no `.env.example`.

## Webhook Asaas
Mantenha a rota existente:
`https://SEU-DOMINIO/webhooks/asaas`

Configure o token do webhook igual a `ASAAS_WEBHOOK_TOKEN`.

## Migrando dados reais do Supabase (opcional)
Como Supabase e Neon são os dois Postgres por baixo, dá para copiar os dados com as ferramentas
padrão do Postgres (`pg_dump`/`psql`) — sem precisar reexportar/reimportar manualmente tabela por
tabela:

1. No Supabase: Project Settings → Database → copie a "Connection string" (modo *Session*, porta
   5432 — não use o *Connection pooling* na 6543 para isso).
2. Rode, do seu computador (com `pg_dump` instalado — vem com o PostgreSQL):
   `pg_dump --no-owner --no-privileges --data-only -f dados_supabase.sql "CONNECTION_STRING_DO_SUPABASE"`
   (`--data-only` porque o schema já foi criado no passo 2 acima, via `INSTALL_ALL.sql`).
3. Restaure no Neon:
   `psql "CONNECTION_STRING_DO_NEON" -f dados_supabase.sql`
4. As fotos que já estavam no bucket `consultorios` do Supabase Storage precisam ser baixadas e
   reenviadas para o bucket novo do Neon Object Storage — e as URLs salvas na coluna `fotos` da
   tabela `consultorios` atualizadas para apontar para o novo endereço. Fale com quem estiver
   fazendo a migração técnica se precisar de ajuda nesse passo específico.

## Importante
Este pacote não contém nenhuma chave real. Preencha as variáveis no Render/`.env`.
Não publique `DATABASE_URL` nem as chaves `NEON_S3_*` no navegador.
