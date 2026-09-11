"""
Avisa o médico quando o saldo de créditos está baixo demais para pagar
outro turno. Tenta primeiro pelo WhatsApp (se já estiver configurado);
se não der, usa email como alternativa.
"""
import os
from app.config import Config
from app.services import creditos_service as creditos_db


LIMITE_ALERTA_SALDO_BAIXO = float(os.getenv("LIMITE_ALERTA_SALDO_BAIXO", "100.00"))


def verificar_e_notificar_saldo_baixo(medico: dict, saldo_atual: float):
    precos = creditos_db.obter_precos()
    horas_minimas = int(precos.get("horas_minimas", 1))
    limite = creditos_db.calcular_preco_horas(horas_minimas, precos)

    if limite <= 0 or saldo_atual >= limite:
        return  # saldo ainda dá para pelo menos a reserva mínima permitida

    if medico.get("alerta_saldo_baixo_enviado"):
        return  # já avisamos, evita ficar mandando toda hora

    mensagem = (
        f"Olá, {medico['nome']}! Seu saldo de créditos no Lifemax está em "
        f"R$ {saldo_atual:.2f} — não é suficiente para a reserva mínima de "
        f"{horas_minimas}h (R$ {limite:.2f}). "
        f"Para continuar reservando consultórios, recarregue seus créditos no seu painel."
    )

    enviado = False

    if Config.WHATSAPP_TOKEN and Config.WHATSAPP_PHONE_NUMBER_ID:
        try:
            from app.services import whatsapp_client as wa
            wa.send_text(medico["telefone"], mensagem)
            enviado = True
        except Exception as e:
            print(f"[alerta_saldo] Falha ao enviar por WhatsApp: {e}")

    if not enviado and medico.get("email"):
        try:
            from app.services import email_service
            email_service.enviar_email(
                [medico["email"]], "Saldo de créditos baixo — Lifemax",
                f"<p>{mensagem}</p>",
            )
            enviado = True
        except Exception as e:
            print(f"[alerta_saldo] Falha ao enviar por email: {e}")

    if enviado:
        creditos_db.marcar_alerta_saldo_baixo_enviado(medico["id"])


def verificar_e_notificar_saldo_baixo_fixo(medico: dict, saldo_atual: float, carteira: str):
    """Pedido do Paulo (08/09/2026): quando QUALQUER uma das duas
    carteiras (salas ou IA) chegar a R$ 100 ou menos, manda um e-mail
    com o link de login -- uma vez só até o saldo subir de novo (o
    flag reseta sozinho em registrar_transacao quando o saldo sobe).
    Sempre por e-mail (diferente do alerta de cima, que tenta WhatsApp
    primeiro) -- é assim que o Paulo pediu esse aviso especificamente."""
    if saldo_atual > LIMITE_ALERTA_SALDO_BAIXO:
        return

    campo_alerta = "alerta_saldo_baixo_enviado" if carteira == "salas" else "alerta_saldo_ia_baixo_enviado"
    if medico.get(campo_alerta):
        return
    if not medico.get("email"):
        return

    from flask import url_for
    link_login = url_for("auth.login", _external=True)
    rotulo_carteira = "reserva de salas" if carteira == "salas" else "uso de IA"

    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <p>Prezado(a) Sr(a). {medico['nome']},</p>
        <p>Seus créditos de {rotulo_carteira} estão com saldo de <strong>R$ {saldo_atual:.2f}</strong>.</p>
        <p>Estamos enviando o link para evitar que sua conta fique sem saldo.</p>
        <p>
            <a href="{link_login}" style="background:#1a3c5e; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Acessar minha conta
            </a>
        </p>
    </div>
    """

    try:
        from app.services import email_service
        enviado = email_service.enviar_email([medico["email"]], "Saldo baixo — Lifemax", corpo_html)
        if enviado:
            creditos_db.marcar_alerta_saldo_baixo_enviado(medico["id"], carteira)
    except Exception as e:
        print(f"[notificacao_saldo] Falha ao enviar e-mail de saldo baixo ({carteira}): {e}")
