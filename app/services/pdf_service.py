"""
Gera o PDF do Contrato Digital de Utilização de Consultórios (LifeMax)
sob demanda, pro botão "Baixar contrato" no painel do médico (ver
app/routes/termos.py, rota /contrato/baixar). Pedido do Paulo em
10/09/2026.

O texto vem todo de app/services/contrato_service.py (mesma fonte usada
pela tela de aceite em termo_uso.html) -- este arquivo só cuida da
formatação/diagramação em PDF via reportlab.
"""
import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, PageBreak,
)

from app.services import contrato_service


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "TituloContrato", parent=base["Title"], fontSize=14, leading=18,
            alignment=TA_CENTER, spaceAfter=4,
        ),
        "subtitulo": ParagraphStyle(
            "SubtituloContrato", parent=base["Normal"], fontSize=10, leading=13,
            alignment=TA_CENTER, spaceAfter=10, textColor="#55707C",
        ),
        "preambulo": ParagraphStyle(
            "Preambulo", parent=base["Normal"], fontSize=9.5, leading=14,
            alignment=TA_JUSTIFY, spaceAfter=8,
        ),
        "secao": ParagraphStyle(
            "Secao", parent=base["Heading2"], fontSize=11.5, leading=14,
            spaceBefore=14, spaceAfter=6, textColor="#0E2A3B",
        ),
        "corpo": ParagraphStyle(
            "Corpo", parent=base["Normal"], fontSize=9.5, leading=14,
            alignment=TA_JUSTIFY, spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"], fontSize=9.5, leading=13.5,
            alignment=TA_JUSTIFY,
        ),
        "aceite_titulo": ParagraphStyle(
            "AceiteTitulo", parent=base["Heading2"], fontSize=12.5, leading=15,
            spaceBefore=16, spaceAfter=8, textColor="#0E2A3B", alignment=TA_CENTER,
        ),
        "aceite_item": ParagraphStyle(
            "AceiteItem", parent=base["Normal"], fontSize=9.5, leading=14, spaceAfter=4,
        ),
        "dados_aceite": ParagraphStyle(
            "DadosAceite", parent=base["Normal"], fontSize=9.5, leading=16, spaceAfter=3,
        ),
    }


def _formatar_data_br(iso_str: str | None) -> str:
    if not iso_str:
        return "não registrada"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y às %H:%M UTC")
    except (ValueError, AttributeError):
        return str(iso_str)


def gerar_pdf_contrato(medico: dict) -> io.BytesIO:
    """Monta o PDF do contrato preenchido com os dados de aceite DESSE
    médico (nome, CPF/CNPJ, registro profissional, data/hora, IP, versão
    do texto aceita). Se por algum motivo o médico ainda não tiver
    aceitado (não deveria acontecer -- essa rota já fica atrás do login
    + @requer_termo_aceito em todas as outras telas), mostra os campos
    como pendentes em vez de quebrar."""
    estilos = _estilos()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=18 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
        title="Contrato Digital LifeMax", author="LifeMax Consultórios",
    )

    story = []
    story.append(Paragraph(contrato_service.CONTRATO_TITULO, estilos["titulo"]))
    story.append(Paragraph(f"Versão do contrato: {contrato_service.CONTRATO_VERSAO}", estilos["subtitulo"]))
    story.append(Spacer(1, 6))

    # Preâmbulo: os 2 primeiros itens são o título/subtítulo da LifeMax
    # (negrito, centralizado), o resto são parágrafos normais.
    for i, texto in enumerate(contrato_service.CONTRATO_PREAMBULO):
        if i < 2:
            story.append(Paragraph(f"<b>{texto}</b>", estilos["subtitulo"]))
        else:
            story.append(Paragraph(texto, estilos["preambulo"]))

    for titulo_secao, itens in contrato_service.CONTRATO_SECOES:
        story.append(Paragraph(titulo_secao, estilos["secao"]))
        for item in itens:
            if isinstance(item, dict):
                # bulletType="bullet" sem `start` custom usa o glifo padrão do
                # reportlab (fonte ZapfDingbats, desenha um ponto de verdade) --
                # passar start="•" ou qualquer símbolo Unicode aqui tentaria
                # desenhar esse caractere com a fonte Helvetica normal, que não
                # tem esse glifo e vira caractere errado no PDF (mesmo risco do
                # ☑ abaixo -- ver aviso da skill de PDF sobre símbolos Unicode).
                bullets = [ListItem(Paragraph(b, estilos["bullet"]), leftIndent=8) for b in item["bullets"]]
                story.append(ListFlowable(bullets, bulletType="bullet", leftIndent=16, spaceAfter=6))
            else:
                story.append(Paragraph(item, estilos["corpo"]))

    # ---- Bloco de aceite, preenchido com os dados reais deste médico ----
    story.append(PageBreak())
    story.append(Paragraph("ACEITE DIGITAL", estilos["aceite_titulo"]))
    story.append(Paragraph(
        "Ao aceitar eletronicamente na plataforma, o profissional declarou que:",
        estilos["corpo"],
    ))
    story.append(Spacer(1, 4))
    for declaracao in contrato_service.CONTRATO_DECLARACOES:
        # "[X]" em vez de ☑ -- Helvetica (fonte base do PDF) não tem esse
        # glifo Unicode e ele viraria um caractere errado no documento
        # final (mesmo problema descrito na skill de PDF sobre símbolos
        # fora do alfabeto latino básico).
        story.append(Paragraph(f"[X] {declaracao}", estilos["aceite_item"]))

    story.append(Spacer(1, 14))
    dados = [
        ("Nome do profissional", medico.get("nome") or "—"),
        ("CPF/CNPJ", medico.get("cpf_cnpj") or "não informado"),
        ("Registro profissional (CRM)", medico.get("crm") or "não informado"),
        ("Data e hora do aceite", _formatar_data_br(medico.get("termo_aceito_em"))),
        ("IP / identificação eletrônica", medico.get("termo_aceito_ip") or "não registrado"),
        ("Versão do contrato aceita", medico.get("termo_versao") or "não registrada (aceite anterior ao controle de versão)"),
        ("Aceite eletrônico", "ACEITO E CONCORDO" if medico.get("termo_aceito") else "PENDENTE"),
    ]
    for rotulo, valor in dados:
        story.append(Paragraph(f"<b>{rotulo}:</b> {valor}", estilos["dados_aceite"]))

    story.append(Spacer(1, 10))
    gerado_em = datetime.now(timezone.utc).strftime("%d/%m/%Y às %H:%M UTC")
    story.append(Paragraph(
        f"<i>Documento gerado automaticamente pela plataforma LifeMax em {gerado_em}, "
        f"a partir do aceite eletrônico registrado -- não requer assinatura física.</i>",
        estilos["dados_aceite"],
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer
