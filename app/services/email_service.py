"""
Envio de email via SMTP.

Funciona com qualquer provedor SMTP (Gmail, Outlook, Zoho, um servidor
próprio, etc). Para Gmail, você precisa gerar uma "senha de app" — a
senha normal da conta não funciona por segurança:
https://myaccount.google.com/apppasswords
"""
import html
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from app.config import Config

# Vários dos e-mails abaixo interpolam nome de médico/paciente direto no
# HTML do corpo do e-mail -- e esses nomes são digitados pelo próprio
# médico (cadastro/primeiro acesso) ou pela recepção, sem checagem de
# conteúdo. Sem escapar, um nome como '<a href="...">texto</a>' vira HTML
# de verdade dentro do e-mail enviado (inclusive pra funcionários/pacientes
# em notificar_turno_escolhido/notificar_nota_fiscal_paciente) -- um jeito
# barato de phishing/injeção de conteúdo. html.escape() neutraliza isso
# sem mudar como o nome aparece pra quem lê normalmente.
_esc = html.escape


def enviar_email(destinatarios: list[str], assunto: str, corpo_html: str,
                  anexos: list[tuple] | None = None) -> bool:
    """
    Envia um email para uma lista de destinatários.
    Retorna True se enviou com sucesso, False se as credenciais SMTP
    não estiverem configuradas (não quebra o fluxo principal por isso).

    anexos: lista opcional de tuplas (nome_arquivo, bytes, mimetype),
    ex: [("recibo.pdf", pdf_bytes, "application/pdf")] — usado, por
    exemplo, para mandar o recibo em PDF (Módulo 4) ou a planilha de
    exportação para a contabilidade direto por email.
    """
    if not all([Config.SMTP_HOST, Config.SMTP_USER, Config.SMTP_PASSWORD, Config.EMAIL_FROM]):
        print("[email] SMTP não configurado — pulando envio de email. "
              "Configure SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM no .env")
        return False

    if not destinatarios:
        print("[email] Nenhum destinatário cadastrado — pulando envio.")
        return False

    msg = MIMEMultipart("mixed")
    msg["Subject"] = assunto
    msg["From"] = Config.EMAIL_FROM
    msg["To"] = ", ".join(destinatarios)

    corpo = MIMEMultipart("alternative")
    corpo.attach(MIMEText(corpo_html, "html"))
    msg.attach(corpo)

    for nome_arquivo, conteudo_bytes, mimetype in (anexos or []):
        subtipo = mimetype.split("/", 1)[-1] if mimetype else "octet-stream"
        parte = MIMEApplication(conteudo_bytes, _subtype=subtipo)
        parte.add_header("Content-Disposition", "attachment", filename=nome_arquivo)
        msg.attach(parte)

    try:
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.sendmail(Config.EMAIL_FROM, destinatarios, msg.as_string())
        return True
    except Exception as e:
        print(f"[email] Erro ao enviar: {e}")
        return False


def notificar_turno_escolhido(medico_nome: str, consultorio_nome: str, data: str, periodo: str,
                                destinatarios: list[str]) -> bool:
    periodo_legivel = {"manha": "Manhã", "tarde": "Tarde", "noite": "Noite"}.get(periodo, periodo)

    assunto = f"Turno reservado: {consultorio_nome} — {data} ({periodo_legivel})"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Novo turno reservado</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding: 6px 0; color: #555;">Médico:</td>
                <td style="padding: 6px 0; font-weight: bold;">{_esc(medico_nome)}</td></tr>
            <tr><td style="padding: 6px 0; color: #555;">Consultório:</td>
                <td style="padding: 6px 0; font-weight: bold;">{_esc(consultorio_nome)}</td></tr>
            <tr><td style="padding: 6px 0; color: #555;">Data:</td>
                <td style="padding: 6px 0; font-weight: bold;">{data}</td></tr>
            <tr><td style="padding: 6px 0; color: #555;">Turno:</td>
                <td style="padding: 6px 0; font-weight: bold;">{periodo_legivel}</td></tr>
        </table>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema de Turnos Lifemax
        </p>
    </div>
    """
    return enviar_email(destinatarios, assunto, corpo_html)


def notificar_recuperacao_senha(nome: str, link_redefinir: str, destinatario: str) -> bool:
    assunto = "Redefinir sua senha — Lifemax"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Redefinição de senha</h2>
        <p>Olá, {_esc(nome)}! Recebemos um pedido para redefinir sua senha de acesso ao sistema Lifemax.</p>
        <p>
            <a href="{link_redefinir}" style="background:#1a3c5e; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Criar nova senha
            </a>
        </p>
        <p style="color: #888; font-size: 12px;">Esse link é válido por 30 minutos e só pode ser usado uma vez.
        Se você não pediu essa redefinição, pode ignorar este e-mail — sua senha continua a mesma.</p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_primeiro_acesso(nome: str, link_criar_senha: str, destinatario: str) -> bool:
    assunto = "Seu acesso ao sistema Lifemax está pronto"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Bem-vindo(a) ao sistema Lifemax</h2>
        <p>Olá, {_esc(nome)}! Seu cadastro já está pronto no sistema da Lifemax — falta só você criar sua senha
        de acesso pra entrar pela primeira vez.</p>
        <p>
            <a href="{link_criar_senha}" style="background:#1a3c5e; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Criar minha senha de acesso
            </a>
        </p>
        <p style="color: #888; font-size: 12px;">Esse link é válido por 48 horas e só pode ser usado uma vez.
        Depois de criar a senha, você já entra direto no seu painel — use esse mesmo e-mail ou o telefone
        cadastrado na próxima vez.</p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_confirmacao_avaliacao(medico_nome: str, nota: int, link_confirmacao: str,
                                     destinatario: str) -> bool:
    estrelas = "★" * nota + "☆" * (5 - nota)
    assunto = f"Confirme sua avaliação de {medico_nome} — Rede Lifemax"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #0E2A3B;">Confirme sua avaliação</h2>
        <p>Você avaliou <strong>{_esc(medico_nome)}</strong> com a nota
        <strong style="color:#d4a017;">{estrelas}</strong> na Rede Lifemax.</p>
        <p>Para publicar essa avaliação, confirme clicando no botão abaixo — isso garante
        que a avaliação foi feita mesmo por você, e não por outra pessoa em seu nome.</p>
        <p>
            <a href="{link_confirmacao}" style="background:#0EA5A0; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Confirmar avaliação
            </a>
        </p>
        <p style="color: #888; font-size: 12px;">Esse link é válido por 48 horas e só pode ser usado
        uma vez. Se você não fez essa avaliação, pode ignorar este e-mail — ela nunca será publicada
        sem essa confirmação.</p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Rede Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_nota_fiscal(medico_nome: str, valor: float, numero_nota: str, url_nota: str,
                           destinatario: str) -> bool:
    assunto = f"Sua nota fiscal — Lifemax (NF {numero_nota})"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Nota fiscal disponível</h2>
        <p>Olá, {_esc(medico_nome)}! Segue sua nota fiscal referente à recarga de créditos
        no valor de <strong>R$ {valor:.2f}</strong>.</p>
        <p>
            <a href="{url_nota}" style="background:#1a3c5e; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Baixar Nota Fiscal (NF {numero_nota})
            </a>
        </p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_nota_fiscal_paciente(medico_nome: str, valor: float, numero_nota: str, url_nota: str,
                                    destinatario: str) -> bool:
    """NF pelo atendimento médico prestado -- e-mail pro PACIENTE, não
    pro médico (diferente de notificar_nota_fiscal, que é sobre a
    recarga de créditos do médico com a Lifemax)."""
    assunto = f"Sua nota fiscal — {medico_nome} (NF {numero_nota})"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Nota fiscal do seu atendimento</h2>
        <p>Segue a nota fiscal referente ao atendimento com <strong>{_esc(medico_nome)}</strong>,
        no valor de <strong>R$ {valor:.2f}</strong>.</p>
        <p>
            <a href="{url_nota}" style="background:#1a3c5e; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Baixar Nota Fiscal (NF {numero_nota})
            </a>
        </p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_notas_periodo_contador(medico_nome: str, ano: int, mes: int, notas: list, destinatario: str) -> bool:
    """Resumo em lote das notas fiscais emitidas num período -- pro
    contador do médico, com os números e links de cada uma (não é um
    PDF único consolidado, cada nota já tem o link dela)."""
    meses = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]
    linhas_html = "".join(
        f"""<tr>
            <td style="padding:6px 10px; border-bottom:1px solid #eee;">NF {n.get('nota_fiscal_numero', '—')}</td>
            <td style="padding:6px 10px; border-bottom:1px solid #eee;">R$ {float(n.get('valor_bruto', 0)):.2f}</td>
            <td style="padding:6px 10px; border-bottom:1px solid #eee;">
                <a href="{n.get('nota_fiscal_url', '#')}">Abrir</a>
            </td>
        </tr>"""
        for n in notas
    )
    assunto = f"Notas fiscais de {medico_nome} — {meses[mes]}/{ano}"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px;">
        <h2 style="color: #1a3c5e;">Notas fiscais do período</h2>
        <p>Segue a lista de notas fiscais de <strong>{_esc(medico_nome)}</strong> emitidas em
        <strong>{meses[mes]}/{ano}</strong> ({len(notas)} nota(s)):</p>
        <table style="border-collapse: collapse; width:100%; font-size: 13px;">
            <thead><tr style="text-align:left; color:#888;">
                <th style="padding:6px 10px;">Número</th><th style="padding:6px 10px;">Valor</th><th style="padding:6px 10px;">Link</th>
            </tr></thead>
            <tbody>{linhas_html}</tbody>
        </table>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)
