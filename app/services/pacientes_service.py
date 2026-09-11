"""
Cadastro completo de pacientes de cada médico -- pedido do Paulo em
11/09/2026: botão "Cadastre o seu paciente" no painel do médico, ficha
com dados pessoais + endereço + responsável (ver sql/migration_pacientes.sql),
e a tela "Pacientes cadastrados" que lista todos os pacientes de um médico
(cada médico só enxerga os próprios).

Também é usado pelo botão "Incluir/alterar paciente" da agenda do médico
(ver reserva_service.associar_paciente), que só precisa da lista de nomes
pra montar a lista de escolha.
"""
from app.services.supabase_client import get_client

# Whitelist dos campos que o formulário de cadastro/edição pode gravar --
# mesmo padrão de creditos_service._CAMPOS_DADOS_PESSOAIS: filtra o que
# vier no corpo da requisição por esta lista antes de montar o payload do
# insert/update, pra um campo desconhecido (ou um campo interno tipo
# medico_id/id) nunca ser sobrescrito a partir do formulário.
CAMPOS_PACIENTE = [
    # Informações pessoais
    "nome_completo", "nome_pai", "nome_mae", "data_nascimento", "cpf", "rg",
    "email", "sexo", "estado_civil", "cor", "convenio", "profissao", "indicacao",
    # Endereço
    "endereco", "bairro", "cep", "cidade", "estado",
    # Informações do responsável
    "responsavel_nome", "responsavel_tipo", "responsavel_telefone",
]


def _limpar_payload(dados: dict) -> dict:
    payload = {}
    for campo in CAMPOS_PACIENTE:
        if campo not in dados:
            continue
        valor = dados[campo]
        if isinstance(valor, str):
            valor = valor.strip()
        # string vazia vira None (data_nascimento vazia, por exemplo, não
        # pode ser gravada como "" numa coluna date -- o Postgres rejeita)
        payload[campo] = valor if valor not in ("",) else None
    return payload


def listar_pacientes_medico(medico_id: str) -> list[dict]:
    """Todos os pacientes cadastrados por esse médico, em ordem
    alfabética -- usada tanto na tela "Pacientes cadastrados" (ficha
    completa) quanto na lista de escolha do botão "Incluir/alterar
    paciente" (só o nome é mostrado ali)."""
    resp = (
        get_client()
        .table("pacientes")
        .select("*")
        .eq("medico_id", medico_id)
        .order("nome_completo")
        .execute()
    )
    return resp.data


def get_paciente_by_id(paciente_id: str) -> dict | None:
    resp = get_client().table("pacientes").select("*").eq("id", paciente_id).execute()
    return resp.data[0] if resp.data else None


def criar_paciente(medico_id: str, dados: dict) -> dict:
    payload = _limpar_payload(dados)
    if not payload.get("nome_completo"):
        raise ValueError("Informe o nome completo do paciente.")
    payload["medico_id"] = medico_id
    resp = get_client().table("pacientes").insert(payload).execute()
    return resp.data[0]


def atualizar_paciente(paciente_id: str, medico_id: str, dados: dict) -> dict:
    """`medico_id` é conferido aqui (não só no chamador) -- um médico
    nunca pode editar a ficha de um paciente de outro médico, mesmo que
    descubra/adivinhe o id de um paciente que não é dele."""
    from datetime import datetime, timezone

    paciente = get_paciente_by_id(paciente_id)
    if paciente is None or paciente["medico_id"] != medico_id:
        raise ValueError("Paciente não encontrado.")

    payload = _limpar_payload(dados)
    if "nome_completo" in payload and not payload["nome_completo"]:
        raise ValueError("Informe o nome completo do paciente.")
    if not payload:
        raise ValueError("Nenhum dado pra salvar.")
    payload["atualizado_em"] = datetime.now(timezone.utc).isoformat()

    resp = get_client().table("pacientes").update(payload).eq("id", paciente_id).execute()
    return resp.data[0]
