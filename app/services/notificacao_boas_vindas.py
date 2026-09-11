"""
Mensagem de boas-vindas enviada pelo WhatsApp quando o admin liga o
assistente de um médico pela primeira vez (botão "Ligar assistente" no
dashboard — só disponível depois do primeiro pagamento confirmado).
"""
from flask import url_for
from app.config import Config

MENSAGEM_BOAS_VINDAS = (
    "Olá, {nome}! 👋 Seu assistente do Lifemax está liberado.\n\n"
    "A partir de agora, você pode fazer tudo por aqui pelo WhatsApp:\n\n"
    "🗓️ *Reservar consultórios* — me manda um texto ou até um áudio "
    "dizendo o dia e turno (ou quantas horas) que precisa\n"
    "📸 *Ver fotos* dos consultórios disponíveis antes de reservar\n"
    "💰 *Consultar seu saldo* de créditos e quantas horas ainda tem disponíveis\n"
    "🧾 *Receber sua nota fiscal* de cada recarga direto por aqui\n\n"
    "Também dá pra acessar seu painel completo pelo navegador em: {url_painel}\n\n"
    "Qualquer coisa, é só me chamar por aqui!"
)


def enviar_boas_vindas(medico: dict) -> bool:
    """
    Envia a mensagem de boas-vindas por WhatsApp. Retorna True se
    enviou, False se não conseguiu (WhatsApp não configurado, erro, etc).
    Nunca levanta exceção — é sempre "melhor esforço".
    """
    if not (Config.WHATSAPP_TOKEN and Config.WHATSAPP_PHONE_NUMBER_ID):
        return False
    try:
        from app.services import whatsapp_client as wa
        texto = MENSAGEM_BOAS_VINDAS.format(
            nome=medico["nome"],
            url_painel=url_for("medico_painel.painel", _external=True),
        )
        wa.send_text(medico["telefone"], texto)
        return True
    except Exception as e:
        print(f"[boas_vindas] Não consegui enviar a mensagem de boas-vindas: {e}")
        return False
