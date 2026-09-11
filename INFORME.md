# Informe — Sistema 1: Reserva de Salas (Horistas)
*Preparado em 09/09/2026 a partir de uma cópia do sistema Lifemax/Biomax original.*

---

## O que é este sistema

É a parte do Lifemax que permite a um **médico horista** (ou avulso) fazer login,
ver a grade de horários de um consultório (com foto), reservar hora(s) usando
crédito em R$, e pagar esse crédito via PIX ou cartão (Asaas).

**Não inclui**: a Agenda Fixos dos médicos mensalistas, a Rede Lifemax
pública, prontuário, contabilidade, WhatsApp/Dora, e o fluxo real do
médico **horista** (saldo em horas creditado manualmente pela recepção,
agendamento de paciente via matriz de liberação — ver `horistas_service.py`
no sistema maior). Esse recorte é só o pedaço de "comprar/reservar hora de
sala" pelo médico **avulso** (paga em R$ via PIX/cartão).

⚠️ **Atualizado em 10/09/2026, na revisão de produção**: ao contrário do que
a versão original deste informe dizia, este pacote **inclui sim** um painel
administrativo (`/admin/*`), com dashboard, cadastro de consultórios, upload
de fotos e a Matriz de Agendamento. Veja `README_PRODUCAO.md`/`INSTALAR.md`
para a lista completa de rotas do admin — esses dois arquivos estavam certos,
só este `INFORME.md` estava desatualizado.

Também na revisão de produção: como `medicos.tipo_vinculo` pode valer
`'fixo'`, `'avulso'` **ou** `'horista'` (não só os dois primeiros), o código
de reserva avulsa (`reserva_service.py`, `turnos.py`, `medico_painel.py`)
agora bloqueia explicitamente tanto `'fixo'` quanto `'horista'` — antes só
bloqueava `'fixo'`, o que deixaria um médico horista de verdade (se logasse
nesta tela, usando o mesmo banco de dados de produção da Lifemax) comprar
créditos em R$ numa carteira que ele nunca teria como gastar.

⚠️ **Atualizado em 10/09/2026 (migração para Neon)**: o banco de dados
deste pacote saiu do Supabase e foi pra Neon (Postgres serverless), a
pedido do Paulo. Isso mudou três coisas:
1. **Banco**: `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` viraram `DATABASE_URL`
   (a connection string do Neon). O acesso ao banco continua escrito do
   mesmo jeito em todo o código (`db.get_client().table(...).select(...)...`),
   só que por baixo agora é `app/services/pg_query.py` (SQL de verdade via
   psycopg2) em vez do SDK do Supabase — ver `app/services/supabase_client.py`
   pra entender por que o nome do arquivo não mudou.
2. **Fotos dos consultórios**: saíram do Supabase Storage e foram pro Neon
   Object Storage (`app/services/neon_storage.py`, variáveis `NEON_S3_*`).
3. **Ordem das migrations**: testando `sql/INSTALL_ALL.sql` contra um
   Postgres de verdade (não só o Supabase, que talvez fosse mais tolerante
   com isso), apareceram 4 migrations que dependiam de tabela/coluna criada
   por uma migration que vinha DEPOIS delas no arquivo — um bug real,
   independente da troca de banco. Corrigido reordenando (ver
   `sql/build_install_all.py`, que agora gera `INSTALL_ALL.sql`
   automaticamente a partir dos arquivos individuais, na ordem certa).

Também nessa revisão: os formulários de `/admin/consultorios` e
`/admin/consultorios/.../fotos` (criar/editar/excluir consultório, enviar
foto) não tinham o campo oculto `csrf_token` — como a proteção contra CSRF
(Flask-WTF) está ativada no projeto inteiro, todo POST nessas telas
recusava com "400 CSRF token is missing" e o admin não conseguia cadastrar
nem editar consultório nenhum. Corrigido adicionando o campo em
`admin_consultorios.html` e `admin_fotos.html` (mesmo padrão já usado em
`login.html`/`admin_login.html`).

⚠️ **Atualizado em 10/09/2026 (à tarde, já com o Neon real em teste)**:

1. **Reconexão automática (Neon "scale to zero")**: o compute serverless
   do Neon suspende sozinho quando fica ocioso, derrubando conexões que o
   pool (`pg_query.py`) mantinha abertas — aparecia como
   `psycopg2.OperationalError: SSL connection has been closed unexpectedly`
   em qualquer tela depois de um tempo sem uso. Corrigido: o pool agora
   descarta conexão fechada/suspeita em vez de devolver ela pro pool, e
   `execute()` tenta de novo automaticamente 1x com conexão nova antes de
   desistir. Testado de verdade matando a conexão no meio (`pg_terminate_backend`)
   e confirmando que a próxima consulta se recupera sozinha.

2. **Modelo de preço da venda de horas avulsas trocado** (pedido do
   Paulo): saiu o preço escalonado antigo (1ª/2ª/3ª hora + "turno de 4h"
   em `creditos_service.calcular_preco_horas`) e entrou um modelo de
   pacotes fechados — 6h/12h/24h/48h, cada um com seu preço por hora
   (desconto por volume) e opção de parcelamento no cartão pro 24h/48h.
   Ver `sql/migration_pacotes_horas_avulsas.sql` e a nova tabela
   `pacotes_horas_avulsas` (⚠️ **não confundir** com a tabela
   `pacotes_horas`, que já existia e é uma coisa completamente diferente:
   só a lista de quantidades usada pra CREDITAR horas manualmente ao
   médico **horista**, sem preço nem cobrança — os nomes parecidos são
   coincidência de domínio, não a mesma tabela). O preço da "hora avulsa"
   usado pra debitar reservas (por hora ou turno) passou a ser sempre o
   valor/hora do menor pacote (hoje, 6h = R$ 65,00/h) — não existe mais
   `preco_turno` fixo separado. A tela de compra do médico
   (`painel_medico.html`) trocou o campo livre "Valor em R$" por uma
   escolha entre os 4 pacotes; não existe (ainda) tela admin pra editar
   esses 4 preços — hoje só dá pra mudar direto no banco
   (`update pacotes_horas_avulsas set ...`). Se quiser essa tela, é
   fácil de adicionar depois.

3. **Card "Módulo 1 — Venda de Horas Avulsas" removido do painel do
   médico** (pedido do Paulo — os médicos vão ter outro caminho de
   acesso): `modulos_service.listar_modulos_visiveis` agora tira esse
   módulo específico (slug `venda-horas-avulsas`) do que aparece no
   painel do médico. Continua existindo normalmente em
   `listar_todos_modulos` (usado pelo admin) e no banco — só não aparece
   mais como card pro médico.

4. **Bug real encontrado testando a troca de preço acima**: o código já
   chamava uma tabela `funcionarios` (lista de e-mails avisados quando
   alguém reserva um turno/hora — ver comentário em
   `migration_secretarias.sql`, que já citava essa tabela como se
   existisse) mas **nenhuma migration deste pacote criava ela**. Resultado:
   toda reserva por hora OU por turno quebrava com 500 *depois* de já ter
   debitado o crédito do médico e criado a reserva (a consulta que falhava
   estava fora do try/except de notificação). Corrigido em duas frentes:
   `sql/migration_funcionarios.sql` cria a tabela que faltava, e
   `reserva_service._pos_reserva` agora protege essa consulta dentro do
   try/except (então mesmo que a tabela suma ou fique indisponível nunca
   mais quebra uma reserva já paga). Não existe tela admin pra cadastrar
   esses e-mails ainda — insira direto pelo SQL Editor do Neon por
   enquanto (exemplo no topo do arquivo da migration).

Tudo isso foi testado de ponta a ponta contra um Postgres 16 local de
verdade antes de reempacotar: instalação completa do `INSTALL_ALL.sql`
sem erros, reserva por hora e por turno debitando o valor certo, compra
de pacote creditando a quantidade exata de horas via webhook, e as rotas
`/painel` e `/turnos` renderizando sem erro.

⚠️ **Atualizado em 10/09/2026 (fim do dia — contrato real, saldo em horas
e transferência entre carteiras)**: seis pedidos novos do Paulo, todos
implementados e testados:

1. **Contrato Digital real substituiu o texto placeholder**. O texto
   integral do "Contrato Digital de Utilização de Consultórios por Horas,
   Serviços e Regras de Reserva" (enviado pelo Paulo em .docx) agora fica
   centralizado em `app/services/contrato_service.py` — usado tanto pela
   tela de aceite no primeiro login (`termo_uso.html`, que mostrou o
   texto correto pra sempre precisar reler o resto do sistema) quanto
   pelo PDF baixável (item 2). O texto foi conferido **caractere por
   caractere** contra o .docx original via script automatizado (comparação
   de 12.797 caracteres de corpo, 18 títulos de seção e 10 declarações
   finais — bateu 100%). Cada aceite agora também grava qual **versão**
   do contrato foi aceita (`medicos.termo_versao`, ver
   `sql/migration_termo_versao.sql`) — se o texto mudar no futuro, dá pra
   saber com certeza qual versão cada médico aceitou no passado.

2. **Botão "Baixar contrato (PDF)"** no final do painel do médico
   (`painel_medico.html`) → rota `/contrato/baixar`
   (`app/routes/termos.py`) → `app/services/pdf_service.py` gera o PDF na
   hora (via reportlab), preenchido com os dados reais do aceite daquele
   médico específico (nome, CPF/CNPJ, CRM, data/hora, IP, versão do
   contrato) — não é um PDF genérico igual pra todo mundo. Disponível a
   qualquer momento, não só no primeiro acesso.

3. **Painel do médico mostra saldo em HORAS** (ex: "18h") em vez de R$
   pra carteira de reserva de salas — o saldo de IA continua mostrando em
   R$ normalmente, sem mudança. A mensagem de "saldo baixo" também passou
   a comparar horas com horas (`horas_minimas`), não mais R$.

4. **Reserva bloqueada sem saldo suficiente em horas**: tanto reserva por
   hora quanto por turno agora recusam com uma mensagem clara em horas —
   "você tem Xh disponíveis e essa reserva precisa de Yh. Compre mais
   horas para continuar." (`SaldoInsuficienteError`, em
   `app/services/reserva_service.py`) — antes a mensagem só falava de R$.

5. **Modal de compra redesenhado em passos**: primeiro o médico escolhe o
   destino (Horas ou IA), preenche o valor/pacote, e só então vê uma tela
   de **confirmação explícita** ("você está prestes a adicionar R$ X para
   a carteira de Y") antes de a tela de pagamento do Asaas abrir — pra
   garantir que o médico saiba pra qual carteira o dinheiro está indo
   antes de pagar. Pra compra de horas, o valor mínimo continua sendo o
   do menor pacote da tabela (hoje, 6h).

6. **Transferência de saldo entre as duas carteiras** (IA ↔ Horas), com
   link dentro de ambas as telas de compra do modal ("prefiro transferir
   de uma carteira pra outra"). Nova função
   `creditos_service.transferir_saldo()` e rota
   `POST /api/creditos/transferir` — sempre debita de uma carteira e
   credita o mesmo valor na outra (dois lançamentos em
   `creditos_transacoes`, tipo "ajuste"), recusa se o saldo de origem for
   insuficiente, e é bloqueada pra médicos mensalistas/turno e horistas
   (que não usam a carteira de reserva de salas).

Tudo testado de ponta a ponta contra um Postgres 16 local limpo, via
Flask test client de verdade (não só renderização isolada de template):
instalação completa do `INSTALL_ALL.sql` sem erros, tela `/termos`
mostrando o contrato real e recusando avançar sem aceitar, aceite
gravando `termo_versao` corretamente, `/contrato/baixar` devolvendo um
PDF válido e não-vazio, `/painel` mostrando o botão de baixar contrato e
o saldo em horas, reserva por hora e por turno sem saldo suficiente
recusando com a mensagem certa (e funcionando normalmente quando o saldo
é suficiente), os 4 passos do modal de compra presentes e condicionados
por tipo de médico, e a transferência de saldo movendo o valor certo
entre as carteiras (inclusive os casos de erro: saldo insuficiente e
médico fixo/horista tentando usar a carteira de salas).

⚠️ **Atualizado em 10/09/2026 (mais tarde ainda — painel admin "Clientes"
e fotos em lote)**: dois ajustes rápidos pedidos pelo Paulo:

1. **Nova tela `/admin/clientes`** ("Clientes" no menu do admin): lista
   todos os médicos cadastrados com busca por nome/telefone/e-mail, saldo
   de Salas/Horas e saldo de IA, e um botão **"Alterar saldo"** em cada
   linha que abre um formulário rápido (carteira + valor em R$ + motivo
   opcional) pra creditar ou debitar saldo manualmente sem precisar mexer
   direto no banco -- útil pra dar crédito de teste, cortesia, ou
   corrigir um erro. Valor positivo credita, negativo debita; o ajuste
   vira uma transação tipo "ajuste" de verdade em `creditos_transacoes`
   (não é uma edição "invisível" -- fica no histórico do médico igual
   qualquer outro lançamento). Rotas novas em `app/routes/admin.py`:
   `GET /admin/clientes` e `POST /admin/clientes/<id>/ajustar-saldo`.

2. **Fotos de consultório em lote**: o formulário de "Adicionar fotos"
   (`/admin/consultorios/<id>/fotos`) agora aceita selecionar VÁRIAS
   fotos de uma vez (`<input type="file" multiple>`) em vez de precisar
   repetir o envio uma foto por vez -- o suporte a múltiplas fotos por
   consultório já existia no banco e no backend (`fotos` é um array, e
   `adicionar_fotos_consultorio` já *anexava* em vez de substituir), mas
   o formulário só deixava escolher 1 arquivo por envio. De quebra,
   corrigido um bug real encontrado nessa revisão: a tela de fotos nunca
   mostrava as mensagens de sucesso/erro do envio (`flash()` era chamado
   no backend, mas o template não tinha o bloco que exibe elas) -- então
   se um envio falhasse (ex: credenciais do Neon Object Storage não
   configuradas), o admin não tinha nenhuma pista do motivo e só via a
   página recarregar "sem fazer nada".

Testado de ponta a ponta contra Postgres local: lista de clientes com
busca, crédito e débito nas duas carteiras (confirmando que uma não
afeta a outra), todas as validações de erro (carteira inválida, valor
não-numérico, valor zero, médico inexistente) sem quebrar a rota, acesso
bloqueado sem sessão de admin, e envio de 3 fotos numa única submissão
resultando em exatamente 3 fotos salvas (mais uma checagem visual via
screenshot da tela nova).

⚠️ **Atualizado em 10/09/2026 (fim do dia — carteira de Salas/Horas é
medida em horas em TODO lugar, não mais em R$)**: pedido explícito do
Paulo -- "os consultórios são reservados por horas, a medida contábil no
sistema pra consultórios é medida em horas, não em dinheiro [...] a IA
mede o saldo e o consumo em dinheiro" -- ou seja, a regra vale só pra
carteira de Salas/Horas; a de IA continua em R$ normalmente, sem mudança.
Varredura no sistema inteiro atrás de qualquer lugar que ainda mostrasse
R$ pra essa carteira, e correção de tudo que achou:

1. **"Preço base" sumiu do cadastro de consultório.** Esse campo
   (`preco_periodo`) nunca influenciou o preço de reserva de verdade
   desde a virada pro modelo de pacotes fechados (10/09/2026, de manhã)
   -- só alimentava uma função (`resumo_financeiro_medico`) que nem
   chega a ser chamada por nenhuma rota nesse pacote (código morto,
   herdado do sistema maior original). Removido dos formulários de criar
   e editar consultório em `admin_consultorios.html`; a coluna continua
   existindo no banco só por compatibilidade, sempre gravada como 0.

2. **Ajuste manual de saldo (painel admin "Clientes") agora é em HORAS
   pra carteira de Salas/Horas.** O campo mudou de "Valor em R$" pra
   "Quantas horas?" quando a carteira selecionada é Salas/Horas (a IA
   continua pedindo R$ normalmente) -- a tela troca o rótulo e o tipo do
   campo automaticamente conforme a carteira escolhida no dropdown. Por
   baixo dos panos ainda converte pra R$ no preço vigente da hora avulsa
   (mecanismo interno do saldo continua sendo em R$), mas isso é
   transparente pro admin.

3. **Transferência de saldo (Salas/Horas → IA) também virou horas.** O
   médico agora informa quantas horas quer converter em crédito de IA
   (não mais um valor em R$) quando a origem é a carteira de horas; saindo
   da carteira de IA (que é mesmo em dinheiro) continua pedindo um valor
   em R$ normalmente. Rota `/api/creditos/transferir` aceita `horas` (pra
   origem='salas') ou `valor` (pra origem='ia').

4. **Histórico de transações do médico (painel) agora mostra horas pra
   linhas da carteira de Salas/Horas**, com uma coluna "Carteira" nova
   deixando claro qual é qual -- antes toda linha aparecia em R$,
   inclusive débito/crédito de horas, o que contradizia a forma como o
   saldo atual já era mostrado (em horas) desde a atualização de mais
   cedo. Uma nova função (`creditos_service.enriquecer_transacoes_com_horas`)
   calcula a equivalência em horas de cada transação -- usa o
   `quantidade_horas` já gravado quando existe (reservas e compras de
   pacote sempre têm; ajustes/transferências passaram a gravar também,
   ver itens 2 e 3), ou estima pelo valor em R$ no preço vigente quando
   não tem (transações bem antigas).

Testado de ponta a ponta contra Postgres local (27 verificações):
cadastro/edição de consultório sem pedir preço, ajuste de saldo em horas
creditando/debitando exatamente a quantidade certa (e o valor em R$
interno batendo com horas × preço da hora), ajuste de IA continuando em
R$ isolado da carteira de horas, todas as validações de erro, transferência
salas→ia em horas e ia→salas em R$, e o histórico do médico mostrando "Xh"
nas linhas de Salas/Horas e "R$ X,XX" nas de IA -- mais checagem visual
por screenshot de cada tela alterada.

⚠️ **Atualizado em 10/09/2026 (painel admin "Horas")**: o Paulo mandou um
print de uma tela parecida do sistema maior original (consultórios
listados com "Filtre por mês" e três cartões -- Horas vendidas / Horas
utilizadas / Horas na praça) e pediu **"No admin preciso de um painel
assim com saldo total e saldo por mês"**.

Nova tela **`/admin/horas`** ("Horas" no menu do admin), com filtro por
mês (`<input type="month">`) e três números, todos só da carteira de
Salas/Horas (a de IA não entra, ela já tem seu próprio jeito de olhar
consumo em R$):

1. **Horas vendidas** -- soma de todos os pacotes comprados DE VERDADE
   (via PIX/cartão) no mês escolhido.
2. **Horas utilizadas** -- soma de todas as reservas feitas no mês
   escolhido (débito por consumo real).
3. **Horas na praça** -- soma do saldo ATUAL de todos os médicos (não
   muda com o filtro de mês -- é uma fotografia de agora: quanto já foi
   comprado e ainda não foi usado).

Ajuste manual do admin e transferência entre carteiras (ambos gravados
como tipo "ajuste" em `creditos_transacoes`) ficam de propósito FORA de
"vendidas"/"utilizadas" -- não são venda nem uso de verdade, só
movimentação interna. Nova função `creditos_service.estatisticas_horas(mes,
ano)` calcula os 3 números; nova rota `admin.horas` em
`app/routes/admin.py`; novo template `admin_horas.html`.

⚠️ Achado testando essa tela: a função auxiliar `estimar_horas_compraveis`
tem um teto de 60h por chamada (faz sentido lá -- é usada pra mostrar
"quanto EU tenho pra gastar" no painel de UM médico). Usar ela sem
ajustar esse teto pra somar o saldo de TODOS os médicos corromperia o
total (testado: com 1 médico só com +900h de saldo, "horas na praça"
aparecia como 75h em vez de milhares). `estatisticas_horas` chama essa
função com um limite bem mais alto só pra esses dois números agregados
-- os demais usos de `estimar_horas_compraveis` no sistema (painel do
próprio médico, lista de Clientes) não foram tocados.

Testado de ponta a ponta contra Postgres local (20 verificações):
horas_vendidas/utilizadas filtradas corretamente pro mês escolhido (e
excluindo ajuste/transferência), horas_na_praca correta e SEM filtro de
mês, nenhuma transação da carteira de IA vazando pros totais, filtro de
mês inválido não quebra a rota (cai pro mês atual), link "Horas" presente
em todas as telas do admin -- mais checagem visual por screenshot,
batendo com o visual da tela de referência (cartões verde/azul-marinho).

⚠️ **Atualizado em 10/09/2026 (liberação manual de acesso pelo admin)**:
o Paulo mandou print de outra tela do sistema maior original (toggle
**"Usuário autorizado no sistema"**, ligado/desligado por médico) e
pediu: **"Cliente faz login - nome fica vermelho - admin precisa liberar
para médico usar sistema - fica bloqueado para reservar consultas até
admin liberar"**.

Coluna nova `medicos.autorizado` (boolean, migração
`sql/migration_autorizacao_medico.sql`). Como funciona:

1. **Auto-cadastro (`/primeiro-acesso`) nasce com `autorizado=False`.**
   É a ÚNICA porta de entrada que nasce bloqueada -- é o próprio médico se
   cadastrando sozinho, sem ninguém do admin conferindo antes. Ele
   consegue logar e comprar horas normalmente (nada disso é travado), só
   fica **bloqueado de RESERVAR consultório** até o admin liberar.
   Médicos cadastrados de outras formas (ex: importação de agenda fixa em
   `agenda_fixos_service.py`, feita pelo próprio admin a partir de uma
   planilha já conferida) continuam nascendo `autorizado=True`, igual
   sempre foi -- `criar_medico()` ganhou um parâmetro `autorizado=True`
   (mantém o comportamento de sempre pra quem já chamava a função) e só a
   rota de auto-cadastro passa `autorizado=False` explicitamente.
   Médicos que já existiam no banco antes dessa migração também viram
   `autorizado=True` no backfill (ninguém que já estava ativo foi travado
   de repente).

2. **Painel `/admin/clientes`**: nome do médico aparece em **vermelho**
   quando `autorizado=False`, com uma tag "Aguardando liberação" e um
   botão **"Liberar acesso"**; quando liberado, mostra tag verde
   "Autorizado" e um botão "Bloquear acesso" (reversível a qualquer
   momento). Rota nova `POST /admin/clientes/<id>/autorizacao`.

3. **Bloqueio de verdade fica no service layer** (não só na tela): tanto
   `reserva_service.reservar_turno` quanto `reservar_por_hora` (as duas
   únicas portas de entrada pra reservar consultório avulso -- usadas
   pela Grade de Turnos web e, no sistema maior original, também pelo
   assistente de WhatsApp) chamam a mesma checagem
   `_checar_pode_alugar_avulso`, que agora levanta
   `NaoAutorizadoError` antes de qualquer outra coisa se o médico não
   estiver autorizado. As rotas de API (`/api/turnos/reservar` e
   `/api/turnos/reservar-horas`) capturam esse erro e devolvem 403 com
   mensagem clara. Nenhuma reserva é criada nem saldo é debitado numa
   tentativa bloqueada -- confirmado testando.

4. **Avisos visuais pro médico**: enquanto não autorizado, o painel
   (`/painel`) mostra um aviso destacado ("seu cadastro ainda está
   aguardando liberação...") e a tag de status muda de "Ativo" pra
   "Aguardando liberação"; a tela de reserva (`/turnos`) também mostra um
   aviso no topo avisando que a reserva só é confirmada depois da
   liberação.

Testado de ponta a ponta contra Postgres local (24 verificações):
auto-cadastro nasce não-autorizado, médicos já existentes continuam
autorizados (grandfather), avisos aparecem no painel e na tela de
turnos, tentativa de reserva bloqueada tanto na chamada direta quanto
pela rota HTTP real (403, sem criar reserva, sem debitar saldo), admin
listando/liberando/bloqueando pela tela nova, e reserva funcionando
normalmente depois de liberado -- mais checagem visual por screenshot
(lista de Clientes com nomes em vermelho/verde, e os dois avisos no lado
do médico).

## O que está incluído nessa cópia

```
app/routes/
  turnos.py            -> tela de reserva em si (/turnos)
  auth.py               -> login, primeiro acesso, esqueci senha
  medico_painel.py       -> "Meu painel" (saldo, comprar créditos, Painel de IA, dados pessoais)
  webhooks_asaas.py     -> confirma o pagamento PIX/cartão e credita o saldo
  termos.py             -> tela de aceite do Contrato Digital (1º login) + /contrato/baixar (PDF)

app/services/           -> toda a lógica de negócio correspondente
  contrato_service.py    -> texto integral do Contrato Digital (fonte única, novo 10/09/2026)
  pdf_service.py          -> gera o PDF do contrato sob demanda (novo 10/09/2026)
app/templates/          -> turnos.html, login.html, painel_medico.html, etc.
sql/                     -> schema.sql + as migrações relevantes (44 arquivos)
```

## ⚠️ Uma dependência que talvez você queira revisar

O arquivo `auth.py` (e `creditos_service.py`) usa **duas funções pequenas**
(`normalizar_telefone` e `telefone_sem_ddi`) que vivem dentro de
`agenda_fixos_service.py` — um arquivo **enorme**, que na verdade é o motor
inteiro da Agenda Fixos dos médicos mensalistas (não faz parte deste sistema).
Copiei o arquivo inteiro pra não quebrar nada, mas **só essas duas funções são
usadas de verdade aqui**. Se quiser um sistema mais enxuto, pode extrair só
essas duas funções pra um arquivo pequeno e apagar o resto.

Do mesmo jeito, `medico_painel.py` traz "Painel de IA" e "Dados Pessoais"
juntos com a compra de créditos, porque no sistema original eles vivem no
mesmo arquivo. Se o objetivo é *só* reserva de salas, pode ser que você queira
tirar essas duas telas depois.

## O banco de dados (Neon) — você vai criar do zero

A forma mais simples: rode `sql/INSTALL_ALL.sql` inteiro (já vem com
`schema.sql` + todas as `migration_*.sql` concatenadas na ordem certa —
ver o aviso "Atualizado em 10/09/2026" acima: a ordem ENTRE elas importa
sim, ao contrário do que este informe dizia antes; 4 migrations dependem
de outra que precisa rodar primeiro). Se preferir rodar arquivo por
arquivo (ou estiver reinstalando contra Supabase por algum motivo), use a
ordem gerada por `sql/build_install_all.py`, não a ordem alfabética pura.

**Tabelas que esse sistema realmente usa no dia a dia:**
- `medicos` — cadastro, saldo de crédito, saldo de IA
- `consultorios` — salas, fotos, preço
- `reservas` — cada hora reservada
- `creditos_transacoes` — histórico de compra/consumo de crédito
- `pagamentos_pix` — pagamentos via Asaas (PIX e cartão)
- `precos` — só o campo `horas_minimas` ainda é lido (mínimo de horas por
  reserva); os campos de preço escalonado (`preco_hora_1/2/3`,
  `preco_turno`) ficaram sem uso desde 10/09/2026, ver `pacotes_horas_avulsas` abaixo
- `pacotes_horas_avulsas` — **novo, 10/09/2026**: os 4 pacotes de venda de
  horas avulsas (6h/12h/24h/48h, com preço e parcelamento) — é daqui que
  vem todo preço de venda de hora avulsa hoje. ⚠️ Não confundir com
  `pacotes_horas` (tabela diferente, mais antiga, sem preço — só a lista
  de quantidades pra creditar hora manualmente ao médico horista)
- `funcionarios` — **novo, 10/09/2026**: e-mails avisados quando um
  médico reserva um turno/hora avulsa (o código já dependia dela, mas
  faltava criar — ver o addendum acima)
- `secretarias` — só usado pra recuperação de senha compartilhada
- `tokens_recuperacao_senha` — "esqueci minha senha"

As outras migrações da pasta criam colunas/tabelas de funcionalidades que
vieram *junto* (Painel de IA, dados pessoais) — não vão fazer falta se você
decidir tirar essas telas depois.

## Variáveis de ambiente necessárias (.env)

Veja o arquivo `.env.example` incluído. As que **importam de verdade** pra
esse sistema funcionar (nomes conferidos direto em `app/config.py`):
- `DATABASE_URL` — connection string do seu projeto Neon (era
  `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` antes da migração de 10/09/2026)
- `NEON_S3_ENDPOINT_URL`, `NEON_S3_REGION`, `NEON_S3_ACCESS_KEY_ID`,
  `NEON_S3_SECRET_ACCESS_KEY`, `NEON_S3_BUCKET` — pro upload de fotos dos
  consultórios (Neon Object Storage; recomendadas, mas não travam o
  servidor de subir se faltarem)
- `FLASK_SECRET_KEY` — qualquer texto aleatório longo (obrigatório em
  produção — sem isso o servidor recusa iniciar, ver `Config.validate()`)
- `ADMIN_PASSWORD` — senha do painel `/admin` (também obrigatória em
  produção)
- `ASAAS_API_KEY`, `ASAAS_ENV` (`sandbox` ou `production`) — pra gerar
  cobrança PIX/cartão
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_LOGIN_REDIRECT_URI` — só
  se quiser manter o "Entrar com Google"

## O que dizer pro Claude na conversa nova

Sugestão de primeira mensagem:

> "Estou criando um sistema novo e independente, uma cópia de uma parte de um
> sistema maior (Lifemax). Esse sistema é só sobre reserva de horas em
> consultório por médicos horistas, com pagamento via Asaas. Vou subir os
> arquivos em anexo. Preciso criar um projeto novo no Neon (Postgres) do
> zero — me ajude a rodar `sql/INSTALL_ALL.sql` e a configurar as
> variáveis de ambiente."

Isso já dá pro Claude entender o recorte e trabalhar com esses arquivos como
base, exatamente como fez pro sistema original.
