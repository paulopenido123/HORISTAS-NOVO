"""
Autenticação de médicos (login por telefone + senha) e do admin
(senha única, definida no .env). Usa hash de senha do Werkzeug (já vem
junto com o Flask, não precisa instalar nada a mais).
"""
from functools import wraps
from flask import session, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash
from app.config import Config


def gerar_hash_senha(senha_texto_puro: str) -> str:
    return generate_password_hash(senha_texto_puro)


def verificar_senha(senha_texto_puro: str, hash_salvo: str) -> bool:
    if not hash_salvo:
        return False
    return check_password_hash(hash_salvo, senha_texto_puro)


def login_medico(medico_id: str):
    session["medico_id"] = medico_id


def logout_medico():
    session.pop("medico_id", None)
    session.pop("lembrar", None)
    session.pop("prontuario_2fa_verificado_medico_id", None)


def medico_logado_id() -> str | None:
    return session.get("medico_id")


def login_admin(usuario_id: str | None = None):
    session["admin"] = True
    if usuario_id:
        session["admin_usuario_id"] = usuario_id
    else:
        session.pop("admin_usuario_id", None)


def logout_admin():
    session.pop("admin", None)
    session.pop("admin_usuario_id", None)
    session.pop("admin_master_ate", None)


def admin_perfil() -> str | None:
    """'admin' | 'secretaria' | None (não logado/bloqueado). Só usuário cadastrado e ATIVO entra
    (conferido a cada acesso -- bloquear derruba a sessão na hora; 1 consulta por requisição).
    Transição: a senha única antiga (ADMIN_PASSWORD) só vale enquanto não existir usuário ativo
    com senha criada, e conta como 'admin'."""
    if not session.get("admin", False):
        return None
    from flask import g
    if hasattr(g, "_admin_perfil"):
        return g._admin_perfil
    from app.services import usuarios_admin_service as ua
    uid = session.get("admin_usuario_id")
    if uid:
        u = ua.buscar_por_id(uid)
        perfil = (u.get("perfil") or "admin") if (u and u.get("ativo")) else None
    else:
        perfil = "admin" if ua.contar_ativos() == 0 else None
    g._admin_perfil = perfil
    return perfil


def admin_logado() -> bool:
    return admin_perfil() is not None


def requer_login_medico(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not medico_logado_id():
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


def requer_admin_total(view_func):
    """Só o perfil Administrador (secretária fica de fora: Horas, Relatórios, Usuários, saldo)."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not admin_logado():
            return redirect(url_for("admin.admin_login", next=request.path))
        if admin_perfil() != "admin":
            from flask import abort
            abort(403)
        return view_func(*args, **kwargs)
    return wrapper


def requer_admin(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not admin_logado():
            return redirect(url_for("admin.admin_login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper
