"""
Integração com o Asaas para gerar cobranças PIX e consultar status de
pagamento. Docs: https://docs.asaas.com

Fluxo:
1. Garante que o médico tem um "customer" no Asaas (criarCliente)
2. Cria a cobrança PIX (criar_cobranca_pix) — Asaas retorna um ID de pagamento
3. Busca o QR Code dessa cobrança (obter_qrcode_pix)
4. Quando o médico paga, o Asaas manda um webhook pro nosso sistema
   (rota /webhooks/asaas) confirmando o pagamento
"""
import requests
from app.config import Config


def _headers():
    return {
        "access_token": Config.ASAAS_API_KEY,
        "Content-Type": "application/json",
    }


def _base_url():
    return Config.asaas_base_url()


def criar_ou_obter_cliente(nome: str, telefone: str, medico_id: str, cpf_cnpj: str) -> str:
    """
    Asaas exige um "customer" para poder cobrar — e exige CPF/CNPJ
    válido nesse cliente pra conseguir gerar cobrança PIX (é uma
    exigência regulatória do Banco Central, de identificar quem está
    pagando via PIX, não é regra nossa). Usamos o medico_id como
    referência externa (externalReference) para não duplicar clientes.
    Retorna o ID do cliente no Asaas.
    """
    cpf_cnpj_limpo = "".join(c for c in (cpf_cnpj or "") if c.isdigit())
    if not cpf_cnpj_limpo:
        raise CpfCnpjObrigatorioError(
            "Para comprar créditos, primeiro preencha seu CPF ou CNPJ na seção "
            "'Meus dados' do seu painel — a Asaas exige essa informação para gerar cobrança PIX."
        )

    # Tenta achar um cliente já existente com essa referência externa
    resp = requests.get(
        f"{_base_url()}/customers",
        headers=_headers(),
        params={"externalReference": medico_id},
        timeout=15,
    )
    _levantar_erro_detalhado(resp)
    dados = resp.json()
    if dados.get("data"):
        cliente_existente = dados["data"][0]
        # se o cliente já existia mas sem CPF/CNPJ (cadastro antigo, de antes dessa correção),
        # atualiza ele agora em vez de tentar criar um novo (evita duplicar)
        if not cliente_existente.get("cpfCnpj"):
            resp_update = requests.post(
                f"{_base_url()}/customers/{cliente_existente['id']}",
                headers=_headers(),
                json={"cpfCnpj": cpf_cnpj_limpo},
                timeout=15,
            )
            _levantar_erro_detalhado(resp_update)
        return cliente_existente["id"]

    # Não existe ainda — cria um novo, já com CPF/CNPJ
    resp = requests.post(
        f"{_base_url()}/customers",
        headers=_headers(),
        json={
            "name": nome,
            "mobilePhone": telefone,
            "cpfCnpj": cpf_cnpj_limpo,
            "externalReference": medico_id,
        },
        timeout=15,
    )
    _levantar_erro_detalhado(resp)
    return resp.json()["id"]


class CpfCnpjObrigatorioError(Exception):
    pass


def _levantar_erro_detalhado(resp: requests.Response):
    """
    Em vez de deixar o requests levantar só '400 Client Error: Bad
    Request for url: ...' (sem dizer o motivo), tenta extrair a
    mensagem de erro específica que a Asaas manda no corpo da resposta
    — isso é essencial pra saber o motivo real de qualquer falha futura,
    em vez de um erro genérico sem contexto.
    """
    if resp.ok:
        return
    detalhe = ""
    try:
        corpo = resp.json()
        erros = corpo.get("errors", [])
        if erros:
            detalhe = " — " + "; ".join(e.get("description", str(e)) for e in erros)
    except ValueError:
        pass
    raise requests.exceptions.HTTPError(
        f"{resp.status_code} {resp.reason} da Asaas{detalhe} (url: {resp.url})", response=resp
    )


def criar_cobranca_pix(customer_id: str, valor: float, descricao: str) -> dict:
    """
    Cria a cobrança PIX. Retorna o dict de resposta do Asaas, que inclui
    o 'id' do pagamento (precisamos dele para buscar o QR Code em seguida).
    """
    resp = requests.post(
        f"{_base_url()}/payments",
        headers=_headers(),
        json={
            "customer": customer_id,
            "billingType": "PIX",
            "value": valor,
            "dueDate": _data_vencimento_hoje(),
            "description": descricao,
        },
        timeout=15,
    )
    _levantar_erro_detalhado(resp)
    return resp.json()


def criar_cobranca_cartao(customer_id: str, valor: float, descricao: str, parcelas: int = 1) -> dict:
    """
    Cria a cobrança para pagamento com cartão de crédito. O médico é
    redirecionado para a 'invoiceUrl' que vem na resposta — lá ele
    digita os dados do cartão numa página segura do próprio Asaas
    (nosso sistema nunca recebe nem guarda o número do cartão).

    `parcelas` > 1: usado pelos pacotes de 24h/48h que permitem
    parcelamento (ver creditos_service.listar_pacotes_horas /
    pacotes_horas.max_parcelas) — a Asaas espera `installmentCount` +
    `totalValue` (o valor TOTAL, ela mesma divide pelas parcelas) em vez
    de `value` nesse caso. Parcelamento só existe no cartão -- PIX é
    sempre à vista.
    """
    payload = {
        "customer": customer_id,
        "billingType": "CREDIT_CARD",
        "dueDate": _data_vencimento_hoje(),
        "description": descricao,
    }
    if parcelas and parcelas > 1:
        payload["installmentCount"] = parcelas
        payload["totalValue"] = valor
    else:
        payload["value"] = valor

    resp = requests.post(
        f"{_base_url()}/payments",
        headers=_headers(),
        json=payload,
        timeout=15,
    )
    _levantar_erro_detalhado(resp)
    return resp.json()


def obter_qrcode_pix(payment_id: str) -> dict:
    """Retorna {'encodedImage': <base64 do QR>, 'payload': <copia e cola>}."""
    resp = requests.get(
        f"{_base_url()}/payments/{payment_id}/pixQrCode",
        headers=_headers(),
        timeout=15,
    )
    _levantar_erro_detalhado(resp)
    return resp.json()


def consultar_pagamento(payment_id: str) -> dict:
    """Consulta o status atual de um pagamento (útil como fallback do webhook)."""
    resp = requests.get(
        f"{_base_url()}/payments/{payment_id}",
        headers=_headers(),
        timeout=15,
    )
    _levantar_erro_detalhado(resp)
    return resp.json()


def _data_vencimento_hoje() -> str:
    from datetime import date
    return date.today().isoformat()
