"""
"Esqueci minha senha" por e-mail -- médico e secretária (ver
sql/migration_recuperacao_senha.sql). O admin fica de fora desse fluxo:
a senha dele é a variável ADMIN_PASSWORD no Render, trocada direto lá,
sem cadastro de e-mail nem tela de recuperação própria.

Fluxo:
  1. solicitar_recuperacao(tipo, telefone) -- se o telefone existir e
     tiver e-mail cadastrado, gera um token (secrets.token_urlsafe),
     guarda só o HASH sha256 dele (nunca o token em si) com validade de
     30 minutos, e manda por e-mail o link de redefinição. A tela que
     chama essa função sempre mostra a mesma mensagem genérica pra quem
     pediu, esteja o telefone cadastrado ou não -- assim ninguém
     descobre, tentando telefones ao acaso, quais estão cadastrados.
  2. validar_token(token) -- confere se um token ainda é válido (existe,
     não expirou, não foi usado). Usado tanto pra mostrar a tela de
     redefinição quanto dentro de redefinir_senha().
  3. redefinir_senha(token, nova_senha) -- troca a senha do dono do
     token e marca o token como usado (um link só serve uma vez).
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from app.services.supabase_client import get_client
from app.services import auth_service
from app.services import email_service

_VALIDADE_MINUTOS = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _buscar_usuario(tipo: str, telefone: str) -> dict | None:
    if tipo == "medico":
        from app.services import supabase_client as db
        return db.get_medico_by_telefone(telefone)
    if tipo == "secretaria":
        from app.services import secretarias_service as sec_db
        return sec_db.get_secretaria_by_telefone(telefone)
    return None


def solicitar_recuperacao(tipo: str, telefone: str) -> None:
    """Não devolve nada e nunca levanta erro por telefone não encontrado
    ou sem e-mail cadastrado -- a tela sempre mostra a mesma mensagem
    genérica pra quem pediu, independente do que aconteceu aqui dentro."""
    telefone = (telefone or "").strip()
    if tipo not in ("medico", "secretaria") or not telefone:
        return

    usuario = _buscar_usuario(tipo, telefone)
    if usuario is None or not usuario.get("email"):
        return

    token = secrets.token_urlsafe(32)
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=_VALIDADE_MINUTOS)

    get_client().table("tokens_recuperacao_senha").insert({
        "tipo": tipo,
        "usuario_id": usuario["id"],
        "token_hash": _hash_token(token),
        "expira_em": expira_em.isoformat(),
        "contexto": "recuperacao",
    }).execute()

    from flask import url_for
    rota = "auth.redefinir_senha" if tipo == "medico" else "secretaria_auth.redefinir_senha"
    link = url_for(rota, token=token, _external=True)

    email_service.notificar_recuperacao_senha(usuario.get("nome", ""), link, usuario["email"])


_VALIDADE_HORAS_PRIMEIRO_ACESSO = 48


def enviar_link_primeiro_acesso(medico_id: str, email: str) -> dict:
    """Admin manda um link direto pra um médico JÁ CADASTRADO criar a
    senha de acesso dele pela primeira vez -- sem passar pela tela
    pública de "Primeiro acesso" (que pede pro médico digitar o próprio
    telefone e, se ele digitar diferente do que já está no sistema,
    cria um cadastro NOVO por engano, duplicando o médico). Aqui o link
    já nasce amarrado ao medico_id certo, então não tem como duplicar.

    Se o e-mail digitado for diferente do que já está salvo, atualiza o
    cadastro do médico com esse e-mail (é o mesmo que vai receber o
    link, faz sentido ficar salvo). Levanta ValueError se o médico não
    existir ou o e-mail vier vazio.

    Devolve {"enviado": bool, "link": str} -- "enviado" é True se o
    e-mail foi mesmo mandado, False se o token foi criado mas o envio
    falhou (ex: SMTP_*/EMAIL_FROM não configurados em .env --
    `email_service.enviar_email` não levanta erro nesse caso, só devolve
    False). "link" sempre vem preenchido (o token já existe e é válido
    mesmo quando o envio falha), pra quem chamar poder mostrar/copiar na
    mão enquanto o e-mail não está configurado."""
    from app.services import supabase_client as db

    medico = db.get_medico_by_id(medico_id)
    if medico is None:
        raise ValueError("Médico não encontrado.")

    email = (email or "").strip()
    if not email or "@" not in email:
        raise ValueError("Digite um e-mail válido.")

    if email != (medico.get("email") or ""):
        db.atualizar_medico(
            medico_id, medico["nome"], medico["telefone"], medico.get("especialidade") or "",
            cpf_cnpj=medico.get("cpf_cnpj") or "", email=email,
        )

    token = secrets.token_urlsafe(32)
    expira_em = datetime.now(timezone.utc) + timedelta(hours=_VALIDADE_HORAS_PRIMEIRO_ACESSO)

    get_client().table("tokens_recuperacao_senha").insert({
        "tipo": "medico",
        "usuario_id": medico_id,
        "token_hash": _hash_token(token),
        "expira_em": expira_em.isoformat(),
        "contexto": "primeiro_acesso",
    }).execute()

    from flask import url_for
    link = url_for("auth.redefinir_senha", token=token, _external=True)
    enviado = email_service.notificar_primeiro_acesso(medico["nome"], link, email)
    return {"enviado": enviado, "link": link}


_VALIDADE_HORAS_CONFIRMACAO_EMAIL = 72


def enviar_confirmacao_email(medico_id: str, email: str) -> None:
    """Item 1 (pedido do Paulo em 11/09/2026): manda o link de
    confirmação de e-mail pro médico -- chamado pelo admin sempre que
    cadastra ou altera o e-mail de um médico (Clientes > Inserir novo /
    Editar dados). Não devolve nada e não levanta erro se o SMTP não
    estiver configurado (mesmo padrão de sempre -- `enviar_email` só
    devolve False nesse caso, não quebra o cadastro)."""
    if not email:
        return

    token = secrets.token_urlsafe(32)
    expira_em = datetime.now(timezone.utc) + timedelta(hours=_VALIDADE_HORAS_CONFIRMACAO_EMAIL)

    get_client().table("tokens_recuperacao_senha").insert({
        "tipo": "medico",
        "usuario_id": medico_id,
        "token_hash": _hash_token(token),
        "expira_em": expira_em.isoformat(),
        "contexto": "confirmar_email",
    }).execute()

    from flask import url_for
    from app.services import supabase_client as db
    medico = db.get_medico_by_id(medico_id)
    link = url_for("auth.confirmar_email", token=token, _external=True)
    email_service.notificar_confirmar_email(medico.get("nome", "") if medico else "", link, email)


def confirmar_email(token: str) -> dict | None:
    """Chamada pela rota pública /confirmar-email/<token> (ver
    app/routes/auth.py). Marca `email_confirmado=True` no médico dono do
    token e devolve o médico atualizado -- ou None se o token for
    inválido, expirado, já usado, ou não for desse contexto (ex: alguém
    tentando usar um token de recuperação de senha aqui)."""
    registro = validar_token(token)
    if registro is None or registro.get("contexto") != "confirmar_email" or registro["tipo"] != "medico":
        return None

    from app.services import supabase_client as db
    medico = db.definir_email_confirmado(registro["usuario_id"], True)
    get_client().table("tokens_recuperacao_senha").update({"usado": True}).eq("id", registro["id"]).execute()
    return medico


def validar_token(token: str) -> dict | None:
    """Devolve a linha do token (com 'tipo' e 'usuario_id') se ainda for
    válido -- existe, não expirou e não foi usado -- ou None."""
    if not token:
        return None

    resp = (
        get_client()
        .table("tokens_recuperacao_senha")
        .select("*")
        .eq("token_hash", _hash_token(token))
        .execute()
    )
    if not resp.data:
        return None

    registro = resp.data[0]
    if registro.get("usado"):
        return None

    expira_em = registro["expira_em"]
    if isinstance(expira_em, str):
        expira_em = datetime.fromisoformat(expira_em.replace("Z", "+00:00"))
    if expira_em < datetime.now(timezone.utc):
        return None

    return registro


def redefinir_senha(token: str, nova_senha: str) -> bool:
    """Troca a senha do médico/secretária dono do token e marca o token
    como usado. Devolve False se o token não existir, já tiver expirado
    ou já tiver sido usado."""
    registro = validar_token(token)
    if registro is None:
        return False

    senha_hash = auth_service.gerar_hash_senha(nova_senha)
    if registro["tipo"] == "medico":
        from app.services import creditos_service as creditos_db
        creditos_db.definir_senha_medico(registro["usuario_id"], senha_hash)
    else:
        from app.services import secretarias_service as sec_db
        sec_db.definir_senha_secretaria(registro["usuario_id"], senha_hash)

    get_client().table("tokens_recuperacao_senha").update({"usado": True}).eq("id", registro["id"]).execute()
    return True
