"""Contrato digital via Autentique (v101).

Regra de negócio (pedido do Paulo, 18/11/2026): o médico que se cadastra sozinho (`medicos.exige_contrato`)
precisa ASSINAR o contrato -- só ele assina -- para poder reservar consultório. Quem já era cliente (ou é
cadastrado pelo admin) não precisa. O PDF do contrato é gerado com os dados do médico (pdf_service) e enviado à
Autentique (API GraphQL, https://docs.autentique.com.br/api). O sistema descobre se ele assinou consultando a
Autentique sob demanda (sem webhook). AUTENTIQUE_SANDBOX=1 (padrão) cria apenas documentos de teste.
"""
import json
import re
import requests
from app.config import Config
from app.services import supabase_client as db
from app.services.supabase_client import get_client, agora_iso

URL_API = "https://api.autentique.com.br/v2/graphql"


class AutentiqueErro(Exception):
    """Falha ao falar com a Autentique (mensagem em português, pronta para mostrar)."""


def modo_teste() -> bool:
    return bool(Config.AUTENTIQUE_SANDBOX)


def configurado() -> bool:
    return bool(Config.AUTENTIQUE_API_TOKEN)


def _headers() -> dict:
    if not configurado():
        raise AutentiqueErro("A assinatura digital ainda não está configurada no sistema (falta AUTENTIQUE_API_TOKEN).")
    return {"Authorization": f"Bearer {Config.AUTENTIQUE_API_TOKEN}"}


def _erros(resp_json: dict) -> str | None:
    erros = resp_json.get("errors")
    if erros:
        return "; ".join(str(e.get("message", e)) for e in erros)[:300]
    return None


def criar_documento(pdf_bytes: bytes, nome_documento: str, nome: str, email: str) -> dict:
    """Cria o documento com UM signatário (o médico). Devolve {"id": str, "link": str | None}."""
    sandbox = ", sandbox: true" if Config.AUTENTIQUE_SANDBOX else ""
    query = ("mutation($document: DocumentInput!, $signers: [SignerInput!]!, $file: Upload!) { "
             f"createDocument(document: $document, signers: $signers, file: $file{sandbox}) "
             "{ id name signatures { public_id name email link { short_link } } } }")
    variables = {"document": {"name": nome_documento},
                 "signers": [{"email": email, "name": nome, "action": "SIGN"}],
                 "file": None}
    try:
        r = requests.post(
            URL_API, headers=_headers(), timeout=40,
            data={"operations": json.dumps({"query": query, "variables": variables}),
                  "map": json.dumps({"file": ["variables.file"]})},
            files={"file": ("contrato.pdf", pdf_bytes, "application/pdf")},
        )
        corpo = r.json()
    except AutentiqueErro:
        raise
    except Exception as e:
        raise AutentiqueErro(f"Não consegui falar com a Autentique agora ({type(e).__name__}). Tente de novo em instantes.")
    erro = _erros(corpo)
    doc = ((corpo.get("data") or {}).get("createDocument")) if not erro else None
    if erro or not doc:
        print(f"[autentique] erro ao criar documento: {erro or corpo}")
        raise AutentiqueErro(f"A Autentique recusou o documento: {erro or 'resposta inesperada'}")
    link = None
    for a in doc.get("signatures") or []:
        link = ((a.get("link") or {}).get("short_link")) or link
    return {"id": doc["id"], "link": link}


def consultar_assinatura(documento_id: str) -> dict:
    """Devolve {"assinado": bool, "assinado_em": str | None, "recusado": bool}."""
    query = ('query { document(id: "%s") { id signatures { public_id signed { created_at } rejected { created_at } } } }'
             % re.sub(r"[^A-Za-z0-9_-]", "", documento_id))
    try:
        r = requests.post(URL_API, headers=dict(_headers(), **{"Content-Type": "application/json"}),
                          json={"query": query}, timeout=25)
        corpo = r.json()
    except AutentiqueErro:
        raise
    except Exception as e:
        raise AutentiqueErro(f"Não consegui falar com a Autentique agora ({type(e).__name__}).")
    erro = _erros(corpo)
    doc = (corpo.get("data") or {}).get("document") if not erro else None
    if erro or not doc:
        print(f"[autentique] erro ao consultar documento: {erro or corpo}")
        raise AutentiqueErro(f"Não consegui consultar a assinatura: {erro or 'resposta inesperada'}")
    assinaturas = doc.get("signatures") or []
    feitas = [(a.get("signed") or {}).get("created_at") for a in assinaturas if a.get("signed")]
    return {
        "assinado": bool(assinaturas) and len(feitas) == len(assinaturas),
        "assinado_em": feitas[0] if feitas else None,
        "recusado": any(a.get("rejected") for a in assinaturas),
    }


def reenviar_assinaturas(documento_id: str) -> tuple[bool, str | None]:
    """Pede à Autentique para reenviar o e-mail de assinatura do documento. Devolve (ok, erro). A Autentique limita
    reenvios muito seguidos (erro too_many_resent_emails); por isso o sistema também manda o seu próprio e-mail."""
    try:
        doc_id = re.sub(r"[^A-Za-z0-9_-]", "", documento_id)
        h = dict(_headers(), **{"Content-Type": "application/json"})
        q = requests.post(URL_API, headers=h, timeout=25,
                          json={"query": 'query { document(id: "%s") { signatures { public_id } } }' % doc_id}).json()
        ids = [a["public_id"] for a in (((q.get("data") or {}).get("document") or {}).get("signatures") or []) if a.get("public_id")]
        if not ids:
            return False, "assinatura não encontrada"
        lista = ", ".join('"%s"' % re.sub(r"[^A-Za-z0-9_-]", "", i) for i in ids)
        r = requests.post(URL_API, headers=h, timeout=25, json={"query": "mutation { resendSignatures(public_ids: [%s]) }" % lista}).json()
        erro = _erros(r)
        return (not erro and bool((r.get("data") or {}).get("resendSignatures", True))), erro
    except AutentiqueErro as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}"


def _html_email_contrato(nome: str, link: str) -> str:
    primeiro = (nome or "").split()[0] if nome else ""
    return (f'<div style="font-family:Arial,sans-serif;color:#102A43;max-width:520px">'
            f'<h2 style="color:#0B3A52;margin:0 0 12px">Assinar contrato</h2>'
            f'<p>Olá{", " + primeiro if primeiro else ""}!</p>'
            f'<p>Para poder reservar consultórios na Lifemax, falta assinar o seu contrato digital. É rápido e feito pelo celular ou computador.</p>'
            f'<p style="margin:22px 0"><a href="{link}" style="background:#0EA5A0;color:#fff;text-decoration:none;font-weight:700;'
            f'padding:14px 26px;border-radius:12px;display:inline-block">Assinar contrato</a></p>'
            f'<p style="font-size:13px;color:#55707C">Se o botão não abrir, copie e cole este endereço no navegador:<br>{link}</p></div>')


def reenviar_contrato(medico_id: str) -> dict:
    """Reenvia o e-mail "Assinar contrato" quantas vezes o médico pedir. Se o documento ainda não existe, cria (a Autentique
    envia o primeiro e-mail). Se já existe: manda o e-mail do próprio sistema com o link e também pede o reenvio à
    Autentique. Devolve {"link", "email", "enviado_sistema", "enviado_autentique", "novo"}."""
    r = enviar_contrato(medico_id)  # cria se não existir; devolve o mesmo documento se já existir
    medico = db.get_medico_by_id(medico_id) or {}
    email = (medico.get("email") or "").strip()
    resultado = {"link": r.get("link"), "email": email, "novo": r["novo"], "enviado_sistema": False, "enviado_autentique": False}
    if r["novo"]:
        resultado["enviado_autentique"] = True  # a própria criação já dispara o e-mail da Autentique
        return resultado
    if resultado["link"]:
        from app.services import email_service
        try:
            resultado["enviado_sistema"] = bool(email_service.enviar_email(
                [email], "Assinar contrato — Lifemax", _html_email_contrato(medico.get("nome") or "", resultado["link"])))
        except Exception as e:
            print(f"[autentique] e-mail do contrato falhou: {e}")
    ok, erro = reenviar_assinaturas(medico["contrato_autentique_id"])
    resultado["enviado_autentique"] = ok
    if erro:
        print(f"[autentique] reenvio pela Autentique: {erro}")
    return resultado


# ---------------------------------------------------------------- regras do sistema
def contrato_pendente(medico: dict | None) -> bool:
    """True se este médico PRECISA assinar e ainda não assinou."""
    return bool(medico and medico.get("exige_contrato") and not medico.get("contrato_assinado_em"))


def enviar_contrato(medico_id: str) -> dict:
    """Gera o PDF do médico e o envia para assinatura. Não duplica: se já existe documento pendente, devolve o
    mesmo (cada documento novo gasta um dos gratuitos do mês). Levanta ValueError/AutentiqueErro."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        raise ValueError("Cadastro não encontrado.")
    if not medico.get("exige_contrato") or medico.get("contrato_assinado_em"):
        raise ValueError("Este cadastro não precisa assinar o contrato (ou já assinou).")
    if medico.get("contrato_autentique_id"):
        return {"link": medico.get("contrato_link"), "novo": False}
    email = (medico.get("email") or "").strip()
    if "@" not in email:
        raise ValueError("Cadastre um e-mail válido antes de assinar o contrato.")
    from app.services import reserva_service
    faltando = reserva_service._campos_pessoais_faltando(medico)
    if faltando:  # o contrato leva CPF, registro, endereço etc.: precisa estar tudo preenchido antes
        raise ValueError("Antes de assinar, complete seus dados em \"Meus dados\" (faltam: " + ", ".join(faltando) + ").")
    from app.services import pdf_service
    pdf = pdf_service.gerar_pdf_contrato(medico, assinatura_externa=True).getvalue()
    primeiro = (medico.get("nome") or "medico").split()[0]
    doc = criar_documento(pdf, f"Contrato Lifemax - {medico.get('nome') or primeiro}", medico.get("nome") or primeiro, email)
    dados = {"contrato_autentique_id": doc["id"], "contrato_link": doc["link"], "contrato_enviado_em": agora_iso(),
             "contrato_assinado_em": None}
    try:
        get_client().table("medicos").update({**dados, "contrato_sandbox": bool(Config.AUTENTIQUE_SANDBOX)}).eq("id", medico_id).execute()
    except Exception as e:
        if getattr(e, "pgcode", None) != "42703":
            raise
        # migração v107 ainda não rodada: grava sem a marca (o documento já foi criado na Autentique)
        get_client().table("medicos").update(dados).eq("id", medico_id).execute()
    return {"link": doc["link"], "novo": True}


def atualizar_status(medico_id: str) -> dict:
    """Consulta a Autentique e, se o médico assinou, grava a data (libera a parte do contrato na reserva).
    Devolve {"assinado": bool, "recusado": bool}."""
    medico = db.get_medico_by_id(medico_id)
    if not medico or not medico.get("contrato_autentique_id"):
        return {"assinado": bool(medico and medico.get("contrato_assinado_em")), "recusado": False}
    if medico.get("contrato_assinado_em"):
        return {"assinado": True, "recusado": False}
    st = consultar_assinatura(medico["contrato_autentique_id"])
    if st["assinado"]:
        get_client().table("medicos").update(
            {"contrato_assinado_em": st["assinado_em"] or agora_iso()}).eq("id", medico_id).execute()
    return {"assinado": st["assinado"], "recusado": st["recusado"]}
