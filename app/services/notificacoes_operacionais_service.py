"""
Avisos operacionais por WhatsApp para os administradores (você e a
Patricia) — coisas como "novo médico se cadastrou" ou "pagamento
confirmado, assistente liberado". Diferente do alerta_admin_service.py
(que é especificamente para suspeita de algo indevido) — esses aqui são
avisos de rotina do dia a dia do negócio.
"""
from app.config import Config


def avisar_admins(texto: str) -> int:
    """Manda a mensagem para todos os telefones de admin configurados
    (você e a Patricia, se ambos estiverem preenchidos). Retorna quantos
    avisos foram enviados com sucesso."""
    if not (Config.WHATSAPP_TOKEN and Config.WHATSAPP_PHONE_NUMBER_ID):
        print(f"[notificacoes_operacionais] WhatsApp não configurado — aviso não enviado: {texto}")
        return 0

    destinos = [t for t in [Config.ADMIN_PHONE, Config.ADMIN_PHONE_PATRICIA] if t]
    if not destinos:
        print(f"[notificacoes_operacionais] Nenhum telefone de admin configurado — aviso não enviado: {texto}")
        return 0

    from app.services import whatsapp_client as wa
    enviados = 0
    for telefone in destinos:
        try:
            wa.send_text(telefone, texto)
            enviados += 1
        except Exception as e:
            print(f"[notificacoes_operacionais] Erro ao avisar {telefone}: {e}")
    return enviados
