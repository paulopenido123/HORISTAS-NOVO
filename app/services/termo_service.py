"""
Extensão do auth_service para o gate do Termo de Uso: todo médico
precisa ter aceitado o termo antes de acessar o painel. Fica separado
do auth_service.py principal só para não misturar responsabilidades
(login vs. aceite contratual).
"""
from functools import wraps
from flask import session, redirect, url_for, request
from app.services.auth_service import medico_logado_id


def medico_precisa_aceitar_termo(medico: dict) -> bool:
    return not medico.get("termo_aceito", False)


def requer_termo_aceito(view_func):
    """
    Use junto com @requer_login_medico (nessa ordem: login primeiro,
    depois termo). Redireciona para a tela do termo se ainda não foi
    aceito, preservando a página que o médico queria acessar.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        from app.services import supabase_client as db
        medico_id = medico_logado_id()
        if medico_id:
            medico = db.get_medico_by_id(medico_id)
            if medico and medico_precisa_aceitar_termo(medico):
                return redirect(url_for("termos.tela_termo", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper
