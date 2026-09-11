"""
Cadastro e login das secretárias (papel separado do admin -- ver
migration_secretarias.sql). O admin cadastra nome+telefone; a própria
secretária define a senha depois, em /secretaria/criar-senha.
"""
from app.services.supabase_client import get_client


def criar_secretaria(nome: str, telefone: str, email: str = "") -> dict:
    resp = (
        get_client()
        .table("secretarias")
        .insert({"nome": nome, "telefone": telefone, "email": (email or "").strip(), "ativo": True})
        .execute()
    )
    return resp.data[0]


def get_secretaria_by_telefone(telefone: str) -> dict | None:
    resp = get_client().table("secretarias").select("*").eq("telefone", telefone).execute()
    data = resp.data
    return data[0] if data else None


def get_secretaria_by_id(secretaria_id: str) -> dict | None:
    resp = get_client().table("secretarias").select("*").eq("id", secretaria_id).execute()
    data = resp.data
    return data[0] if data else None


def definir_senha_secretaria(secretaria_id: str, senha_hash: str):
    get_client().table("secretarias").update({"senha_hash": senha_hash}).eq("id", secretaria_id).execute()


def secretaria_tem_senha(secretaria: dict) -> bool:
    return bool(secretaria.get("senha_hash"))


def listar_secretarias() -> list[dict]:
    resp = get_client().table("secretarias").select("*").order("nome").execute()
    return resp.data


def desativar_secretaria(secretaria_id: str):
    get_client().table("secretarias").update({"ativo": False}).eq("id", secretaria_id).execute()


def reativar_secretaria(secretaria_id: str):
    get_client().table("secretarias").update({"ativo": True}).eq("id", secretaria_id).execute()


def atualizar_email_secretaria(secretaria_id: str, email: str):
    get_client().table("secretarias").update({"email": (email or "").strip()}).eq("id", secretaria_id).execute()
