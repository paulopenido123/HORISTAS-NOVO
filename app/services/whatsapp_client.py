"""
Cliente para a WhatsApp Cloud API (Meta oficial).
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api

IMPORTANTE sobre a janela de 24h:
- Se o médico mandou mensagem nas últimas 24h, você pode responder
  com texto/imagem livre.
- Se você quer INICIAR uma conversa (ex: lembrete automático), precisa
  usar um "template" pré-aprovado pela Meta. Isso é configurado no
  Meta Business Manager, não aqui no código.
"""
import requests
from app.config import Config

BASE_URL = f"https://graph.facebook.com/{Config.WHATSAPP_API_VERSION}/{Config.WHATSAPP_PHONE_NUMBER_ID}"


def _headers():
    return {
        "Authorization": f"Bearer {Config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def send_text(to: str, body: str) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    resp = requests.post(f"{BASE_URL}/messages", headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_image(to: str, image_url: str, caption: str = "") -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }
    resp = requests.post(f"{BASE_URL}/messages", headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_document(to: str, document_url: str, filename: str = "documento.pdf", caption: str = "") -> dict:
    """Envia um arquivo (ex: PDF de nota fiscal) como documento no WhatsApp."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"link": document_url, "filename": filename, "caption": caption},
    }
    resp = requests.post(f"{BASE_URL}/messages", headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_template(to: str, template_name: str, language_code: str = "pt_BR", components: list | None = None) -> dict:
    """
    Envia mensagem via template aprovado (necessário para iniciar
    conversa fora da janela de 24h — ex: lembretes automáticos).
    O template precisa já existir e estar aprovado no Meta Business Manager.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
    }
    if components:
        payload["template"]["components"] = components

    resp = requests.post(f"{BASE_URL}/messages", headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def download_media(media_id: str) -> tuple[bytes, str]:
    """
    Baixa um arquivo de mídia (áudio, imagem, etc.) enviado pelo usuário.
    A WhatsApp Cloud API funciona em 2 passos: primeiro pega a URL
    temporária do arquivo, depois baixa o conteúdo de fato.
    Retorna: (bytes_do_arquivo, mime_type)
    """
    # Passo 1: pega a URL temporária do arquivo
    resp = requests.get(
        f"https://graph.facebook.com/{Config.WHATSAPP_API_VERSION}/{media_id}",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    info = resp.json()
    url_arquivo = info["url"]
    mime_type = info.get("mime_type", "application/octet-stream")

    # Passo 2: baixa o conteúdo de fato (a URL exige o mesmo token de autenticação)
    resp_arquivo = requests.get(url_arquivo, headers=_headers(), timeout=30)
    resp_arquivo.raise_for_status()
    return resp_arquivo.content, mime_type


def extract_incoming_message(webhook_payload: dict) -> dict | None:
    """
    Extrai a mensagem recebida do payload bruto do webhook da Meta.
    Retorna None se o payload não contiver uma mensagem reconhecida (ex: status update).
    """
    try:
        entry = webhook_payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        if "messages" not in value:
            return None  # provavelmente é um status update (delivered/read), ignora

        message = value["messages"][0]
        from_number = message["from"]  # já vem em E.164 sem '+'
        msg_type = message["type"]

        text = None
        media_id = None

        if msg_type == "text":
            text = message["text"]["body"]
        elif msg_type == "audio":
            media_id = message["audio"]["id"]
        elif msg_type == "interactive":
            # resposta de botão/lista
            interactive = message["interactive"]
            if interactive["type"] == "button_reply":
                text = interactive["button_reply"]["title"]
            elif interactive["type"] == "list_reply":
                text = interactive["list_reply"]["title"]

        return {"from": from_number, "type": msg_type, "text": text, "media_id": media_id, "raw": message}
    except (KeyError, IndexError):
        return None
