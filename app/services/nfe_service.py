"""
Emissão de Nota Fiscal (NFS-e) da LIFEMAX para os médicos, referente aos
pagamentos de aluguel de sala/hora (tabela pagamentos_pix) -- pedido do
Paulo em 11/09/2026: "Em relatórios: criar botão 'Transações ainda não
faturadas' ... criar botões 'Emitir NF' (criar sistema para emissão de nf
pelo governo via chave A1 -- vou enviar essas configurações
posteriormente)."

⚠️ Não confundir com sql/migration_tax_profile_nfse.sql (colunas
medicos.certificado_a1_*): aquele é o certificado A1 DO MÉDICO, usado em
outro módulo (financeiro médico) para as notas que ELE emite pros
PACIENTES dele. Aqui é o certificado A1 da PRÓPRIA LIFEMAX, usado pra
emitir a nota que a Lifemax manda pro médico pelo aluguel do consultório
-- por isso as variáveis de configuração abaixo são globais do sistema
(NFE_*), não por médico.

Ainda NÃO há integração real com nenhum provedor de NFS-e/prefeitura --
o Paulo vai mandar o certificado A1 + senha + CNPJ emissor depois. Até lá,
emitir_nf() sempre levanta NfeNaoConfiguradaError com uma mensagem clara
pro admin, sem quebrar o resto da tela -- mesmo padrão já usado pro SMTP
(app/services/email_service.py) e pro Google Calendar
(app/services/google_calendar_service.py, GoogleCalendarNaoConfiguradoError).
"""
from app.config import Config


class NfeNaoConfiguradaError(Exception):
    pass


def configurado() -> bool:
    return bool(Config.NFE_A1_CERTIFICADO_PATH and Config.NFE_A1_SENHA and Config.NFE_CNPJ_EMISSOR)


def _checar_configurado():
    if not configurado():
        raise NfeNaoConfiguradaError(
            "A emissão automática de Nota Fiscal ainda não está configurada neste sistema. "
            "Preencha NFE_A1_CERTIFICADO_PATH, NFE_A1_SENHA e NFE_CNPJ_EMISSOR (certificado "
            'digital A1 da Lifemax) no .env -- veja .env.example, seção "Emissão de Nota '
            'Fiscal (NFS-e)". Assim que o Paulo enviar essas configurações, é só preencher '
            "aqui que o botão \"Emitir NF\" passa a funcionar de verdade."
        )


def emitir_nf(pagamento: dict) -> dict:
    """Emite a NFS-e referente a um pagamento (aluguel de sala/hora) já
    confirmado (status 'pago' em pagamentos_pix).

    Retorno esperado, quando um provedor real estiver integrado:
        {"numero": "<número da nota>", "url": "<link do PDF/XML da nota>"}
    -- usado por app.routes.admin.emitir_nf_pagamento pra chamar
    creditos_service.marcar_nota_fiscal_emitida(pagamento_id, numero, url).

    Por enquanto, sem provedor/certificado configurado, isso sempre
    levanta NfeNaoConfiguradaError (ver docstring do módulo)."""
    _checar_configurado()
    # TODO: quando o Paulo mandar o certificado A1 (.pfx/.p12) + senha, o
    # CNPJ emissor da Lifemax e o provedor de NFS-e da prefeitura/governo
    # a ser usado, integrar aqui:
    #   1. montar o RPS (tomador = médico, valor = pagamento["valor"],
    #      descrição = "Aluguel de consultório/sala - Lifemax")
    #   2. assinar com o certificado A1 (NFE_A1_CERTIFICADO_PATH + SENHA)
    #   3. chamar a API do provedor de NFS-e/prefeitura pra emitir
    #   4. devolver {"numero": ..., "url": ...} com o número e o link da
    #      nota emitida
    raise NfeNaoConfiguradaError("Provedor de NFS-e ainda não integrado.")
