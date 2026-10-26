# Lifemax "Reserva de Horas" — Descritivo completo do sistema

> **Para quem vai ler (outro Claude):** este documento descreve, de ponta a ponta, um sistema Flask
> independente que será **migrado/adaptado para dentro de um sistema-mãe** (o projeto Flask do
> Lifemax/Lifedoctor — `lifemax-assistant`). O dono é **Paulo Penido** (não técnico; comunicação e
> código em **português do Brasil**). Leia tudo antes de mexer. Onde digo **[CONFIRMAR NO MÃE]** é um
> ponto que só dá pra decidir olhando o código/banco do sistema-mãe.
>
> Versão descrita: `lifemax_v32` (19–20/10/2026). Fonte da verdade = o código; os comentários do código
> (em português) trazem a história de cada decisão, com data e "pedido do Paulo".

---

## 1. O que o sistema faz (visão de negócio)

A **Lifemax/Biomax** é um coworking médico (~62 consultórios, em andares). Médicos **alugam consultório por
hora** sem contrato fixo. Fluxo de negócio:

1. O médico se cadastra sozinho (telefone + senha), aceita o **contrato digital** e completa o cadastro.
2. **Compra horas** em pacotes fechados (6h/12h/24h/48h) pagando por **PIX ou cartão (Asaas)**. O dinheiro vira
   **saldo** na carteira dele (`saldo_creditos`, em R$), exibido sempre em **horas**.
3. **Reserva consultórios** numa grade (dia × consultório × horário), debitando o saldo.
4. Cancela com **reembolso das horas** se faltar ≥ 12h para o início; com menos de 12h cancela **sem reembolso**.
5. Associa **pacientes** às reservas (agenda do médico) e pode mandar e-mail de confirmação ao paciente.
6. O **admin** (Paulo/equipe) cadastra consultórios e fotos, gera a **Matriz** (período em que a grade está aberta e
   horários reservados pelo admin), ajusta saldos, vê relatórios, emite NF (stub), envia e-mails em lote.

**Todo médico é "avulso".** Os conceitos antigos "fixo" e "horista" (e as telas Agenda Fixos / Agenda Horistas) foram
**removidos** em 30/09/2026. A coluna `medicos.tipo_vinculo` ainda existe e vale sempre `'avulso'`.

**IA foi removida** em 19/10/2026 (carteira de IA, compra de uso de IA, controle de IA, transferência entre carteiras,
chaves Anthropic/OpenAI/Gemini). Restam colunas/tabelas de IA no banco **sem uso** (ver §12). O sistema-mãe é quem tem a
IA/Dora.

---

## 2. Stack e execução

| Item | Detalhe |
|---|---|
| Linguagem/Framework | Python 3.11, **Flask 3.0.3** (application factory em `app/__init__.py`, `create_app()`) |
| Servidor | `gunicorn` (produção, Render), `run.py` usa `socketio.run(...)` localmente |
| Banco | **PostgreSQL (Neon)** via `psycopg2-binary`, **sem ORM**. Camada `app/services/pg_query.py` emula a API encadeada do Supabase (`get_client().table("x").select().eq().execute().data`) — **o código inteiro foi escrito nesse estilo Supabase** |
| Storage | Fotos de consultórios no **Neon Object Storage (S3-compatível)** via `boto3` (`neon_storage.py`) |
| Pagamento | **Asaas** (PIX + cartão) via `requests` (`asaas_client.py`) + webhook |
| E-mail | SMTP (Gmail com senha de app etc.) via `email_service.py` |
| WhatsApp | `whatsapp_client.py` (Meta Cloud API) — usado só para avisos a admins/médico (boas-vindas, saldo baixo) |
| Agenda Google | `google_calendar_service.py` (opcional; ver §11) |
| Segurança web | `flask-wtf` (CSRF), `flask-limiter` (rate limit em memória), cookies HttpOnly/SameSite=Lax, sessão permanente 8h |
| Front | **Jinja2 server-side**, CSS e JS **inline** em cada template, `fetch()` para APIs JSON. Sem framework JS. PWA mínimo (`static/manifest.json`, `service-worker.js`) |
| PDF | `reportlab` (contrato em PDF) — *voltou ao requirements.txt na v32; havia sido removido por engano* |
| Timezone | Brasília fixo (`utcnow() - 3h`); não guarda fuso por médico |

`requirements.txt`: flask, requests, python-dotenv, psycopg2-binary, boto3, gunicorn, flask-socketio, google-auth(+oauthlib,
api-client), flask-limiter, flask-wtf, tzdata, reportlab.

`flask-socketio` está registrado mas **não há nenhum evento/handler** (resquício; pode ser descartado na adaptação).

`painel.py` (Tkinter) é um painel gráfico para o Paulo configurar `.env`/instalar/rodar **localmente no Windows** — **não faz
parte do sistema web**; ignorar na migração. `scripts_migracao/` tem importação de horistas históricos do sistema maior (uso
único); ignorar.

---

## 3. Estrutura de pastas

```
run.py                         # entrypoint (socketio.run)
painel.py                      # GUI Tkinter local (ignorar)
requirements.txt  .env.example
app/
  __init__.py                  # create_app: config, blueprints, CSRF, /, /consultorios, /health
  config.py  extensions.py     # Config (env vars) | socketio, limiter, csrf
  routes/
    auth.py                    # /primeiro-acesso /login /logout /esqueci-senha /redefinir-senha /confirmar-email/<t>
    turnos.py                  # /turnos + /api/turnos/* (grade de reserva do médico)
    medico_painel.py           # /painel, /painel/agenda, /painel/dados-pessoais, /painel/pacientes, /api/creditos/*, /api/pacientes*, /api/reservas/*, /api/perfil/*
    admin.py                   # /admin/* (dashboard, clientes, consultórios, fotos, horas, matriz, relatórios, NF)
    termos.py                  # /termos (aceite do contrato), /contrato/baixar (PDF)
    api_dora.py                # /api/dora/* (API p/ o WhatsApp "Dora", chave X-API-Key)
    webhooks_asaas.py          # POST /webhooks/asaas
  services/
    supabase_client.py         # "db": consultórios, reservas, médicos, grade, fotos, aceite de termo... (nome histórico; usa PgClient)
    pg_query.py                # emulador PostgREST→SQL (QueryBuilder)
    reserva_service.py         # **núcleo**: reservar_turno, reservar_por_hora, cancelar, pacientes da reserva, pós-reserva
    creditos_service.py        # **núcleo**: preços/pacotes, saldo, registrar_transacao, pagamentos, estatísticas
    template_service.py        # grade de horários, bloqueios (Semana Padrão), data_tem_matriz_gerada
    asaas_client.py  nfe_service.py  email_service.py  whatsapp_client.py  google_calendar_service.py
    neon_storage.py  pacientes_service.py  secretarias_service.py  modulos_service.py
    recuperacao_senha_service.py  auth_service.py  termo_service.py  contrato_service.py  pdf_service.py
    relatorios_service.py  notificacao_saldo.py  notificacao_boas_vindas.py  notificacoes_operacionais_service.py
    telefone_utils.py
  templates/                   # 24 HTMLs (ver §9)
  static/                      # icons/, images/ (logo), js/socket.io.min.js, manifest.json, service-worker.js, favicon.ico
sql/
  INSTALL_ALL.sql              # instalação completa (gerado por build_install_all.py a partir das migration_*.sql)
  schema.sql + migration_*.sql # histórico de migrações (idempotentes)
```

---

## 4. Modelo de dados (tabelas realmente usadas)

> `sql/INSTALL_ALL.sql` contém também tabelas do **sistema maior** (prontuários, contabilidade, IA, vídeo etc.) por
> herança — **não são usadas por este código**. Só as abaixo importam.

**`medicos`** — id (uuid), nome, telefone (E.164 sem `+`, ex. `5531999999999`, **único de fato**), email, email_confirmado,
especialidade, crm, cpf_cnpj, data_nascimento, endereço (`endereco_cep/rua/numero/complemento/bairro/cidade/estado`),
convenios (text; lista), `senha_hash` (Werkzeug), `saldo_creditos` (numeric R$ — **a carteira**), `saldo_horas` (legado, não
é a fonte), `alerta_saldo_baixo_enviado`, `autorizado` (bool; default true), `ativo`, `assistente_ativo`, `tipo_vinculo`
(sempre `'avulso'`), `termo_aceito/_em/_ip/_versao`, `is_beta_tester`, campos de atendimento (`valor_consulta`,
`tempo_consulta`, `formas_pagamento`, `politica_cancelamento`, `retorno_*`, `observacoes_atendimento`, `idade_minima`,
`telefone_publico`), campos de "rede pública" (`visivel_rede_lifemax`, `bio_publica`, `latitude/longitude`...),
`google_*` (tokens do Google Calendar), `foto_perfil_url`.

**`consultorios`** — id, nome (ordenação "natural": "Sala 2" < "Sala 10"), descricao, `preco_periodo` (legado), `fotos text[]`
(URLs), `ativo`, `andar` (derivado do nome via `andar_a_partir_do_nome`).

**`reservas`** — id, consultorio_id, medico_id, `data` (date), `periodo` (`manha`/`tarde`/`noite`, **só nos turnos**),
`tipo_reserva` (turno | hora), `hora_inicio`, `hora_fim`, `quantidade_horas`, `status` (`pendente` | `confirmada` | `cancelada`; **toda reserva nasce `pendente` e este pacote nunca chama `confirmar_reserva`** — `pendente` já conta como reserva ativa em todas as consultas; só `cancelada` libera o horário),
`criado_por_admin`, `cancelado_por_admin`, `cancelado_em`, `google_evento_id`, `hora_confirmada` (text, edição pelo médico),
`paciente_id`, `tryout` (legado), `intervalo_ocupado` (**tsrange**; usada para impedir sobreposição no banco —
ver `sql/migration_protecao_conflito.sql`).

**`creditos_transacoes`** — extrato: id, medico_id, `tipo` (`compra` | `consumo` | `ajuste`), `valor` (+ crédito / − consumo),
`saldo_apos`, descricao, reserva_id, pagamento_id, `quantidade_horas`, `categoria` (`horas`), `carteira` (hoje só `salas`).

**`pagamentos_pix`** — cobranças Asaas (PIX e cartão, nome histórico): medico_id, asaas_payment_id, asaas_customer_id, valor,
`valor_salas`, `horas_pacote`, `parcelas`, `forma_pagamento`, status (`pendente`/`pago`), qr_code_base64, copia_e_cola,
invoice_url, pago_em, `nota_fiscal_status/_numero/_url/_emitida_em/_enviada_em`. (`valor_ia` é coluna morta.)

**`pacotes_horas_avulsas`** — catálogo vendido: `horas` (6/12/24/48), `valor_hora`, `valor_total`, `max_parcelas`, `ativo`.
Seed: 6h R$65,00/h (R$390) 1x · 12h R$58/h (R$696) 1x · 24h R$49/h (R$1.176) até 2x · 48h R$45/h (R$2.160) até 3x.
*(Não confundir com a tabela antiga `pacotes_horas`, só lista de quantidades.)*

**`precos`** — linha única de configuração: `horas_minimas` (mínimo de horas por reserva), `endereco_padrao_*` (endereço da
Lifemax usado no e-mail ao paciente). Colunas `preco_hora_1/2/3`, `preco_turno`, `ia_*` são **legado, não lidas**.

**Matriz / Semana Padrão:**
- `matriz_template` (consultorio_id, dia_semana 0=dom…6=sáb, horario) — **padrão semanal de horários que o admin quer deixar
  "reservados"** (marca a matriz).
- `matriz_reservas_admin` (consultorio_id, data, horario, descricao) — **bloqueios/reservas do admin em datas reais** (resultado da replicação).
- `matriz_replicacoes` (tipo `periodo`/`mes`, data_inicio, data_fim, aplicados, conflitos) — **registra quais períodos o admin já
  "gerou"**. **O médico só consegue reservar datas cobertas por alguma replicação.**
- `template_semanal_bloqueios` (consultorio_id, dia_semana, hora_inicio) — bloqueios da "Semana Padrão"; hoje **sem tela de edição**
  (a função `alternar_bloqueio` existe mas ninguém a chama); a regra efetiva vem do código (§6.4).

**Pacientes:** `pacientes` (por médico: dados pessoais, responsável etc.), `reserva_pacientes` (N:N reserva↔paciente, com
`email_enviado_em`).
**Outras:** `secretarias` (nome, telefone, senha_hash, email, ativo — **papel existe no `auth_service` mas as rotas de
secretária NÃO estão neste pacote**), `tokens_recuperacao_senha` (token **hasheado sha256**, tipo, usuario_id, expira_em, usado,
`contexto`: recuperação / primeiro acesso / confirmar e-mail), `modulos` (cards do painel; `modulos_service`), `funcionarios`
(e-mails que recebem aviso de reserva), `agenda_*`/outros (sem uso aqui).

> Atenção ao `pg_query`: joins PostgREST (`select("*, medicos(nome)")`) só funcionam se a **coluna FK estiver no select**
> (ex.: `medico_id`). Isso já causou bug (nome vazio). Se o sistema-mãe usa o Supabase real, esse detalhe desaparece.

---

## 5. Autenticação e papéis

- **Médico:** login por **telefone + senha** (`/login`, rate-limit 8/min). `normalizar_telefone` guarda só dígitos e prefixa
  DDI `55` se vier com 10/11 dígitos; `telefone_sem_ddi` é só para exibição. Sessão Flask: `session["medico_id"]`.
  Decoradores: `requer_login_medico`, `requer_termo_aceito` (gate do contrato).
- **Cadastro (`/primeiro-acesso`)** em etapas: informa telefone → se não existe, **auto-cadastro** (nome, especialidade, senha ≥ 6) e
  já entra; se existe sem senha, define a senha; se já tem senha, manda ao login. Médico novo nasce `autorizado=True`; o admin
  é avisado por WhatsApp e e-mail (`ADMIN_EMAIL`, `ADMIN_PHONE*`).
- **Esqueci a senha:** por e-mail (`/esqueci-senha` → link com token → `/redefinir-senha`). Token guardado só como hash, com validade.
  O mesmo mecanismo serve ao "link de primeiro acesso" que o admin envia e à **confirmação de e-mail** (⭐ na lista do admin).
- **Admin:** **senha única** em `ADMIN_PASSWORD` (env), `session["admin"]`; decorador `requer_admin` / `_admin`. Sem usuário, sem
  recuperação.
- **Dora (WhatsApp):** `X-API-Key` == `DORA_API_KEY` (servidor→servidor, rota isenta de CSRF). Sem chave configurada, tudo é recusado.
- **Webhook Asaas:** header `asaas-access-token` == `ASAAS_WEBHOOK_TOKEN` (isento de CSRF).
- **Privacidade:** o médico logado **nunca** vê o nome de outro médico na grade (`r["medicos"] = None` se `medico_id` ≠ o da
  sessão). As rotas de reserva **ignoram qualquer `medico_id` vindo do navegador** — usam sempre o da sessão. O admin vê tudo.

---

## 6. Regras de negócio (o coração do sistema)

### 6.1 Grade de horários (constante em todo o sistema)
11 horários por dia, em hora cheia, com pausa de almoço (12–13h) e limpeza (17–17:30):
- **manhã:** 08:00 09:00 10:00 11:00 · **tarde:** 13:00 14:00 15:00 16:00 · **noite:** 17:30 18:30 19:30 (termina 20:30).
- Turnos (`PERIODOS_HORARIOS`): manhã 08:00–12:00, tarde 13:00–17:00, noite 17:30–20:30.
- `dia_semana`: 0=domingo … 6=sábado (igual `Date.getDay()` do JS).

### 6.2 Dois tipos de reserva
- **Por hora** (`reservar_por_hora(medico, consultorio, data, hora_inicio, quantidade_horas)`): N horas **seguidas** a partir de um horário.
  Respeita `precos.horas_minimas`.
- **Por turno** (`reservar_turno`): manhã/tarde/noite inteiros (4h/4h/3h).
Ambas exigem, **nesta ordem**: (1) cadastro completo e médico autorizado (admin ignora); (2) data/hora **não passada**; (3) a
**Matriz gerada** para aquela data (admin ignora); (4) horários **não bloqueados** na Semana Padrão; (5) sem conflito com
`matriz_reservas_admin`; (6) **saldo suficiente**; (7) sem conflito no **Google Agenda** do médico (se conectado; timeout 2,5s;
não bloqueia, só sinaliza); (8) inserção da reserva (o banco impede sobreposição via `intervalo_ocupado`, sem corrida) →
(9) **débito** no extrato → (10) pós-reserva **em segundo plano** (thread): evento no Google Agenda, e-mail aos `funcionarios`, e-mail de
confirmação ao médico (com saldo), alerta de saldo baixo. Falha de e-mail **nunca** derruba a reserva já feita.

### 6.3 Preço e saldo
- O saldo é **monetário** (`saldo_creditos`, R$), mas a UI mostra **horas**. `saldo_em_horas_medico` = `saldo // preço da hora avulsa`.
- **Preço da hora avulsa** = `valor_hora` do **menor pacote ativo** (hoje o de 6h = R$65). Reservar N horas debita `N × esse preço`
  (comprar pacote maior sai mais barato; reservar direto sai "no cheio"). Não existe mais preço escalonado nem preço de turno fixo.
- Erros de saldo falam em **horas** ("você tem Xh e precisa de Yh. Compre mais horas").
- **Cortesia/tryout está DESATIVADA** (`TRYOUT_TOTAL = 0`; `tryout_restante()` sempre 0). Toda reserva debita.
- **Toda movimentação de saldo passa por `creditos_service.registrar_transacao`** (atualiza `medicos.saldo_creditos` + insere extrato; se o
  saldo sobe, rearma o alerta de saldo baixo). Nunca alterar saldo direto.

### 6.4 Bloqueios fixos (código, não banco)
`template_service._bloqueios_fixos_fim_de_semana`: **domingo inteiro bloqueado**; **sábado só manhã** (tarde e noite bloqueadas) — aplicado a
todos os consultórios (cache de 60s da lista de consultórios). Somam-se às linhas de `template_semanal_bloqueios`.

### 6.5 Cadastro mínimo para reservar (fonte única: `_CAMPOS_OBRIGATORIOS_PARA_RESERVAR`)
telefone, e-mail, especialidade, CPF/CNPJ, CEP, rua, número, bairro, cidade, UF. (Complemento e **data de nascimento NÃO bloqueiam**.)
Se faltar algo: `DadosPessoaisIncompletosError(faltando)` → a tela leva o médico a "Meus dados". `autorizado=False` é um **bloqueio manual
excepcional** do admin (`NaoAutorizadoError`).

### 6.6 Cancelamento e reembolso (`_efetivar_cancelamento`)
- Médico cancela a própria reserva; admin cancela qualquer uma (`cancelar_reserva_admin`).
- Faltam **≥ 12h** do início → **reembolso** do valor **exato da transação de consumo original** (protege contra mudança de preço); lança
  transação `ajuste` positiva "Reembolso por cancelamento". Faltam **< 12h** → cancela **sem reembolso**. Vale igual para admin (o reembolso vai ao médico dono).
- Cancela evento do Google Agenda e manda e-mail de confirmação de cancelamento em segundo plano.

### 6.7 Compra de horas (Asaas)
1. Médico escolhe um **pacote** (`pacote_horas`) e **PIX** (`/api/creditos/comprar`) ou **cartão** com `parcelas ≤ max_parcelas`
   (`/api/creditos/comprar-cartao`). Exige **CPF/CNPJ** (cria/recupera cliente Asaas: `criar_ou_obter_cliente`).
2. Cria cobrança Asaas, grava em `pagamentos_pix` com `status=pendente`, `horas_pacote`, `valor_salas`. PIX devolve QR + copia-e-cola;
   cartão devolve `invoice_url` (checkout hospedado do Asaas).
3. **Confirmação:** o webhook `/webhooks/asaas` (eventos `PAYMENT_RECEIVED`/`PAYMENT_CONFIRMED`) **e** o polling `/api/creditos/status/<id>` chamam a
   mesma função **idempotente** `confirmar_pagamento_e_creditar`: marca pago, `registrar_transacao(tipo="compra", valor=valor_salas,
   quantidade_horas=horas_pacote)`, manda **recibo por e-mail**; se for o **primeiro pagamento** do médico, ativa `assistente_ativo`,
   manda boas-vindas por WhatsApp e avisa os admins.
4. **NF-e/NFS-e:** `nfe_service.emitir_nf` é **stub** — sempre levanta `NfeNaoConfiguradaError` até haver certificado A1 + provedor
   (`NFE_*`). A tela Relatórios mostra "Transações ainda não faturadas" com botão "Emitir NF" que hoje só exibe o aviso.

### 6.8 Matriz do admin ("Gerar Matriz")
Duas fases:
1. **Padrão semanal** (`matriz_template`): o admin marca, por consultório × dia da semana × horário, o que fica **reservado pelo admin**. Não permite marcar
   o que já está bloqueado pela Semana Padrão.
2. **Replicar** (`_aplicar_template_no_periodo`, "por período" ou "por mês"): aplica o padrão em datas reais, escrevendo `matriz_reservas_admin` e
   registrando em `matriz_replicacoes`. Regras: (a) cria o que falta; (b) **libera** horários que uma replicação anterior marcou mas saíram do
   padrão; (c) se uma célula alvo colide com **reserva real de médico**, devolve `precisa_confirmar` com a lista de conflitos; só com
   `confirmar=true` as reservas dos médicos são **canceladas** (com a regra normal de reembolso) e o bloqueio é aplicado.
**Consequência-chave:** sem replicação cobrindo a data, o médico **não consegue reservar** (`MatrizNaoGeradaError`). "Visualizar agenda" mostra a
grade completa com nomes (`/admin/api/matriz/grade`).

### 6.9 Pacientes na reserva
O médico cadastra pacientes (`/painel/pacientes`), associa **1 paciente principal** (`reservas.paciente_id`) e/ou **vários** (`reserva_pacientes`) a uma
reserva, define `hora_confirmada` e pode enviar e-mail de confirmação ao paciente (usa o endereço padrão da Lifemax de `precos`). Cada médico só vê os seus.

### 6.10 Alertas de saldo baixo
`notificacao_saldo`: após cada reserva, se o saldo não paga a reserva mínima, avisa (WhatsApp, com e-mail de fallback) **uma vez**
(`alerta_saldo_baixo_enviado`, rearmado quando o saldo sobe). Limite por env `LIMITE_ALERTA_SALDO_BAIXO` (padrão 100,00).

### 6.11 Contrato digital
Todo médico precisa **aceitar o contrato** (`/termos`) antes de usar o painel; guarda data/hora, IP e versão
(`contrato_service.CONTRATO_VERSAO`). Texto integral em `contrato_service.py` ("Contrato de Prestação de Serviços de Coworking e Cessão de
Infraestrutura — Horas — modelo BIOMAX"). `/contrato/baixar` gera o PDF (reportlab) com os dados do aceite.

---

## 7. Rotas (todas as registradas)

**Públicas:** `GET /` (home), `GET /consultorios` (carrossel de fotos), `GET /health`, `GET|POST /login`, `/logout`, `/primeiro-acesso`, `/esqueci-senha`,
`/redefinir-senha`, `GET /confirmar-email/<token>`.

**Médico (login + termo aceito):** `GET /painel` (saldo, comprar horas, histórico, minha agenda, botões), `/painel/agenda`, `/painel/dados-pessoais`,
`/painel/pacientes`, `/turnos` (grade de reserva), `GET|POST /termos`, `GET /contrato/baixar`.
APIs: `POST /api/creditos/comprar`, `/api/creditos/comprar-cartao`, `GET /api/creditos/status/<pagamento_id>`;
`GET /api/turnos/grade|medicos|precos`, `POST /api/turnos/reservar|reservar-horas|cancelar`;
`POST /api/perfil/dados-pessoais|cpf-cnpj|crm`; `POST /api/pacientes`, `/api/pacientes/<id>`; `POST /api/reservas/<id>/paciente|hora-confirmada|pacientes-agendados`
(+ `/<paciente_id>/remover`, `/<paciente_id>/enviar-email`).

**Admin (`/admin`, senha única):** `/admin` (dashboard), `/admin/login|logout`, `/admin/clientes` (lista) · `/novo` · `/<id>` (visualizar) · `/<id>/editar` ·
`/<id>/ajustar-saldo` · `/<id>/autorizacao` · `/<id>/enviar-link`; `POST /admin/api/clientes/enviar-email-lote` e `/enviar-link-lote`;
`/admin/consultorios` (+ `/<id>/editar|excluir|fotos|fotos/excluir`); `/admin/horas` (+ `/endereco-padrao`); `/admin/matriz`, `/admin/matriz/visualizar-agenda`,
`/admin/api/matriz/template|template/toggle|grade|replicar-periodo|replicar-mes|intervalo-criado|relatorio`; `/admin/relatorios` (+ `POST /admin/pagamentos/<id>/emitir-nf`).

**Integrações:** `POST /webhooks/asaas`; `GET /api/dora/medico?telefone=`, `GET /api/dora/consultorios`, `GET /api/dora/disponibilidade`, `POST /api/dora/reservar`
(todas com `X-API-Key`; reaproveitam 100% `reserva_service`, então o resultado é idêntico ao do site).

---

## 8. Integrações externas e variáveis de ambiente

**Obrigatórias (`Config.validate`):** `DATABASE_URL`, `FLASK_SECRET_KEY`, `ADMIN_PASSWORD`.
**Opcionais (o sistema degrada com elegância quando faltam):**
`ASAAS_API_KEY`, `ASAAS_ENV` (`sandbox`|`production`), `ASAAS_WEBHOOK_TOKEN` · `SMTP_HOST/PORT/USER/PASSWORD`, `EMAIL_FROM`, `ADMIN_EMAIL` (vírgulas) ·
`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_API_VERSION`, `ADMIN_PHONE`, `ADMIN_PHONE_PATRICIA` ·
`DORA_API_KEY` · `NEON_S3_ENDPOINT_URL/REGION/ACCESS_KEY_ID/SECRET_ACCESS_KEY/BUCKET` · `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` ·
`NFE_A1_CERTIFICADO_PATH/SENHA`, `NFE_CNPJ_EMISSOR` · `FORCE_HTTPS_COOKIES` · `LIMITE_ALERTA_SALDO_BAIXO` · `PORT`, `DEBUG`.
Há também `ENCRYPTION_KEY`, `GOOGLE_REVIEW_URL`, `PLANILHA_MEDICOS_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` no `config.py` — **sem uso neste pacote**.

Padrão de robustez: e-mail/WhatsApp/Google/NF não configurados → registram no log e **não quebram** o fluxo principal.

---

## 9. Telas (templates) e UX

- `home_reserva_horas.html` (home) · `consultorios_publicos.html` (carrossel de fotos) · `login.html`, `primeiro_acesso.html`, `esqueci_senha.html`,
  `redefinir_senha.html`, `confirmar_email.html`, `termo_uso.html`.
- **Painel do médico** `painel_medico.html`: faixa azul-escura no topo com logo, título "Área do cliente — Seu painel Lifemax", **Saldo de horas** (valor ao lado do
  rótulo) e botões centralizados **[+ Comprar horas] [Reservar consultórios] [Meus dados] [LifeDoctor]** (o LifeDoctor abre
  `https://www.lifedoctor.com.br/primeiro-acesso` em nova aba, com o logo hotlinkado e fallback só-texto); "Minha agenda" (reservas de hoje em diante, ordem crescente, horários
  marcados em verde claro, botão Cancelar preto/branco); bloco **"Visão geral da conta"** (2 células: Saldo para reserva de salas + Meu perfil); modal de compra de horas
  (pacote → PIX ou cartão → QR/checkout, com polling); histórico de transações; notas fiscais.
- `turnos.html` (grade de reserva, fonte grande p/ celular, número do consultório com botão "ver foto", horário 08:00 sem corte), `minha_agenda.html`,
  `painel_dados_pessoais.html` ("Meus dados" — tela única de contato, endereço e atendimento), `painel_pacientes.html`.
- **Admin:** `admin_login`, `admin_dashboard`, `admin_clientes` (lista, e-mail em lote, 5 colunas), `admin_cliente_form`, `admin_cliente_visualizar` (dados, saldo, **ajuste de saldo**,
  histórico), `admin_consultorios`, `admin_fotos`, `admin_horas` (vendidas/utilizadas/saldo na praça + endereço padrão), `admin_matriz`, `admin_matriz_visualizar_agenda`,
  `admin_relatorios` (Agendamentos, Transações, faturadas / não faturadas).
- Todo template tem `<head>` com favicon/ícone novo do Lifemax (duas pilhas de barras verde-azulado/oliva); logo novo em `static/images/logo.png` (e `logo-light.png`,
  usado no topo azul dentro de caixa branca). Cores da marca: verde-azulado `#028B8A`, oliva `#A0AA73`, azul-escuro `#082A3D`.
- Padrão de front: HTML com Jinja + `fetch()` enviando o token CSRF (`X-CSRFToken`, via `<meta name="csrf-token">`).

---

## 10. Fluxos principais passo a passo

**A. Novo médico → primeira reserva:** `/primeiro-acesso` (telefone, nome, especialidade, senha) → entra → `/termos` (aceite) → `/painel` → "Meus dados" (completar campos
obrigatórios) → "+ Comprar horas" (pacote + PIX/cartão) → webhook credita + e-mail recibo (+ boas-vindas WhatsApp no 1º pagamento) → "Reservar consultórios" (`/turnos`):
escolhe consultório/dia/horário → `POST /api/turnos/reservar-horas` → débito, e-mails, Google Agenda → aparece em "Minha agenda".

**B. Cancelamento:** `POST /api/turnos/cancelar` → regra das 12h (§6.6) → saldo e e-mail.

**C. Admin prepara um mês:** `/admin/matriz` → marca padrão semanal → "Replicar por mês" → (se conflito, confirma sobreposição) → só então os médicos conseguem reservar aquele mês.

**D. Dora (WhatsApp):** `GET /api/dora/medico` (é médico?) → `/consultorios` (fotos) → `/disponibilidade` → `POST /api/dora/reservar` (mesmo motor do site).

---

## 11. Pontos de atenção, legados e dívidas conhecidas

1. **Google Agenda:** o serviço (checar conflito, criar/cancelar evento) funciona **se o médico já tiver conectado** a conta, mas **as rotas OAuth (`/google/connect|callback`) e a
   tela para conectar NÃO existem neste pacote** (ficaram no sistema-mãe). **[CONFIRMAR NO MÃE]** — provavelmente o mãe já tem; reaproveitar.
2. **Secretárias:** `secretarias_service`/`auth_service` têm helpers, mas **não há rotas/telas de secretária aqui**.
3. **NF-e:** stub (§6.7). Nenhuma nota é emitida de verdade.
4. **Semana Padrão:** sem tela; só vale a regra fixa de fim de semana (+ linhas legadas).
5. **`flask-socketio`:** sem uso. **`painel.py`**, **`scripts_migracao/`**: ignorar.
6. **Tryout/cortesia:** desativada (constante 0). **Colunas legadas** em `precos` (`preco_hora_*`, `preco_turno`, `ia_*`), `medicos` (`saldo_ia`, `alerta_saldo_ia_baixo_enviado`, `saldo_horas`,
   `horista_*`, `ia_trial_creditado`), `pagamentos_pix.valor_ia`, `creditos_transacoes.carteira='ia'` (movimentos antigos), tabelas `ia_*`, `medico_ia_contadores`, `grade_medico_fixo` etc.: **sem uso**. Existe
   `sql/migration_remover_fixo_horista.sql` (o Paulo precisa ter rodado o passo 1 no Neon). **Não há SQL para dropar as colunas/tabelas de IA** — ofereça ao Paulo se desejar.
7. **Rate limit em memória** (`flask-limiter` sem Redis): com vários workers, cada um conta separado.
8. **Concorrência:** a proteção contra reserva dupla é no banco (`intervalo_ocupado` tsrange); manter essa constraint ao migrar.
9. **E-mail/WhatsApp em thread** (`_rodar_em_segundo_plano`): sem fila. Em ambiente serverless, trocar por fila/worker.
10. **Testes automatizados: não existem.** A validação histórica foi: `py_compile` de todo `app/`, parse Jinja + `node --check` dos scripts inline dos templates, e boot do app com libs simuladas.

---

## 12. Guia para a adaptação ao sistema-mãe

**Antes de codar, no mãe:** (a) listar tabelas/colunas existentes e **comparar com o §4** — nomes como `medicos`, `consultorios`, `reservas`, `pacientes`, `precos`, `modulos`,
`secretarias`, `funcionarios`, `pagamentos_pix`, `creditos_transacoes` **provavelmente já existem com esquemas diferentes** (este sistema nasceu de um recorte do mãe, por isso o
`INSTALL_ALL.sql` traz tabelas dele). Decidir por tabela: reaproveitar, estender (migration `ADD COLUMN IF NOT EXISTS`) ou prefixar. **[CONFIRMAR NO MÃE]**
(b) Ver como o mãe autentica o médico (aqui: telefone+senha; a decisão do Paulo para o Lifedoctor é **e-mail** — ver nota abaixo) e unificar **uma** identidade, não duas.
(c) Ver se o mãe já tem Asaas/SMTP/WhatsApp/Google Calendar e **reaproveitar** os clientes em vez de duplicar.

**O que migrar (módulos independentes, em ordem):**
1. **Núcleo de saldo/reserva:** `creditos_service` + `reserva_service` + `template_service` + as tabelas `reservas`, `creditos_transacoes`, `pacotes_horas_avulsas`, `precos`, `matriz_*`.
   Preservar as regras do §6 **exatamente** (ordem das validações, 12h, preço da hora = menor pacote, tudo por `registrar_transacao`).
2. **Compra de horas:** `asaas_client` + `webhooks_asaas` + `pagamentos_pix` + rotas `/api/creditos/*` (manter idempotência e o polling).
3. **Grade do médico** (`turnos` + `turnos.html`) e **painel** (`painel_medico.html`, agenda, dados pessoais, pacientes).
4. **Admin:** clientes, consultórios/fotos (precisa Neon S3 ou o storage que o mãe usa — trocar `neon_storage` por equivalente), horas, matriz, relatórios.
5. **Contrato/termo** (`contrato_service`, `pdf_service`, `termos`), **e-mails** (`email_service`) e **notificações**.
6. **API da Dora** — se a Dora e este módulo passarem a viver no mesmo processo, **chamar `reserva_service` direto** e descartar o HTTP/`X-API-Key` (decisão do Paulo em 16/10: a Dora fica exclusiva do Lifemax por ora).

**Mapeamentos práticos:**
- Se o mãe usa **Supabase real**, `pg_query.py`/`PgClient` pode ser descartado: `supabase_client.get_client()` passa a devolver o cliente Supabase (a API é a mesma). Lembrar do ponto do embed (FK no select) só para o `PgClient`.
- Blueprints: prefixar para evitar colisão (`/login`, `/painel`, `/admin`, `/api/...` provavelmente já existem no mãe). Rotas atuais usam nomes de endpoint como `medico_painel.painel`, `admin.dashboard` em `url_for` nos templates — **se renomear blueprints, atualizar todos os `url_for`**.
- Templates têm CSS/JS inline e dependem de `csrf_token()`; garantir CSRF habilitado no mãe.
- Manter o **gate do termo** e o **cadastro mínimo** (§6.5): são regras do contrato/negócio.
- Constantes de negócio a preservar: horários (§6.1), fim de semana (§6.4), 12h (§6.6), pacotes/preços (seed do §4, editáveis no banco), fuso -03:00.
- Segredos: nada de chave no código; tudo por env (§8). **Nunca** commitar `.env`.

**Nota sobre identidade (decisão do Paulo, 2026):** no Lifedoctor/sistema todo, médicos devem **entrar por e-mail**; admin segue só com senha; secretárias com telefone+senha. Este pacote ainda usa
**telefone** como chave de login e de integração com a Dora/WhatsApp. Na adaptação, manter telefone como **dado** (obrigatório p/ reservar) mas alinhar o **login** com a regra do mãe. **[CONFIRMAR COM O PAULO/NO MÃE]**.

**Critérios de aceite da migração (checklist):** reserva por hora e por turno funcionam e debitam; conflito é recusado no banco; data sem matriz recusada; cancelamento ≥12h reembolsa o valor exato e <12h não;
compra PIX e cartão creditam **uma única vez** (webhook + polling); primeiro pagamento ativa assistente; cadastro incompleto bloqueia reserva e leva a "Meus dados"; contrato bloqueia painel até aceitar e baixa em PDF;
médico não vê nomes de outros; admin ajusta saldo e cancela/reserva por qualquer médico; e-mails e alertas não derrubam o fluxo quando SMTP/WhatsApp faltam; nenhum `url_for` quebrado; nenhuma referência a IA/fixo/horista.

---

## 13. Histórico resumido de decisões do Paulo (contexto)

10–11/09: migração Supabase→Neon; saldo em horas; pacotes 6/12/24/48; reembolso 12h; relatórios; pacientes; contrato BIOMAX · 14/09: privacidade na grade; layout do hero · 21/09: Matriz como padrão semanal + replicação;
Dora API; tryout · 23–24/09: cadastro obrigatório em vez de liberação manual; tryout desligado; velocidade da reserva (1 busca do médico, queries em lote); Matriz obrigatória p/ reservar; sobreposição de matriz cancela com confirmação ·
30/09: data de nascimento deixa de bloquear; **todos "avulso"**, removidas Agenda Fixos/Horistas · 19/10: **IA removida**, botão LifeDoctor, "Meus dados" sem texto da planilha, "Visão geral da conta" em 2 colunas, novo logo e favicon.

## Atualização 21/10/2026 — Matriz v2
- Matriz mais rápida (buscas por Set, atualização otimista de uma célula, inserções/remoções em lote).
- Visualizar agenda (admin): modo "Bloquear/desbloquear horários" (clique), botão direito para dar nome do médico, botão verde por dia para ocultar/exibir o dia para os médicos, dicas ao passar o mouse.
- "Matrizes geradas": últimas 5 replicações com "Desfazer a matriz" (tabela `matriz_replicacao_itens`; colunas novas em `matriz_replicacoes`).
- Dias ocultos: tabela `dias_ocultos`; somem da grade do médico e bloqueiam novas reservas (site e Dora).
- Migração: `sql/migration_matriz_desfazer_e_ocultar_dias.sql` (também em INSTALL_ALL.sql).
- Endpoints: GET /admin/api/matriz/replicacoes; POST .../replicacoes/<id>/desfazer, .../celula/bloquear, .../celula/nome, .../dia/ocultar.

## Atualização 22/10/2026 — Painel do médico
- "Minha agenda": removidos a coluna Paciente, "Incluir/alterar paciente" e "E-mail de agendamento" (e as rotas/serviços ligados a eles). Novo botão "Enviar e-mail de confirmação" em cada agendamento: mensagem padrão (Rua Gonçalves Dias, 82 + sala + data/horário), botão "Paciente" (lista de pacientes cadastrados, e-mail puxado do cadastro) e "Enviar email". Rotas: GET /api/reservas/<id>/confirmacao-previa, POST /api/reservas/<id>/enviar-confirmacao.
- Cadastro rápido de paciente: só nome, telefone e e-mail (nova coluna `pacientes.telefone` — `sql/migration_paciente_telefone.sql`).
- Opções para contratação (antes "Venda de horas avulsas"; colunas: horas sem título, Valor hora avulsa, Total, Condição): botão "Comprar" por pacote (abre a compra com valor preenchido; PIX ou cartão parcelado via Asaas).
- Verde padrão dos botões: #0EA5A0 (hover #0C8B87). Regra única de celular em /static/css/base-mobile.css.


## Atualização 22/10/2026 (v46) — Novo padrão visual do painel do médico
- `painel_medico.html` redesenhado conforme a foto enviada pelo Paulo (celular idêntico; PC segue o mesmo padrão, centralizado, menu inferior flutuante).
- Topo azul-petróleo com logo, "Bem-vindo, <nome>!", botão Sair; cartão "Saldo de horas" com + Comprar horas / Meus dados; cartões Reservar consultórios e LifeDoctor.
- Minha agenda: Ver todos, Cadastrar paciente, busca (por data/consultório), abas Próximas/Hoje/Semana/Mês, cartões de consulta (Confirmada/Cancelada, Enviar e-mail, menu ⋮ com cancelar).
- Visão geral da conta (saldo e atalho para Histórico de uso) e menu inferior fixo: Início, Agenda, Pacientes, Meu perfil.
- Removidos: botão Ocultar/Exibir da agenda (substituído por Ver todos), célula "Meu perfil" e botão Pacientes no cabeçalho (agora no menu inferior).

## Atualização 22/10/2026 (v47) — Grade de turnos (`turnos.html`) no novo padrão
- Visual igual ao painel do médico: topo com logo, cartão de saldo (Meus dados / Voltar ao painel), caixa Reservar/Cancelar geral, navegação de mês, legenda e um cartão por consultório. Celular exibe os 7 dias inteiros sem rolagem lateral (como na foto); PC usa o mesmo estilo centralizado.
- Cada consultório ganhou os botões **Ver foto | Reservar | Cancelar**, todos do mesmo tamanho. O modo escolhido num consultório vale só para ele; os botões gerais do topo valem para todos (`modoConsultorio` em JS; `clicarSlotLivre`/`clicarBlocoReservado` validam o consultório).
- Cores: livre = menta claro, reservado por mim = verde, reservado (outros/admin) = azul, indisponível = azul-marinho.
- Removido "Ver detalhes" (duplicava Ver foto, que já mostra descrição).

## Atualização 22/10/2026 (v48)
- **Grade de turnos:** removidos os botões Reservar/Cancelar do alto da página (ficam só em cada consultório); avisos de reserva agora numa faixa flutuante no topo da tela; setas de semana maiores (54 px), verde-água com seta branca; **reserva otimista** — o horário aparece reservado no instante do clique e é confirmado/desfeito conforme a resposta do servidor (`clicarSlotLivre`).
- **Painel:** removida a busca da agenda (`#ag-busca`); cartão LifeDoctor agora usa o logo oficial (`static/images/lifedoctor-logo.png`, fundo transparente).
- **Meus dados e Pacientes:** novo padrão visual compartilhado — `static/css/padrao-medico.css`, `templates/_topo_medico.html` (topo com logo e Sair) e `templates/_nav_medico.html` (menu inferior). Em Meus dados, sair/menu continuam salvando antes de navegar.
- (v50) Grade de turnos, **só no celular**: dentro de cada consultório, ao lado do número da sala, aparece o mês em exibição com seta ← à esquerda e → à direita; as setas acionam os mesmos botões do alto da página (trocam a semana de todos os consultórios).
- (v51) Meus dados: botão "← Voltar" (ao lado de Salvar) leva ao painel e salva os dados antes de sair.
- (v52) /admin (admin_dashboard.html) no novo padrão visual: topo com logo, cartão de números, atalhos (Gerar Matriz, Consultórios, Clientes, Horas, Relatórios), reservas recentes em cartões, aviso de clientes pendentes. Demais telas do admin ainda no visual antigo.

## Atualização 22/10/2026 (v53) — Login
- Tela `/login` no novo padrão. Campo único **"E-mail ou telefone"** + senha (`identificador`; se tiver "@" busca por e-mail sem diferenciar maiúsculas — `supabase_client.listar_medicos_por_email`; senão por telefone). E-mail repetido em mais de um cadastro: entra o cadastro cuja senha confere.

## Atualização 22/10/2026 (v55) — Login
- **Removido** o "Entrar com Google" (rotas `/login/google*`, botão e variáveis `GOOGLE_LOGIN_*` não são mais usadas; `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` seguem só para o Google Agenda).
- Botão **"Recuperar senha"** na tela de login → `/esqueci-senha` (novo padrão visual): aceita e-mail OU telefone; o link de redefinição (30 min) sempre vai para o **e-mail cadastrado** na conta, com a mesma mensagem genérica quando não há cadastro (`recuperacao_senha_service.solicitar_recuperacao(tipo, identificador)`). Depende do SMTP configurado.

## Atualização 22/10/2026 (v56) — Relatórios > Receitas
- Nova aba preta **"Receitas"** (`/admin/relatorios?tipo=receitas`), à direita de "Transações faturadas" (que não foi alterada — ela mostra notas fiscais emitidas).
- Lista todo dinheiro **efetivamente recebido** (`pagamentos_pix` com status `pago`, Pix e cartão), por **data do pagamento em horário de Brasília**, com subtotal por dia e total do período. Independe de nota fiscal.
- Filtros: **Por período (de/até)** e **Mês** (escolher o mês já mostra o relatório). Sem filtro, mostra automaticamente os **últimos 120 dias**. Botão "Baixar planilha (CSV)" exporta o que está na tela.
- Código: `relatorios_service.periodo_receitas / listar_receitas`, `routes/admin.py` (`tipo == 'receitas'`), `admin_relatorios.html`.
- Limite: só aparecem pagamentos que o sistema registrou como pagos (webhook/consulta do Asaas); não há importação direta do extrato do Asaas.

## Atualização 22/10/2026 (v57) — Link de primeiro acesso permanente
- O link enviado pelo admin (Clientes > Enviar link de acesso) **não expira e pode ser usado quantas vezes for preciso** (`recuperacao_senha_service`: expiração em 2099, nunca marcado como usado; contexto `primeiro_acesso`). Cada envio cria um novo link e os anteriores continuam valendo. Links de "Recuperar senha" continuam de 30 min e uso único. Quem abre o link define a senha e entra direto no painel do médico — tratar o link como credencial.
- (v58) Tela do link de primeiro acesso (`redefinir_senha.html`): aviso de contato mostra só os telefones (31) 99754-6473 e (31) 97207-8423, sem nomes.

## Atualização 22/10/2026 (v59) — Relatórios no novo padrão
- `admin_relatorios.html` (Agendamentos, Transações, Não faturadas, Faturadas e Receitas) com o visual do painel: topo com logo, menu em botões, filtros em cartão, abas coloridas. No **celular** cada linha da tabela vira um **cartão** com rótulo/valor, borda colorida (verde = ok/agendamento/NF emitida, vermelho = cancelamento/NF não emitida, verde-água = demais) e linhas separando os campos; no PC continua em tabela com linhas separadas por cor. Sem rolagem lateral.

## v60
- Relatórios > Receitas: coluna "Profissional" em cada pagamento; novo botão "Profissionais" (ranking por total: nome, compras feitas, total) com os mesmos filtros de período e mês; CSV para as duas visões.
- Padrão visual do celular aplicado a todas as páginas do admin: parcial `_admin_topo.html` (cabeçalho + menu) e `static/css/admin-padrao.css` (tabelas viram cartões com `class="cartoes"` + `data-label`; grades empilham no celular). Páginas: login, clientes, cliente (ver/editar/novo), consultórios, fotos, horas, matriz e agenda da matriz.

## v61 — Usuários do admin
- Tabelas `usuarios_admin` e `tokens_admin_usuarios` (sql/migration_usuarios_admin.sql, também no INSTALL_ALL.sql).
- /admin/login: e-mail ou telefone + senha. Só usuário cadastrado e ATIVO entra; a situação é conferida a cada acesso (bloquear derruba a sessão na hora).
- Transição: a senha antiga (ADMIN_PASSWORD, campo e-mail em branco) vale só até o primeiro usuário ativo criar senha.
- Botão "Usuários" (ao lado de Relatórios): pede senha master (ADMIN_MASTER_PASSWORD no Render; padrão definido no código), liberada por 15 min na sessão. Lista usuários, "Novo Usuário" (cadastra e envia link), "Enviar link de acesso", "Bloquear/Ativar" (não permite bloquear a si mesmo).
- Link de acesso: /admin/definir-senha?token=..., NÃO expira e pode ser reutilizado (nova senha quando preciso); se o SMTP não estiver configurado o link aparece na tela para copiar.

## v64 — Página Horas simplificada
- /admin/horas mostra só "Horas na praça" (soma do saldo em horas de todos os profissionais, agora) + endereço padrão. Removidos filtro por mês, horas vendidas/utilizadas (mês e total) e "na praça (mês)". `creditos_service.estatisticas_horas` foi substituída por `horas_na_praca_total()`.

## v66 — Agenda, e-mail de acesso e Manual
- Painel > Minha agenda: status "Confirmada" vira só o ícone; no celular a linha de ações desce para baixo do horário (sem sobreposição); sala exibida como "SL 402"; menu ⋮ com "Reserva confirmada" (verde; mostra SL + endereço — o padrão de Admin > Horas, ou "Rua Gonçalves Dias, 82" se vazio) e "Cancelar reserva" (vermelho).
- E-mail do link de acesso (notificar_primeiro_acesso): novo texto de migração + manual em PDF anexo (static/docs/Manual_do_Cliente_Lifemax.pdf).
- Botão "Manual" sob o logo (topo do painel, turnos, dados, pacientes) → /manual (templates/manual_cliente.html; tabela de pacotes vem do banco). **Regra: ao alterar o sistema, atualizar manual_cliente.html (e o PDF, se mudar o que é enviado).**

## v67 — Primeiro acesso pede e-mail
- Tela do link de primeiro acesso (redefinir_senha.html / auth.redefinir_senha): o campo obrigatório é o E-mail (usado para entrar); o telefone não é mais pedido nem alterado (continua o cadastrado). E-mail já usado por outro profissional é recusado.
- Manual: botão "← Voltar" no topo (volta à página anterior; sem origem, vai ao painel).

## v69 — E-mail de confirmação com horário opcional; /primeiro-acesso por e-mail
- Agenda > "Enviar e-mail": a mensagem NÃO inclui mais o horário automático; novo campo "Horário (opcional)" (texto livre, até 40 caracteres) — se preenchido, entra a linha "Horário: ..." depois da data (prévia atualiza ao digitar). Manual atualizado.
- /primeiro-acesso (página pública): pede o E-MAIL (não mais o telefone). E-mail já cadastrado sem senha → cria a senha; e-mail novo → auto-cadastro só com nome, e-mail e senha (telefone fica NULL; migration_telefone_opcional.sql tira o NOT NULL). O cliente novo só consegue reservar depois de preencher os dados exigidos em "Meus dados" (reserva_service._CAMPOS_OBRIGATORIOS_PARA_RESERVAR); o aviso no painel lista o que falta. Código que usava medico['telefone'] passou a tolerar vazio (Asaas, WhatsApp, Dora, webhook).

## v71 — Perfil "Secretária" + Acesso administrativo
- `usuarios_admin.perfil` ('admin' | 'secretaria'; sql/migration_usuarios_admin_perfil.sql). Em Usuários (senha master) escolhe-se o tipo ao cadastrar.
- Secretária: acessa Dashboard, Matriz (incl. Visualizar agenda, onde aparece o nome do profissional em cada horário reservado), Consultórios, Fotos e Clientes. NÃO acessa Horas, Relatórios (incl. emissão de NF), Usuários, nem altera saldo de cliente (rotas com `requer_admin_total` → 403; menus/atalhos escondidos via `admin_total`). Perfil conferido a cada requisição (bloquear derruba a sessão).
- Página principal e /consultorios: botão "Acesso administrativo" → /admin/login. "Esqueci minha senha" (/admin/esqueci-senha) reenvia o link de acesso (permanente) ao e-mail cadastrado, resposta sempre igual.
- Removido código morto de secretária antiga (auth_service: login_secretaria etc.; blueprint inexistente). Tabela `secretarias`/secretarias_service legados permanecem sem uso no fluxo admin.

## v72 — Visualizar agenda: setas; menu "Visualizar agenda"; botões da página inicial
- Visualizar agenda: setas fixas nas laterais movem TODAS as salas juntas, 3 dias por clique (salas desenhadas depois entram na mesma posição).
- Menu do admin: novo item "Visualizar agenda" à direita de "Usuários" (também no dashboard). A secretária o acessa (e só o que ele precisa: grade, intervalo, bloquear/nomear horário, ocultar dia); "Gerar Matriz" e suas APIs (template, replicar, relatório, replicações, desfazer) passaram a ser só do Administrador.
- Página inicial: Consultórios, Entrar, Primeiro acesso e Acesso administrativo com o mesmo tamanho e cor (2x2 no celular).

## v86 — Rótulo "CRM/Correspondente"
- O campo CRM passou a se chamar "CRM/Correspondente" em Meus dados, no cadastro/visualização de cliente do admin, no PDF do contrato (linha "Registro profissional") e nas mensagens de salvamento. Só o rótulo mudou; o campo no banco continua `crm`.

## v85 — "Meus dados" sem erro interno
- `creditos_service.atualizar_dados_pessoais`: telefone já usado por outro cliente (campo único no banco) → mensagem clara; erros do banco (duplicado, obrigatório, formato, coluna inexistente, outros) viram mensagem amigável na tela e ficam no log do servidor (`[dados_pessoais] erro ao salvar...`) em vez de "erro interno". Cadastro inexistente também tratado.
- A tela já exibia `erro` das respostas 400, sem mudança de front.

## v84 — Relatórios > Receitas sempre por mês
- Receitas (visões Pagamentos e Profissionais) abre sempre num mês: o mês atual (fuso Brasília) ou o escolhido em `mes=AAAA-MM`; mês inválido volta ao atual. Removidos os campos "de/até" e "Últimos 120 dias"; entram setas ← → de mês e "Mês atual". O CSV exporta o mês exibido. Filtros de profissional/cliente preservados ao navegar.
- Arquivos: routes/admin.py (relatorios), templates/admin_relatorios.html.
- Também nesta versão: backup_service trata colunas de intervalo (tstzrange) e tipos desconhecidos.

## v81 — Backup/restauração e limpeza de pagamentos de teste
- Admin > "Backup" (menu + atalho no Dashboard; só Administrador; protegido pela senha master, 15 min): (1) "Baixar backup agora" gera `backup_lifemax_AAAA-MM-DD_HH-MM.json.gz` com TODAS as tabelas do schema public (médicos, reservas, pagamentos, consultórios, valores, usuários admin, fotos no banco...). (2) "Restaurar backup": envia o arquivo, exige digitar RESTAURAR + confirmação; modo mesclar (upsert pela chave primária, nada é apagado), numa única transação (falhou = nada muda).
- Tipos especiais: colunas de intervalo (tstzrange etc.) são salvas como texto e voltam ao tipo certo; qualquer tipo desconhecido vira texto em vez de derrubar o backup.
- Arquivos: services/backup_service.py (novo), routes/admin.py (`/admin/backup`, `/backup/baixar`, `/backup/restaurar`), templates/admin_backup.html (novo), admin_usuarios_master.html (título parametrizável).
- sql/limpeza_testes_receitas.sql: uso único, apaga 3 pagamentos de teste (22/10 R$390; 23/09 e 11/09 R$20) de Receitas e a transação da compra de 6h de 22/10 (Horas vendidas de outubro 30 → 24). Identifica por nome/valor/data (não depende da coluna horas_pacote). Trava: só apaga se achar exatamente 3. Não altera saldo de ninguém.

## v80 — Admin: "Alterar valores"
- Novo botão "Alterar valores" no menu do admin (e atalho no Dashboard), só para perfil Administrador (secretária não vê nem acessa — 403). Rota `/admin/valores` (GET/POST).
- A página lista as opções de "Opções para contratação" (tabela `pacotes_horas_avulsas`: 6h/12h/24h/48h): um campo de valor por hora para cada opção, total calculado (horas × valor/hora) ao vivo, botão "Publicar novos valores" com confirmação.
- Validação (`creditos_service.validar_novos_valores_pacotes`): valor > 0 e ≤ R$ 10.000, aceita vírgula/ponto, pacote maior nunca com valor/hora maior que o menor. Gravação em `atualizar_valores_pacotes` (valor_hora, valor_total, atualizado_em).
- Efeito: painel do médico, janela de compra, manual do cliente e preço de reserva (valor/hora do MENOR pacote) passam a usar os novos valores imediatamente. Pagamentos já gerados mantêm o valor cobrado.
- Sem migração de banco. Arquivos: routes/admin.py, services/creditos_service.py, templates/admin_valores.html, _admin_topo.html, admin_dashboard.html.

## v79 — Login mais rápido e horários vagos destacados
- Painel do médico (`/painel`, destino do login): as ~10 consultas ao banco agora rodam em paralelo (ThreadPoolExecutor, 4 trabalhadores) em vez de uma após a outra.
- Tela de login (GET): acorda o banco e abre conexão em segundo plano (`pg_query.aquecer_banco`) enquanto a pessoa digita. Pool de conexões: min 2 / máx 25, com keepalive.
- Hash de senha NÃO foi enfraquecido (scrypt do Werkzeug mantido).
- Grade de Turnos: horário vago ganhou contorno verde discreto (#5DBFA9) e sombra leve; destaque mais forte ao passar o mouse. O contorno do modo "Reservar" continua.
- Arquivos: routes/medico_painel.py, routes/auth.py, services/pg_query.py, templates/turnos.html.

## v78 — Legibilidade do modal "Ver foto"
- Bloco "Descrição" com fundo verde bem claro (#EAF7F5), borda suave, sombra e texto azul-marinho legível; "Sem foto cadastrada" também com fundo claro. Causa: `--bege` em turnos.html é azul escuro. Arquivo: app/templates/turnos.html.

## v77 — Primeiro nome nos horários reservados
- Grade de Turnos (médicos logados): horário ocupado por outro profissional mostra só o PRIMEIRO NOME (antes "Reservado"); o próprio médico segue vendo "Você". Sobrenome e demais dados nunca saem da API (`/api/turnos/grade` devolve só `{nome: primeiro}`). Sem nome → continua "Reservado". Horários bloqueados pelo admin seguem "Reservado".
- Admin/secretária (Visualizar agenda / Matriz) inalterados: nome completo e demais dados.
- A vitrine pública (sem login) não exibe agenda. Arquivos: app/routes/turnos.py, app/templates/turnos.html (legenda).

## v76 — Recibo automático e aviso de e-mail automático
- Recibo de pagamento: a cada compra de horas confirmada (PIX/cartão, via webhook Asaas ou consulta manual) o médico recebe e-mail com data/hora, horas, valor, forma e código do pagamento. Idempotente (pagamento já pago não reenvia). Só é enviado se o médico tiver e-mail cadastrado.
- Rodapé padrão em TODOS os e-mails (`email_service.enviar_email`, `RODAPE_EMAIL_AUTOMATICO`): informa que é automático, que não se deve responder/escrever para o endereço e que se usem os canais da Lifemax. Exceção: confirmação de consulta ao paciente (`rodape_automatico=False`), pois o paciente fala com o médico.
- Arquivos: app/services/email_service.py, app/routes/webhooks_asaas.py.

## v75 — Descrição do consultório em "Ver foto"
- Grade de Turnos (médico): o modal "Ver foto" mostra, abaixo das fotos, um bloco com o rótulo "Descrição" e o texto cadastrado em Admin > Consultórios (admin ou secretária). Quebras de linha preservadas.
- Se a descrição estiver vazia (ou só espaços), o bloco não aparece.
- Arquivo: app/templates/turnos.html. Sem mudança de banco ou de API.

## v73 — Horas restaurada, com contagem zerada
- Admin > Horas voltou ao formato completo (filtro por mês, horas vendidas/utilizadas/na praça do mês e totais) — só perfil Administrador. Os contadores de vendidas/utilizadas passaram a contar apenas movimentos a partir de 22/10/2026 — primeiro dia com agendamentos liberados; compras e reservas feitas em outubro para novembro contam (`creditos_service.DATA_INICIO_CONTAGEM_HORAS`; pode ser mudada pela variável HORAS_INICIO_CONTAGEM no Render). "Horas na praça (total)" continua sendo o saldo real de todos os profissionais hoje. Nenhum dado foi apagado do banco.
