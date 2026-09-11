"""
Webhook do Asaas: recebe a notificação de pagamento confirmado e credita
o saldo do médico automaticamente.

Configuração no painel do Asaas: Settings > Integrações > Webhooks,
apontando para https://sua-url.com/webhooks/asaas, evento
"PAYMENT_RECEIVED" (e "PAYMENT_CONFIRMED" para cobrir PIX confirmado
antes da compensação).
"""
from flask import Blueprint, request, jsonify
from app.config import Config
from app.services import creditos_service as creditos_db
from app.services import supabase_client as db
from app.services import notificacao_saldo

webhooks_asaas_bp = Blueprint("webhooks_asaas", __name__)


def confirmar_pagamento_e_creditar(asaas_payment_id: str) -> bool:
    """
    Função central chamada tanto pelo webhook quanto pelo fallback de
    consulta manual (medico_painel.status_pagamento). Idempotente: se o
    pagamento já estiver marcado como pago, não credita de novo.

    Se for o PRIMEIRO pagamento confirmado do médico, libera o
    assistente de WhatsApp automaticamente (sem precisar do admin
    clicar em nada) e avisa o médico + os administradores.
    """
    pagamento = creditos_db.obter_pagamento_por_asaas_id(asaas_payment_id)
    if pagamento is None:
        print(f"[webhook_asaas] Pagamento {asaas_payment_id} não encontrado no nosso banco.")
        return False

    if pagamento["status"] == "pago":
        return True  # já processado antes, evita creditar duas vezes

    medico_id = pagamento["medico_id"]
    era_primeiro_pagamento = not creditos_db.medico_tem_pagamento_confirmado(medico_id)

    creditos_db.marcar_pagamento_pago(pagamento["id"])

    # Divide o crédito entre as duas carteiras conforme o médico
    # escolheu na hora de comprar (ver medico_painel.comprar_creditos) --
    # pagamento antigo, de antes da divisão de carteiras, não tem
    # valor_salas/valor_ia preenchidos -- nesse caso vai tudo pra salas,
    # igual sempre funcionou.
    valor_salas = float(pagamento.get("valor_salas") or pagamento["valor"])
    valor_ia = float(pagamento.get("valor_ia") or 0)
    horas_pacote = pagamento.get("horas_pacote")

    if valor_salas > 0:
        descricao = "Recarga via PIX (Asaas) — reserva de salas"
        if horas_pacote:
            # compra de um pacote fechado (6h/12h/24h/48h) -- grava a
            # quantidade EXATA de horas na transação, em vez de deixar
            # pra estimar depois a partir do valor pago (ver
            # creditos_service.horas_compradas_medico).
            descricao = f"Recarga via {pagamento.get('forma_pagamento', 'PIX')} (Asaas) — pacote de {horas_pacote}h"
        creditos_db.registrar_transacao(
            medico_id=medico_id, tipo="compra", valor=valor_salas,
            descricao=descricao,
            pagamento_id=pagamento["id"], carteira="salas",
            quantidade_horas=horas_pacote,
        )
    if valor_ia > 0:
        creditos_db.registrar_transacao(
            medico_id=medico_id, tipo="compra", valor=valor_ia,
            descricao="Recarga via PIX (Asaas) — créditos de IA",
            pagamento_id=pagamento["id"], carteira="ia", categoria="ia",
        )

    if era_primeiro_pagamento:
        _liberar_assistente_pelo_primeiro_pagamento(medico_id)

    return True


def _liberar_assistente_pelo_primeiro_pagamento(medico_id: str):
    from app.services import notificacao_boas_vindas
    from app.services import notificacoes_operacionais_service as notif_op

    medico = db.get_medico_by_id(medico_id)
    if medico is None:
        return

    resultado = creditos_db.ativar_assistente(medico_id)
    if resultado["ja_estava_ativo"]:
        return  # já tinha sido ligado manualmente antes — não manda boas-vindas de novo

    notificacao_boas_vindas.enviar_boas_vindas(medico)
    notif_op.avisar_admins(
        f"💰 Primeiro pagamento confirmado! {medico['nome']} ({medico['telefone']}) já tem o "
        f"assistente de WhatsApp liberado automaticamente (Módulo 1 — Venda de Horas Avulsas)."
    )


@webhooks_asaas_bp.route("/webhooks/asaas", methods=["POST"])
def receber_webhook():
    # Validação simples: se um token foi configurado, exige ele no header
    if Config.ASAAS_WEBHOOK_TOKEN:
        token_recebido = request.headers.get("asaas-access-token")
        if token_recebido != Config.ASAAS_WEBHOOK_TOKEN:
            return jsonify({"erro": "Token inválido."}), 401

    payload = request.get_json(force=True, silent=True) or {}
    evento = payload.get("event")
    pagamento_asaas = payload.get("payment", {})
    payment_id = pagamento_asaas.get("id")

    if evento in ("PAYMENT_RECEIVED", "PAYMENT_CONFIRMED") and payment_id:
        confirmar_pagamento_e_creditar(payment_id)

    return jsonify({"status": "ok"}), 200
