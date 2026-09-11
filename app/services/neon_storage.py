"""
Armazenamento de arquivos (fotos dos consultórios) no Neon Object
Storage -- substitui o Supabase Storage na migração de 10/09/2026.

O Neon Object Storage fala o protocolo S3 (é "S3-compatível"), então
usamos o boto3 -- o SDK oficial da AWS -- só que apontado pro endereço
do seu projeto Neon em vez da AWS de verdade. Veja INSTALAR.md pra saber
onde pegar cada uma dessas variáveis no Neon Console.

Uso (substitui exatamente o que o Supabase Storage fazia):

    from app.services import neon_storage

    url = neon_storage.upload_arquivo(caminho, dados_binarios, content_type)
    # url já é o link público (o bucket é público-leitura) pra salvar no
    # banco, igual o get_public_url() do Supabase fazia.
"""
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from app.config import Config

_client = None


class NeonStorageNaoConfigurado(Exception):
    """As variáveis NEON_S3_* não foram preenchidas ainda."""


def _get_client():
    global _client
    if _client is None:
        if not (Config.NEON_S3_ENDPOINT_URL and Config.NEON_S3_ACCESS_KEY_ID
                and Config.NEON_S3_SECRET_ACCESS_KEY):
            raise NeonStorageNaoConfigurado(
                "Armazenamento de fotos não configurado -- preencha NEON_S3_ENDPOINT_URL, "
                "NEON_S3_ACCESS_KEY_ID e NEON_S3_SECRET_ACCESS_KEY (veja o painel de "
                "configuração ou o .env.example)."
            )
        _client = boto3.client(
            "s3",
            region_name=Config.NEON_S3_REGION,
            endpoint_url=Config.NEON_S3_ENDPOINT_URL,
            aws_access_key_id=Config.NEON_S3_ACCESS_KEY_ID,
            aws_secret_access_key=Config.NEON_S3_SECRET_ACCESS_KEY,
        )
    return _client


def upload_arquivo(caminho: str, dados: bytes, content_type: str = "application/octet-stream") -> str:
    """Envia o arquivo pro bucket configurado (NEON_S3_BUCKET) e devolve a
    URL pública dele -- pronta pra guardar no banco (mesmo formato que o
    Supabase Storage devolvia). `caminho` é o "nome do arquivo" dentro do
    bucket, ex: "consultorio-id/2026-09-10-foto.jpg".

    Levanta NeonStorageNaoConfigurado se as credenciais não estiverem
    preenchidas, ou RuntimeError se o Neon recusar o upload (bucket
    inexistente, credencial inválida etc) -- ambos com mensagem em
    português pronta pra mostrar num flash() de erro."""
    client = _get_client()
    bucket = Config.NEON_S3_BUCKET
    try:
        client.put_object(Bucket=bucket, Key=caminho, Body=dados, ContentType=content_type)
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Não foi possível enviar o arquivo pro Neon Object Storage: {e}") from e
    return get_url_publica(caminho)


def get_url_publica(caminho: str) -> str:
    """Monta a URL pública de um objeto já enviado (o bucket precisa estar
    configurado como "Public Read" no Neon -- é assim que foi orientado
    na criação do projeto)."""
    endpoint = (Config.NEON_S3_ENDPOINT_URL or "").rstrip("/")
    return f"{endpoint}/{Config.NEON_S3_BUCKET}/{caminho}"


def excluir_arquivo(caminho: str) -> None:
    """Remove um arquivo do bucket. Silencioso se o arquivo já não existir
    (mesmo comportamento "idempotente" que o resto do sistema usa pra
    exclusão)."""
    client = _get_client()
    try:
        client.delete_object(Bucket=Config.NEON_S3_BUCKET, Key=caminho)
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Não foi possível apagar o arquivo do Neon Object Storage: {e}") from e
