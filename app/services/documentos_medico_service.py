"""Documento do médico (v100): upload pelo próprio médico em "Meus dados"; consulta e exclusão só
pelo administrador. Fica na tabela `documentos_medico` (bytea) -- nunca em bucket público -- e é
servido apenas pela rota admin protegida. Um documento por médico; reenviar substitui.
A tabela fica FORA do backup JSON (ver backup_service._TABELAS_FORA_DO_BACKUP): dado sensível e pesado."""
from app.services.supabase_client import get_client, agora_iso

TAMANHO_MAXIMO = 4 * 1024 * 1024  # 4 MB (o navegador já reduz fotos antes de enviar)

# (assinatura dos primeiros bytes, content-type, extensão)
_TIPOS = (
    (b"%PDF", "application/pdf", "pdf"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


def detectar_tipo(dados: bytes) -> tuple[str, str] | None:
    """Confere pelo CONTEÚDO (não pelo nome/cabeçalho enviado). Devolve (content_type, extensão) ou None."""
    for assinatura, content_type, ext in _TIPOS:
        if dados.startswith(assinatura):
            return content_type, ext
    return None


def salvar(medico_id: str, nome_original: str, dados: bytes) -> dict:
    """Valida e grava (substitui o anterior). Levanta ValueError com mensagem para o médico."""
    if not dados:
        raise ValueError("Nenhum arquivo foi enviado.")
    if len(dados) > TAMANHO_MAXIMO:
        raise ValueError("O arquivo é grande demais (máximo 4 MB). Tire uma foto mais leve ou envie um PDF menor.")
    tipo = detectar_tipo(dados)
    if tipo is None:
        raise ValueError("Formato não aceito. Envie um PDF, JPG ou PNG.")
    content_type, ext = tipo
    base = "".join(c for c in (nome_original or "documento").rsplit(".", 1)[0] if c.isalnum() or c in " _-")[:60].strip()
    nome = f"{base or 'documento'}.{ext}"
    get_client().table("documentos_medico").upsert({
        "medico_id": medico_id, "nome_arquivo": nome, "content_type": content_type,
        "tamanho": len(dados), "conteudo": dados, "enviado_em": agora_iso(),
    }, on_conflict="medico_id").execute()
    return obter_info(medico_id)


def obter_info(medico_id: str) -> dict | None:
    """Só os metadados (sem o conteúdo) -- seguro para telas e listas."""
    r = (get_client().table("documentos_medico").select("medico_id,nome_arquivo,content_type,tamanho,enviado_em")
         .eq("medico_id", medico_id).execute().data)
    return r[0] if r else None


def documento_pendente(medico_id: str) -> bool:
    """v114: True se o médico ainda não anexou o documento de identidade. Se a tabela ainda não existe (migração v100 não
    rodada), devolve False para não travar o cadastro de todo mundo."""
    try:
        return obter_info(medico_id) is None
    except Exception as e:
        if getattr(e, "pgcode", None) == "42P01":
            return False
        raise


def info_de_todos() -> dict:
    """{medico_id: metadados} de quem já enviou -- 1 consulta, sem carregar os arquivos."""
    r = get_client().table("documentos_medico").select("medico_id,nome_arquivo,enviado_em").execute().data
    return {x["medico_id"]: x for x in r}


def obter(medico_id: str) -> dict | None:
    """Documento completo, com `conteudo` em bytes (uso exclusivo da rota admin). Lê direto do
    psycopg2: o PgClient converteria o bytea em texto e o arquivo se perderia."""
    from app.services.pg_query import _ConnCtx
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("select nome_arquivo, content_type, tamanho, conteudo, enviado_em "
                        "from documentos_medico where medico_id = %s", (medico_id,))
            linha = cur.fetchone()
        conn.rollback()
    if not linha:
        return None
    doc = dict(linha)
    doc["conteudo"] = bytes(doc["conteudo"])
    return doc


def excluir(medico_id: str) -> None:
    get_client().table("documentos_medico").delete().eq("medico_id", medico_id).execute()
