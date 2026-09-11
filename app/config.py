"""
Configurações centrais do projeto.
Todas as chaves sensíveis vêm de variáveis de ambiente (.env) — nunca
deixe API keys direto no código.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# O Google, na resposta do token OAuth (login com Google e Google Agenda),
# costuma devolver o "scope" reformatado (reordenado, e às vezes com
# "email"/"profile" abreviados junto da URL completa) -- diferente,
# caractere por caractere, do que foi pedido. Por padrão a biblioteca
# oauthlib trata isso como um ERRO ("Scope has changed") e cancela o
# login, mesmo sendo uma reformatação inofensiva do Google, não uma
# falha de verdade. Essa variável desliga essa checagem estrita. SEM
# isso, "Entrar com Google" falha silenciosamente com a mensagem
# genérica "Não consegui confirmar sua conta Google agora" -- precisa
# ser definida ANTES de qualquer client OAuth ser criado, por isso fica
# aqui no topo do config.py (o primeiro arquivo carregado pelo app).
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class Config:
    # --- WhatsApp Cloud API (Meta oficial) ---
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")

    # --- Claude API (Anthropic) ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # --- OpenAI API (GPT-5.6) — provedor usado por padrão no serviço pago
    # de assistente de IA pros clientes (ver app/services/ia_uso_service.py).
    # Decidido com o Paulo em 03/09/2026: GPT-5.6 Luna (o mais barato) pra
    # quase tudo (secretaria, WhatsApp, agenda, financeiro, recibos,
    # perguntas gerais); GPT-5.6 Sol só pra análise de prontuário/exame
    # quando o caso realmente precisa de raciocínio mais forte. ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    # Confira o nome/preço atual em https://platform.openai.com/docs/models
    # antes de ativar pra valer — modelo padrão pra quase tudo: o mais
    # barato da família (Luna).
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

    # Modelo mais forte (e mais caro), usado só quando o caso não é tão
    # simples: análise de prontuário com alerta crítico detectado pela
    # camada de segurança, ou que precisou buscar evidência no PubMed
    # (ver assistente_medico_ia_service.py -> _modelo_complexo_para).
    OPENAI_MODEL_PRONTUARIO_COMPLEXO = os.getenv("OPENAI_MODEL_PRONTUARIO_COMPLEXO", "gpt-5.6-sol")

    # --- Gemini API (Google) — opção alternativa, não usada por padrão
    # desde a virada pra OpenAI (03/09/2026). Fica disponível caso queira
    # trocar algum módulo de volta pra Gemini. ---
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    # Confira o nome/preço do modelo mais barato disponível em
    # https://ai.google.dev/gemini-api/docs/pricing antes de ativar pra valer.
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    GEMINI_MODEL_PRONTUARIO_COMPLEXO = os.getenv("GEMINI_MODEL_PRONTUARIO_COMPLEXO", "gemini-3.5-flash")
    # Se o Módulo 7/8 estiver rodando no Claude, o "modelo forte" pra esses
    # mesmos casos (Sonnet já é robusto, mas deixo configurável caso queira
    # usar um modelo ainda mais cuidadoso).
    CLAUDE_MODEL_PRONTUARIO_COMPLEXO = os.getenv("CLAUDE_MODEL_PRONTUARIO_COMPLEXO", "claude-sonnet-4-6")

    # --- Qual provedor de IA cada módulo usa: 'openai', 'claude' ou 'gemini' ---
    # (ver app/services/ai_provider.py -> obter_provider). Padrão: OpenAI
    # (GPT-5.6 Luna/Sol) em todos os módulos do serviço pago de IA — troque
    # pra 'claude' ou 'gemini' módulo por módulo se preferir, mas então
    # configure a respectiva chave (ANTHROPIC_API_KEY/GEMINI_API_KEY).
    IA_PROVEDOR_SECRETARIA = os.getenv("IA_PROVEDOR_SECRETARIA", "openai")
    IA_PROVEDOR_PRONTUARIO = os.getenv("IA_PROVEDOR_PRONTUARIO", "openai")
    IA_PROVEDOR_FINANCEIRO = os.getenv("IA_PROVEDOR_FINANCEIRO", "openai")

    # --- Banco de dados (Neon — Postgres serverless) ---
    # Migrado do Supabase em 10/09/2026 (pedido do Paulo). DATABASE_URL é a
    # "connection string" que o Neon mostra na tela do projeto, algo como:
    #   postgresql://usuario:senha@ep-xxxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
    # Cole ela inteira aqui (ou no painel de configuração do painel.py).
    DATABASE_URL = os.getenv("DATABASE_URL")

    # --- Neon Object Storage (fotos dos consultórios) ---
    # Substitui o Supabase Storage. Veja app/services/neon_storage.py.
    # Todos esses 5 valores vêm da tela "Object Storage" do seu projeto no
    # Neon Console (e da API de credenciais -- veja INSTALAR.md).
    NEON_S3_ENDPOINT_URL = os.getenv("NEON_S3_ENDPOINT_URL")
    NEON_S3_REGION = os.getenv("NEON_S3_REGION", "us-east-2")
    NEON_S3_ACCESS_KEY_ID = os.getenv("NEON_S3_ACCESS_KEY_ID")
    NEON_S3_SECRET_ACCESS_KEY = os.getenv("NEON_S3_SECRET_ACCESS_KEY")
    NEON_S3_BUCKET = os.getenv("NEON_S3_BUCKET", "lifemax-reserva-horas")

    # --- Email (notificação aos funcionários quando um turno é escolhido) ---
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    EMAIL_FROM = os.getenv("EMAIL_FROM")

    # --- Asaas (PIX) ---
    ASAAS_API_KEY = os.getenv("ASAAS_API_KEY")
    ASAAS_ENV = os.getenv("ASAAS_ENV", "sandbox")  # "sandbox" ou "production"
    ASAAS_WEBHOOK_TOKEN = os.getenv("ASAAS_WEBHOOK_TOKEN")  # token que você define e configura no Asaas

    # --- Emissão de Nota Fiscal (NFS-e) da Lifemax pros médicos ---
    # Certificado A1 da PRÓPRIA LIFEMAX (emitente), usado pra emitir a nota
    # cobrada do médico pelo aluguel do consultório/sala -- ver
    # app/services/nfe_service.py. Enquanto essas 3 variáveis não estiverem
    # preenchidas, o botão "Emitir NF" mostra uma mensagem clara em vez de
    # quebrar (mesmo padrão do SMTP/Google Calendar).
    NFE_A1_CERTIFICADO_PATH = os.getenv("NFE_A1_CERTIFICADO_PATH")  # caminho do .pfx/.p12
    NFE_A1_SENHA = os.getenv("NFE_A1_SENHA")
    NFE_CNPJ_EMISSOR = os.getenv("NFE_CNPJ_EMISSOR")  # CNPJ da Lifemax que emite a nota

    @classmethod
    def asaas_base_url(cls):
        if cls.ASAAS_ENV == "production":
            return "https://api.asaas.com/v3"
        return "https://sandbox.asaas.com/api/v3"


    # --- Painel administrativo ---
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    ADMIN_PHONE = os.getenv("ADMIN_PHONE")  # formato E.164 sem '+', ex: 5531999999999 — recebe alertas de segurança
    # ⚠️ SEM valor padrão de propósito (corrigido na revisão de produção de
    # 10/09/2026): antes tinha um default fixo ("troque-esta-chave-em-
    # producao") -- se alguém esquecesse de configurar essa variável no
    # Render, o servidor subia normalmente só que com essa mesma chave
    # PÚBLICA (está aqui, neste arquivo) assinando a sessão de todo mundo,
    # o que permite forjar cookie de sessão de qualquer usuário, inclusive
    # admin. Agora, sem essa variável configurada, Config.validate() abaixo
    # recusa o servidor subir -- é melhor não subir do que subir inseguro.
    FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")

    # --- Google Calendar (integração de agenda) ---
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")  # ex: http://localhost:5000/google/callback

    # --- Login do médico com conta Google ---
    # Reaproveita o MESMO Client ID/Secret do Google Calendar acima (mesmo
    # projeto no Google Cloud Console) -- só o redirect_uri é diferente,
    # porque é um fluxo separado (entrar no sistema, não conectar a agenda).
    GOOGLE_LOGIN_REDIRECT_URI = os.getenv("GOOGLE_LOGIN_REDIRECT_URI")  # ex: http://localhost:5000/login/google/callback

    # --- Google Sheets (planilha de médicos, Módulo 2) — Conta de Serviço ---
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")  # caminho pro arquivo .json baixado
    PLANILHA_MEDICOS_ID = os.getenv("PLANILHA_MEDICOS_ID")  # o ID que aparece na URL da planilha

    # --- Rede Lifemax: link do perfil do Google Meu Negócio da Lifemax,
    # usado no botão "Avalie-nos também no Google" (perfil do médico e
    # home da Rede Lifemax). Pegue o link em "Peça avaliações" no seu
    # perfil do Google Meu Negócio (g.page/.../review) -- ver
    # PASSO_A_PASSO.md. Sem preencher, o botão simplesmente não aparece.
    GOOGLE_REVIEW_URL = os.getenv("GOOGLE_REVIEW_URL", "")

    # --- Notificação da gerente (Patricia) ---
    ADMIN_PHONE_PATRICIA = os.getenv("ADMIN_PHONE_PATRICIA")

    # --- Criptografia em repouso (prontuário e exames) ---
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

    # --- Segurança de sessão ---
    # Deixe "false" enquanto testar local (sem HTTPS). Quando hospedar
    # de verdade com HTTPS (Passo 7 do guia), mude para "true" —
    # assim o cookie de sessão só trafega criptografado.
    FORCE_HTTPS_COOKIES = os.getenv("FORCE_HTTPS_COOKIES", "false").lower() == "true"

    # --- Regras de negócio ---
    # Janela de 24h do WhatsApp: fora dela, só se pode mandar mensagens
    # usando templates pré-aprovados pela Meta.
    RECEPTION_WINDOW_HOURS = 24

    @classmethod
    def validate(cls):
        # Exige o mínimo pro sistema subir com segurança. O assistente de
        # WhatsApp e o envio de email checam suas próprias credenciais na
        # hora de usar (assim dá pra rodar só a grade de turnos sem
        # configurar tudo) -- mas DATABASE_URL (sem ela, nada funciona,
        # é a conexão com o banco Neon), FLASK_SECRET_KEY (sem valor
        # próprio, cookie de sessão fica forjável -- ver comentário acima)
        # e ADMIN_PASSWORD (sem ela, /admin fica acessível a qualquer um
        # que tente logar sem senha nenhuma, já que a checagem de senha
        # vazia falha, mas é fácil esquecer de configurar) são exigidos
        # sempre, mesmo em teste local. NEON_S3_* (fotos dos consultórios)
        # não entra aqui de propósito -- sem essas variáveis o upload de
        # foto só mostra um erro amigável na hora de usar, não impede o
        # resto do sistema de subir e funcionar.
        required = [
            "DATABASE_URL", "FLASK_SECRET_KEY", "ADMIN_PASSWORD",
        ]
        missing = [k for k in required if not getattr(cls, k)]
        if missing:
            raise RuntimeError(
                f"Variáveis de ambiente faltando: {', '.join(missing)}. "
                "Configure o arquivo .env (veja .env.example) antes de iniciar o servidor."
            )
