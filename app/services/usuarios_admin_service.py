"""Usuários do painel admin (22/10/2026): cadastro, bloqueio, login e link de acesso.
Só quem está aqui, ativo, entra nas páginas /admin."""
import hashlib
import re
import secrets
from datetime import datetime, timezone

from app.services.supabase_client import get_client
from app.services import auth_service, email_service

# Link de acesso NÃO expira e pode ser usado quantas vezes for preciso (pedido do Paulo em 22/10/2026).
_EXPIRA = datetime(2099, 12, 31, tzinfo=timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalizar_tel(tel: str) -> str:
    return re.sub(r"\D", "", tel or "")


_AVISO_TABELA = "Tabela de usuários do admin não encontrada no banco. Rode sql/migration_usuarios_admin.sql no Neon."


def tabela_ok() -> bool:
    try:
        get_client().table("usuarios_admin").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def listar() -> list[dict]:
    try:
        return get_client().table("usuarios_admin").select("*").order("nome").execute().data or []
    except Exception:
        return []  # tabela ainda não criada: login cai no modo de transição (senha antiga)


def buscar_por_id(usuario_id: str) -> dict | None:
    try:
        r = get_client().table("usuarios_admin").select("*").eq("id", usuario_id).execute().data
    except Exception:
        return None
    return r[0] if r else None


def contar_ativos() -> int:
    """Usuários ativos que JÁ criaram senha (só esses conseguem entrar). Enquanto for 0, a senha
    antiga do admin continua valendo -- assim ninguém fica trancado antes do 1º usuário ter senha."""
    try:
        r = get_client().table("usuarios_admin").select("id,senha_hash").eq("ativo", True).execute().data
    except Exception:
        return 0  # tabela inexistente = nenhum usuário cadastrado
    return len([u for u in (r or []) if u.get("senha_hash")])


def criar(nome: str, email: str, telefone: str) -> dict:
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    if not nome:
        raise ValueError("Informe o nome.")
    if "@" not in email:
        raise ValueError("Digite um e-mail válido.")
    if not tabela_ok():
        raise ValueError(_AVISO_TABELA)
    if any((u.get("email") or "").lower() == email for u in listar()):
        raise ValueError("Já existe um usuário com esse e-mail.")
    r = get_client().table("usuarios_admin").insert({
        "nome": nome, "email": email, "telefone": _normalizar_tel(telefone), "ativo": True,
    }).execute()
    return r.data[0]


def definir_ativo(usuario_id: str, ativo: bool) -> None:
    get_client().table("usuarios_admin").update({"ativo": ativo}).eq("id", usuario_id).execute()


def autenticar(identificador: str, senha: str) -> dict | None:
    ident = (identificador or "").strip().lower()
    if not ident or not senha:
        return None
    tel = _normalizar_tel(ident)
    for u in listar():
        if not u.get("ativo") or not u.get("senha_hash"):
            continue
        confere = (u.get("email") or "").lower() == ident or (
            "@" not in ident and tel and _normalizar_tel(u.get("telefone")) == tel)
        if confere and auth_service.verificar_senha(senha, u["senha_hash"]):
            return u
    return None


def enviar_link(usuario_id: str) -> dict:
    u = buscar_por_id(usuario_id)
    if not u:
        raise ValueError("Usuário não encontrado.")
    token = secrets.token_urlsafe(32)
    get_client().table("tokens_admin_usuarios").insert({
        "usuario_id": usuario_id,
        "token_hash": _hash_token(token),
        "expira_em": _EXPIRA.isoformat(),
    }).execute()
    from flask import url_for
    link = url_for("admin.definir_senha", token=token, _external=True)
    enviado = email_service.notificar_acesso_admin(u["nome"], link, u["email"])
    return {"enviado": enviado, "link": link, "email": u["email"]}


def validar_token(token: str) -> dict | None:
    if not token:
        return None
    r = get_client().table("tokens_admin_usuarios").select("*").eq("token_hash", _hash_token(token)).execute().data
    if not r:
        return None
    exp = r[0]["expira_em"]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        return None
    return r[0]


def definir_senha(token: str, nova_senha: str) -> bool:
    reg = validar_token(token)
    if reg is None:
        return False
    get_client().table("usuarios_admin").update(
        {"senha_hash": auth_service.gerar_hash_senha(nova_senha)}).eq("id", reg["usuario_id"]).execute()
    return True
