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


def admin_logado() -> bool:
    """Só usuário admin cadastrado e ATIVO entra (conferido a cada acesso, então
    bloquear um usuário derruba a sessão dele na hora). Exceção de transição: a
    senha única antiga (ADMIN_PASSWORD) só vale enquanto não existir nenhum
    usuário ativo com senha criada -- evita ficar trancado do lado de fora."""
    if not session.get("admin", False):
        return False
    from app.services import usuarios_admin_service as ua
    uid = session.get("admin_usuario_id")
    if uid:
        u = ua.buscar_por_id(uid)
        return bool(u and u.get("ativo"))
    return ua.contar_ativos() == 0


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
