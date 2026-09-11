# LIFEMAX CONSULTÓRIOS — RESERVA POR HORA

Pacote de produção baseado no código Lifemax enviado, agora com a operação de reserva por hora e a Matriz de Agendamento do administrador.

## Fluxo
Página inicial → Primeiro acesso/Login → Dashboard médico → Escolher consultório → Escolher data/horário → Pagamento → Reserva confirmada.

## Admin
`/admin/login`

`/admin` — dashboard

`/admin/consultorios` — inserir, editar, ativar/desativar, excluir e fotos

`/admin/matriz` — gerar/editar a matriz semanal por consultório

Na matriz:
- verde: disponível para médicos;
- rosa: reservado manualmente pelo administrador;
- cinza: indisponível conforme Semana Padrão;
- azul/teal: reserva confirmada.

## Instalação Neon (banco de dados)
Migrado do Supabase para o Neon (Postgres serverless) em 10/09/2026. A opção mais simples é
executar `sql/INSTALL_ALL.sql` no SQL Editor do novo projeto Neon (ou via `psql`).

O arquivo inclui o `schema.sql`, as migrations existentes e, por último, `migration_matriz_admin_reservas.sql`
— já concatenados numa ordem que respeita as dependências entre eles (gerado por
`sql/build_install_all.py`; não edite `INSTALL_ALL.sql` à mão, edite o `migration_*.sql`
correspondente e rode esse script de novo).

As fotos dos consultórios usam o **Neon Object Storage** (bucket público, ex:
`lifemax-reserva-horas`) em vez do antigo Supabase Storage — veja `INSTALAR.md` para o passo a
passo de criação do bucket e das credenciais.

## Variáveis Render
Obrigatórias:
- DATABASE_URL (connection string do Neon)
- FLASK_SECRET_KEY
- ADMIN_PASSWORD

Recomendadas (fotos dos consultórios):
- NEON_S3_ENDPOINT_URL
- NEON_S3_REGION
- NEON_S3_ACCESS_KEY_ID
- NEON_S3_SECRET_ACCESS_KEY
- NEON_S3_BUCKET

Para pagamento real:
- ASAAS_API_KEY
- ASAAS_ENV=production
- ASAAS_WEBHOOK_TOKEN

## Render
Build:
`pip install -r requirements.txt`

Start:
`python run.py`

## Webhook Asaas
`https://SEU-DOMINIO/webhooks/asaas`

## Segurança
Não coloque DATABASE_URL, as chaves NEON_S3_*, ASAAS_API_KEY ou outras chaves secretas em HTML/JavaScript. Elas devem ficar somente nas variáveis de ambiente do servidor.
