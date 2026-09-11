"""
Sistema de módulos: cada funcionalidade grande do sistema aparece como
um "card" no painel do médico, com status ('em_desenvolvimento', 'beta'
ou 'ativo'). Médicos "beta tester" (por enquanto, só o Dr. Paulo de
teste) veem todos os módulos, inclusive os que ainda não existem de
verdade — os outros médicos só veem os que já estão 'ativo'.
"""
from app.services.supabase_client import get_client


def listar_todos_modulos() -> list[dict]:
    resp = get_client().table("modulos").select("*").order("ordem").execute()
    return resp.data


def listar_modulos_publicos() -> list[dict]:
    """O que aparece na homepage pública — pode ter módulo pausado
    temporariamente aqui (visivel_publicamente=False) mesmo que ele
    ainda exista normalmente pro controle interno (admin/médico)."""
    todos = listar_todos_modulos()
    return [m for m in todos if m.get("visivel_publicamente", True)]


def listar_modulos_visiveis(medico: dict) -> list[dict]:
    """O que esse médico específico deve ver no painel dele.

    O Módulo 1 (venda-horas-avulsas) fica de fora daqui desde 10/09/2026
    (pedido do Paulo): os médicos vão ter outro caminho de acesso a essa
    funcionalidade, não mais o card "Acessar" dentro da própria tela que
    ela mesma abre. Continua existindo normalmente em listar_todos_modulos
    (usado pelo admin) -- só sai da grade que o médico vê no painel dele."""
    todos = listar_todos_modulos()
    if medico.get("is_beta_tester"):
        visiveis = todos
    else:
        visiveis = [m for m in todos if m["status"] == "ativo"]
    return [m for m in visiveis if m.get("slug") != "venda-horas-avulsas"]


def atualizar_status_modulo(modulo_id: str, status: str) -> dict:
    resp = get_client().table("modulos").update({"status": status}).eq("id", modulo_id).execute()
    return resp.data[0]


def marcar_beta_tester(medico_id: str, valor: bool):
    get_client().table("medicos").update({"is_beta_tester": valor}).eq("id", medico_id).execute()
