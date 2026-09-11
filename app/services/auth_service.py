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
    session.pop("prontuario_2fa_verificado_medico_id", None)


def medico_logado_id() -> str | None:
    return session.get("medico_id")


def login_admin():
    session["admin"] = True


def logout_admin():
    session.pop("admin", None)


def admin_logado() -> bool:
    return session.get("admin", False)


def requer_login_medico(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not medico_logado_id():
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


def requer_admin(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not admin_logado():
            return redirect(url_for("admin.admin_login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


def login_secretaria(secretaria_id: str):
    session["secretaria_id"] = secretaria_id
    session.pop("andar_secretaria", None)  # plantão novo -- força escolher o andar de novo


def logout_secretaria():
    session.pop("secretaria_id", None)
    session.pop("andar_secretaria", None)


def secretaria_logada_id() -> str | None:
    return session.get("secretaria_id")


def andar_secretaria_logada() -> str | None:
    return session.get("andar_secretaria")


def definir_andar_secretaria(andar: str):
    session["andar_secretaria"] = andar


def requer_secretaria(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not secretaria_logada_id():
            return redirect(url_for("secretaria_auth.login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper


def requer_secretaria_ou_admin(view_func):
    """Pras rotas da tela 'Agenda Fixos' -- tanto o admin (senha única)
    quanto qualquer secretária com login próprio têm acesso completo a
    essa tela (agenda, crédito de horas de horista, matriz de liberação
    e relatórios). O resto do painel admin (preços, cadastro de médico,
    backup, módulos, notas fiscais, fotos) continua só com @requer_admin.

    Toda secretária (não o admin) precisa ter escolhido o andar que está
    atendendo nesse plantão antes de entrar aqui -- é o que decide pra
    qual painel de chamadas ela recebe o aviso vermelho quando um médico
    chama um paciente. Se ainda não escolheu (login novo, ou sessão
    antiga de antes dessa função existir), manda pra tela de escolher
    andar antes de continuar."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not admin_logado() and not secretaria_logada_id():
            return redirect(url_for("admin.admin_login", next=request.path))
        if secretaria_logada_id() and not andar_secretaria_logada():
            return redirect(url_for("secretaria_auth.escolher_andar", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper
