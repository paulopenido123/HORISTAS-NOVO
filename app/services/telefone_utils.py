"""
Funções utilitárias de normalização de telefone -- usadas em vários pontos
do sistema (login, cadastro, API da Dora/WhatsApp). Moveram-se pra cá em
30/09/2026, quando o módulo "Agenda Fixos" (agenda_fixos_service.py) foi
removido do sistema (todos os médicos passaram a ser só "avulso"), já que
essas duas funções não tinham nada a ver com aquele módulo específico --
eram só utilitárias genéricas que moravam lá.
"""
import re


def normalizar_telefone(valor) -> str | None:
    """Extrai só os dígitos e garante o DDI 55 na frente (padrão E.164 sem '+' usado no resto do sistema)."""
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor))
    if not digitos:
        return None
    if not digitos.startswith("55") and len(digitos) in (10, 11):
        digitos = "55" + digitos
    return digitos


def telefone_sem_ddi(valor) -> str:
    """O contrário de normalizar_telefone -- pra MOSTRAR pro médico/paciente
    (login, "Dados Pessoais", listas no admin etc.): tira o "55" da
    frente, deixando só DDD + número. Nunca usar isso pra guardar no
    banco nem pra mandar mensagem pelo WhatsApp -- lá o "55" continua
    obrigatório (é assim que a Meta identifica o número)."""
    if not valor:
        return ""
    digitos = re.sub(r"\D", "", str(valor))
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos[2:]
    return digitos
