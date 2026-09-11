"""
Integração com o Google Agenda (Google Calendar API) — cada médico
conecta a própria conta Google (OAuth), e o sistema passa a:
  1. Checar conflito na agenda pessoal dele antes de confirmar uma reserva
  2. Criar/atualizar/cancelar automaticamente um evento na agenda dele
     correspondente a cada reserva de consultório

Os tokens (access + refresh) ficam guardados só no banco, nunca vão
para o navegador do médico — só o backend fala com a API do Google.

Setup necessário (uma vez, feito por você no Google Cloud Console):
  1. Crie um projeto em console.cloud.google.com
  2. Ative a "Google Calendar API"
  3. Configure a tela de consentimento OAuth (tipo "Externo")
  4. Crie uma credencial "OAuth Client ID", tipo "Aplicativo Web"
  5. Em "URIs de redirecionamento autorizados", adicione a URL configurada
     em GOOGLE_REDIRECT_URI (ex: http://localhost:5000/google/callback)
  6. Copie o Client ID e Client Secret para o .env
"""
from datetime import datetime, timedelta, timezone
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import Config
from app.services.supabase_client import get_client

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarNaoConfiguradoError(Exception):
    pass


def _checar_configurado():
    if not (Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET and Config.GOOGLE_REDIRECT_URI):
        raise GoogleCalendarNaoConfiguradoError(
            "A integração com o Google Agenda ainda não está configurada. "
            "Preencha GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REDIRECT_URI "
            "no painel de credenciais (veja o README para o passo a passo no Google Cloud Console)."
        )


def _client_config():
    return {
        "web": {
            "client_id": Config.GOOGLE_CLIENT_ID,
            "client_secret": Config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [Config.GOOGLE_REDIRECT_URI],
        }
    }


def gerar_url_autorizacao(medico_id: str) -> str:
    """Monta o link para o médico autorizar o acesso — 'state' carrega o
    id do médico, para sabermos de quem é o token quando o Google
    chamar nosso /google/callback de volta."""
    _checar_configurado()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=Config.GOOGLE_REDIRECT_URI)
    url, _ = flow.authorization_url(
        access_type="offline",       # necessário para ganhar o refresh_token
        prompt="consent",             # garante que o refresh_token venha mesmo em reautorizações
        state=medico_id,
    )
    return url


def trocar_codigo_por_tokens(code: str) -> dict:
    """Troca o 'code' que o Google devolveu pela URL por access_token + refresh_token."""
    _checar_configurado()
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=Config.GOOGLE_REDIRECT_URI)
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expira_em": creds.expiry,  # datetime (UTC, sem tzinfo às vezes — tratamos abaixo)
    }


def salvar_conexao(medico_id: str, tokens: dict):
    expira_em = tokens["expira_em"]
    if expira_em and expira_em.tzinfo is None:
        expira_em = expira_em.replace(tzinfo=timezone.utc)

    get_client().table("medicos").update({
        "google_calendar_conectado": True,
        "google_access_token": tokens["access_token"],
        "google_refresh_token": tokens["refresh_token"],
        "google_token_expira_em": expira_em.isoformat() if expira_em else None,
    }).eq("id", medico_id).execute()


def desconectar(medico_id: str):
    get_client().table("medicos").update({
        "google_calendar_conectado": False,
        "google_access_token": None,
        "google_refresh_token": None,
        "google_token_expira_em": None,
    }).eq("id", medico_id).execute()


def _obter_credenciais(medico: dict) -> Credentials | None:
    """Monta o objeto de credenciais do Google a partir do que temos salvo,
    renovando o access_token automaticamente se estiver vencido."""
    if not medico.get("google_calendar_conectado") or not medico.get("google_refresh_token"):
        return None

    creds = Credentials(
        token=medico.get("google_access_token"),
        refresh_token=medico.get("google_refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=Config.GOOGLE_CLIENT_ID,
        client_secret=Config.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )

    if creds.expired or not creds.valid:
        creds.refresh(GoogleAuthRequest())
        # salva o novo access_token renovado, para não precisar renovar de novo
        # a cada chamada
        get_client().table("medicos").update({
            "google_access_token": creds.token,
            "google_token_expira_em": creds.expiry.isoformat() if creds.expiry else None,
        }).eq("id", medico["id"]).execute()

    return creds


def _servico_calendar(medico: dict):
    creds = _obter_credenciais(medico)
    if creds is None:
        return None
    return build("calendar", "v3", credentials=creds)


def verificar_conflito(medico: dict, inicio_iso: str, fim_iso: str) -> bool:
    """
    True se já existe algum evento na agenda pessoal do médico que
    sobrepõe esse intervalo. Se o médico não tiver conectado o Google
    Agenda, retorna False (não bloqueia — a checagem é só um bônus
    quando disponível, o sistema de reservas já tem sua própria trava
    de conflito independente disso).
    """
    servico = _servico_calendar(medico)
    if servico is None:
        return False

    calendar_id = medico.get("google_calendar_id") or "primary"
    resultado = servico.events().list(
        calendarId=calendar_id,
        timeMin=inicio_iso,
        timeMax=fim_iso,
        singleEvents=True,
    ).execute()

    eventos = resultado.get("items", [])
    return len(eventos) > 0


def criar_evento(medico: dict, titulo: str, inicio_iso: str, fim_iso: str, descricao: str = "") -> str | None:
    """Cria o evento na agenda do médico e retorna o ID do evento (para poder atualizar/cancelar depois)."""
    servico = _servico_calendar(medico)
    if servico is None:
        return None

    calendar_id = medico.get("google_calendar_id") or "primary"
    evento = servico.events().insert(calendarId=calendar_id, body={
        "summary": titulo,
        "description": descricao,
        "start": {"dateTime": inicio_iso},
        "end": {"dateTime": fim_iso},
    }).execute()
    return evento.get("id")


def cancelar_evento(medico: dict, evento_id: str):
    servico = _servico_calendar(medico)
    if servico is None or not evento_id:
        return
    calendar_id = medico.get("google_calendar_id") or "primary"
    try:
        servico.events().delete(calendarId=calendar_id, eventId=evento_id).execute()
    except Exception as e:
        print(f"[google_calendar] Erro ao cancelar evento {evento_id}: {e}")


def atualizar_evento(medico: dict, evento_id: str, titulo: str, inicio_iso: str,
                      fim_iso: str, descricao: str = "") -> bool:
    """Atualiza um evento já existente na Google Agenda. Retorna True se conseguiu."""
    servico = _servico_calendar(medico)
    if servico is None or not evento_id:
        return False
    calendar_id = medico.get("google_calendar_id") or "primary"
    try:
        servico.events().patch(calendarId=calendar_id, eventId=evento_id, body={
            "summary": titulo,
            "description": descricao,
            "start": {"dateTime": inicio_iso},
            "end": {"dateTime": fim_iso},
        }).execute()
        return True
    except Exception as e:
        print(f"[google_calendar] Erro ao atualizar evento {evento_id}: {e}")
        return False
