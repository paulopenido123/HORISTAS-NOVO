"""
Login do médico com a conta Google — uma OPÇÃO A MAIS de entrar no
sistema, além do telefone + senha de sempre (não substitui nada, e não
cria médico novo por essa porta).

Como funciona: o médico clica em "Entrar com Google", autoriza no
Google, e o sistema recebe de volta só a identidade dele (e-mail e
nome) -- nunca uma senha. A gente então procura um médico JÁ
CADASTRADO cujo e-mail (campo preenchido no cadastro dele) seja
exatamente esse. Se achar, loga. Se não achar (ou se o e-mail estiver
cadastrado em mais de um médico ao mesmo tempo, o que seria um erro de
cadastro), bloqueia e explica o motivo -- nunca cria um cadastro novo
por aqui, porque o telefone é obrigatório pro assistente de WhatsApp, e
uma conta Google não tem telefone nenhum pra gente aproveitar.

Setup necessário (uma vez, feito por você no Google Cloud Console) --
ver PASSO_A_PASSO.md, seção "Login do médico com Google":
  1. Se você já configurou o Google Agenda (Módulo de agenda pessoal),
     é o MESMO projeto e o MESMO Client ID/Secret -- só precisa
     acrescentar mais uma "URI de redirecionamento autorizada".
  2. Se ainda não configurou nada de Google, crie um projeto em
     console.cloud.google.com, configure a tela de consentimento OAuth
     (tipo "Externo") e crie uma credencial "OAuth Client ID" tipo
     "Aplicativo Web".
  3. Em "URIs de redirecionamento autorizados", adicione a URL
     configurada em GOOGLE_LOGIN_REDIRECT_URI (ex:
     http://localhost:5000/login/google/callback).
  4. Copie o Client ID e Client Secret pro .env (GOOGLE_CLIENT_ID e
     GOOGLE_CLIENT_SECRET -- os mesmos usados pelo Google Agenda) e
     preencha GOOGLE_LOGIN_REDIRECT_URI.
"""
import requests
from google_auth_oauthlib.flow import Flow

from app.config import Config

# Só pedimos identidade (e-mail e nome) -- bem diferente do escopo do
# Google Agenda (que pede acesso de leitura/escrita na agenda). Login
# nunca precisa, e nunca ganha, acesso à agenda do médico.
SCOPES_LOGIN = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class GoogleLoginNaoConfiguradoError(Exception):
    pass


def _checar_configurado():
    if not (Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET and Config.GOOGLE_LOGIN_REDIRECT_URI):
        raise GoogleLoginNaoConfiguradoError(
            "O login com Google ainda não está configurado nesse sistema. Peça pro administrador "
            "preencher GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_LOGIN_REDIRECT_URI (veja o "
            "passo a passo no Google Cloud Console)."
        )


def _client_config():
    return {
        "web": {
            "client_id": Config.GOOGLE_CLIENT_ID,
            "client_secret": Config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [Config.GOOGLE_LOGIN_REDIRECT_URI],
        }
    }


def gerar_url_autorizacao() -> str:
    """Monta o link do botão "Entrar com Google" -- manda o médico pro
    Google escolher/confirmar a conta."""
    _checar_configurado()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES_LOGIN, redirect_uri=Config.GOOGLE_LOGIN_REDIRECT_URI)
    url, _ = flow.authorization_url(prompt="select_account")
    return url


def obter_identidade_da_conta(code: str) -> dict:
    """Troca o 'code' que o Google devolveu pela URL por um token, e usa
    esse token só pra perguntar ao Google 'qual é o e-mail e o nome
    dessa conta' -- nunca guardamos esse token (ele não dá acesso a
    nada além da identidade, e o login no nosso sistema usa a sessão
    do Flask de sempre, igual ao login por telefone/senha)."""
    _checar_configurado()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES_LOGIN, redirect_uri=Config.GOOGLE_LOGIN_REDIRECT_URI)
    flow.fetch_token(code=code)
    creds = flow.credentials

    resp = requests.get(_USERINFO_URL, headers={"Authorization": f"Bearer {creds.token}"}, timeout=10)
    resp.raise_for_status()
    dados = resp.json()

    return {
        "email": (dados.get("email") or "").strip().lower(),
        "nome": dados.get("name") or "",
        "email_verificado": bool(dados.get("email_verified")),
    }
