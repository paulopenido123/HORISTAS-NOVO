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


# ---------------------------------------------------------------------
# Avisos automáticos por e-mail -- pedido do Paulo em 11/09/2026 (ver
# sql/migration_notificacoes_email.sql e app/routes/auth.py,
# app/routes/admin.py, app/services/reserva_service.py,
# app/routes/webhooks_asaas.py, que chamam as funções abaixo).
# ---------------------------------------------------------------------

def notificar_confirmar_email(nome: str, link_confirmar: str, destinatario: str) -> bool:
    """Item 1: e-mail com o link de confirmação, mandado toda vez que o
    admin cadastra ou altera o e-mail de um médico (Clientes > Inserir
    novo / Editar dados). Quando o médico clica, aparece uma ⭐ do lado
    do e-mail dele na lista de Clientes do admin."""
    assunto = "Confirme seu e-mail — Sistema Lifemax"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Confirme seu e-mail</h2>
        <p>Olá, {_esc(nome)}! Pra confirmar que este e-mail é mesmo seu, clique no botão abaixo.</p>
        <p>
            <a href="{link_confirmar}" style="background:#1a3c5e; color:white; padding:10px 18px;
               border-radius:6px; text-decoration:none; display:inline-block;">
               Confirmar meu e-mail
            </a>
        </p>
        <p style="color: #888; font-size: 12px;">Se você não reconhece este cadastro, pode ignorar este e-mail.</p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_admin_novo_cadastro_pendente(nome_medico: str, telefone: str, destinatarios: list[str]) -> bool:
    """Item 2: aviso por e-mail ao(s) admin(s) (ADMIN_EMAIL) quando um
    médico se autocadastra pelo site (/primeiro-acesso) e fica
    aguardando liberação em Clientes."""
    assunto = f"Novo cadastro aguardando liberação: {nome_medico}"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Novo médico aguardando liberação</h2>
        <p><strong>{_esc(nome_medico)}</strong> ({_esc(telefone)}) acabou de se cadastrar sozinho pelo site.</p>
        <p>Ele já consegue entrar e comprar horas, mas fica bloqueado de reservar consultório até
        você liberar o acesso em <strong>Clientes</strong> (botão "Liberar acesso").</p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email(destinatarios, assunto, corpo_html)


def notificar_acesso_liberado(nome: str, destinatario: str) -> bool:
    """Item 3: aviso por e-mail ao médico quando o admin clica em
    "Liberar acesso" em Clientes -- a partir daí ele já pode reservar
    consultório (comprar horas ele já podia desde o cadastro)."""
    assunto = "Seu acesso foi liberado — Sistema Lifemax"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Seu acesso foi liberado!</h2>
        <p>Olá, {_esc(nome)}! Seu cadastro foi conferido e liberado -- você já pode reservar
        consultório e comprar horas normalmente no sistema.</p>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_recibo_compra_horas(nome: str, valor: float, horas: float | None,
                                   forma_pagamento: str, destinatario: str) -> bool:
    """Item 4: recibo por e-mail toda vez que uma compra de horas é
    confirmada (PIX ou cartão) -- ver webhooks_asaas.confirmar_pagamento_e_creditar."""
    linha_horas = f"<tr><td style='padding:6px 0; color:#555;'>Horas:</td><td style='padding:6px 0; font-weight:bold;'>{horas}h</td></tr>" if horas else ""
    assunto = "Recibo de pagamento — Sistema Lifemax"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Pagamento confirmado</h2>
        <p>Olá, {_esc(nome)}! Confirmamos o recebimento do seu pagamento. Segue o recibo:</p>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding:6px 0; color:#555;">Valor:</td>
                <td style="padding:6px 0; font-weight:bold;">R$ {valor:.2f}</td></tr>
            {linha_horas}
            <tr><td style="padding:6px 0; color:#555;">Forma de pagamento:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(forma_pagamento)}</td></tr>
        </table>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def _bloco_saldos_html(saldo_horas: float | None, saldo_ia: float | None) -> str:
    """Bloco com o saldo atual de horas e de IA do médico -- pedido do
    Paulo em 22/09/2026: todo e-mail de agendamento/cancelamento passou a
    mostrar os dois saldos atualizados, pra ele não precisar entrar no
    painel só pra conferir. `None` (chamador não conseguiu buscar o
    saldo por algum motivo) simplesmente omite a linha correspondente,
    em vez de mostrar "None" ou quebrar o e-mail."""
    linhas = ""
    if saldo_horas is not None:
        linhas += (f'<tr><td style="padding:6px 0; color:#555;">Saldo de horas:</td>'
                   f'<td style="padding:6px 0; font-weight:bold;">{saldo_horas}h</td></tr>')
    if saldo_ia is not None:
        linhas += (f'<tr><td style="padding:6px 0; color:#555;">Saldo para IA:</td>'
                   f'<td style="padding:6px 0; font-weight:bold;">R$ {saldo_ia:.2f}</td></tr>')
    if not linhas:
        return ""
    return f"""
        <table style="width: 100%; border-collapse: collapse; margin-top: 14px; border-top: 1px solid #e3ebef; padding-top: 6px;">
            {linhas}
        </table>
    """


def notificar_agendamento_medico(nome_medico: str, consultorio_nome: str, data: str, horario: str,
                                  destinatario: str, saldo_horas: float | None = None,
                                  saldo_ia: float | None = None) -> bool:
    """Item 5 (lado do médico): confirma que uma reserva foi feita --
    mandado direto pro e-mail do PRÓPRIO médico (diferente de
    notificar_turno_escolhido, que avisa a recepção/funcionários).
    `saldo_horas`/`saldo_ia` (pedido do Paulo em 22/09/2026) mostram o
    saldo JÁ ATUALIZADO depois dessa reserva -- opcionais pra não quebrar
    quem já chamava essa função sem eles."""
    assunto = f"Agendamento confirmado — {data}"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Agendamento confirmado</h2>
        <p>Olá, {_esc(nome_medico)}! Sua reserva foi confirmada:</p>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding:6px 0; color:#555;">Consultório:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(consultorio_nome)}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Data:</td>
                <td style="padding:6px 0; font-weight:bold;">{data}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Horário:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(horario)}</td></tr>
        </table>
        {_bloco_saldos_html(saldo_horas, saldo_ia)}
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_cancelamento_medico(nome_medico: str, consultorio_nome: str, data: str, horario: str,
                                   destinatario: str, saldo_horas: float | None = None,
                                   saldo_ia: float | None = None) -> bool:
    """Item 5 (lado do médico): confirma que uma reserva foi cancelada.
    `saldo_horas`/`saldo_ia` (pedido do Paulo em 22/09/2026) mostram o
    saldo JÁ ATUALIZADO depois desse cancelamento (com o reembolso de
    horas já aplicado, se houve) -- opcionais pra não quebrar quem já
    chamava essa função sem eles."""
    assunto = f"Agendamento cancelado — {data}"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Agendamento cancelado</h2>
        <p>Olá, {_esc(nome_medico)}! A reserva abaixo foi cancelada:</p>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding:6px 0; color:#555;">Consultório:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(consultorio_nome)}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Data:</td>
                <td style="padding:6px 0; font-weight:bold;">{data}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Horário:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(horario)}</td></tr>
        </table>
        {_bloco_saldos_html(saldo_horas, saldo_ia)}
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Sistema Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)


def notificar_agendamento_paciente(nome_paciente: str, nome_medico: str, data: str, hora_confirmada: str,
                                    endereco: str, consultorio_nome: str, destinatario: str) -> bool:
    """Item 5 (lado do paciente): mandado só quando o médico clica em
    "Enviar e-mail" na tela "Minha agenda", com a hora já confirmada por
    ele. `endereco` vem pronto formatado (ver
    creditos_service.endereco_padrao_formatado)."""
    assunto = f"Sua consulta com {nome_medico} — {data}"
    corpo_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px;">
        <h2 style="color: #1a3c5e;">Confirmação de consulta</h2>
        <p>Olá, {_esc(nome_paciente)}! Sua consulta com <strong>{_esc(nome_medico)}</strong> está
        confirmada:</p>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td style="padding:6px 0; color:#555;">Data:</td>
                <td style="padding:6px 0; font-weight:bold;">{data}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Horário:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(hora_confirmada)}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Consultório:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(consultorio_nome)}</td></tr>
            <tr><td style="padding:6px 0; color:#555;">Endereço:</td>
                <td style="padding:6px 0; font-weight:bold;">{_esc(endereco)}</td></tr>
        </table>
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Notificação automática — Lifemax
        </p>
    </div>
    """
    return enviar_email([destinatario], assunto, corpo_html)
