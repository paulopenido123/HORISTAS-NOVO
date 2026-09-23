"""
Autenticação dos médicos: primeiro acesso (agora com auto-cadastro —
o médico se cadastra sozinho, sem precisar que o admin crie antes) e
login normal.
"""
from flask import Blueprint, request, render_template, redirect, url_for, session, flash
from app.services import supabase_client as db
from app.services import creditos_service as creditos_db
from app.services import auth_service
from app.services import recuperacao_senha_service as rec_senha
from app.services import agenda_fixos_service
from app.extensions import limiter

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    erro = None
    etapa = "telefone"
    medico = None
    telefone_digitado = ""

    if request.method == "POST":
        etapa_enviada = request.form.get("etapa", "telefone")
        telefone_digitado = agenda_fixos_service.normalizar_telefone(request.form.get("telefone", "")) or ""

        if etapa_enviada == "telefone":
            medico = db.get_medico_by_telefone(telefone_digitado) if telefone_digitado else None

            if medico is None:
                # Telefone novo -> auto-cadastro (o próprio médico cria o
                # cadastro dele, sem precisar que o admin faça isso antes)
                etapa = "cadastro"
            elif creditos_db.medico_tem_senha(medico):
                erro = "Esse telefone já tem senha cadastrada. Use a tela de login."
            else:
                etapa = "senha"

        elif etapa_enviada == "cadastro":
            nome = request.form.get("nome", "").strip()
            especialidade = request.form.get("especialidade", "").strip()
            senha = request.form.get("senha", "")
            confirmar = request.form.get("confirmar_senha", "")

            if not telefone_digitado.isdigit():
                erro = "Telefone deve conter só números, com DDI e DDD (ex: 5531999999999)."
                etapa = "cadastro"
            elif not nome:
                erro = "Digite seu nome completo."
                etapa = "cadastro"
            elif len(senha) < 6:
                erro = "A senha precisa ter pelo menos 6 caracteres."
                etapa = "cadastro"
            elif senha != confirmar:
                erro = "As senhas não coincidem."
                etapa = "cadastro"
            elif db.get_medico_by_telefone(telefone_digitado) is not None:
                # alguem cadastrou esse telefone nesse meio-tempo (raro, mas possível)
                erro = "Esse telefone já foi cadastrado. Tente fazer login."
                etapa = "telefone"
            else:
                # autorizado=True (default) -- pedido do Paulo em
                # 23/09/2026 (itens 1 e 2): médico novo NÃO espera mais
                # liberação manual do admin pra poder reservar. Assim que
                # aceita o contrato, compra horas e completa o cadastro
                # (telefone, e-mail, especialidade, CPF, data de
                # nascimento e endereço -- ver reserva_service.
                # _CAMPOS_OBRIGATORIOS_PARA_RESERVAR), já pode reservar
                # consultório sozinho. O bloqueio manual (autorizado=False)
                # continua existindo em reserva_service.NaoAutorizadoError,
                # mas agora só como uma exceção rara que o admin aciona
                # manualmente em /admin/clientes (ex: suspender um médico
                # problemático), não mais o fluxo padrão de todo cadastro novo.
                novo_medico = db.criar_medico(nome, telefone_digitado, especialidade)
                creditos_db.definir_senha_medico(novo_medico["id"], auth_service.gerar_hash_senha(senha))
                auth_service.login_medico(novo_medico["id"])

                from app.services import notificacoes_operacionais_service as notif_op
                notif_op.avisar_admins(
                    f"👋 Novo médico se cadastrou pelo site: {nome} ({telefone_digitado}). "
                    f"O assistente de WhatsApp dele só é liberado depois do primeiro pagamento."
                )

                # Item 2 (pedido do Paulo em 11/09/2026): aviso por
                # E-MAIL pro(s) admin(s) além do WhatsApp acima -- mesmo
                # padrão gracioso de sempre (se ADMIN_EMAIL/SMTP não
                # estiverem configurados, só não manda, não quebra o
                # cadastro do médico).
                from app.config import Config
                destinatarios_admin = [e.strip() for e in (Config.ADMIN_EMAIL or "").split(",") if e.strip()]
                if destinatarios_admin:
                    from app.services import email_service
                    email_service.notificar_admin_novo_cadastro_pendente(nome, telefone_digitado, destinatarios_admin)

                return redirect(url_for("medico_painel.painel"))

        elif etapa_enviada == "senha":
            medico = db.get_medico_by_telefone(telefone_digitado)
            if medico is None:
                erro = "Telefone não encontrado."
                etapa = "telefone"
            elif creditos_db.medico_tem_senha(medico):
                erro = "Esse telefone já tem senha cadastrada. Use a tela de login."
            else:
                senha = request.form.get("senha", "")
                confirmar = request.form.get("confirmar_senha", "")
                if len(senha) < 6:
                    erro = "A senha precisa ter pelo menos 6 caracteres."
                    etapa = "senha"
                elif senha != confirmar:
                    erro = "As senhas não coincidem."
                    etapa = "senha"
                else:
                    creditos_db.definir_senha_medico(medico["id"], auth_service.gerar_hash_senha(senha))
                    auth_service.login_medico(medico["id"])
                    return redirect(url_for("medico_painel.painel"))

    return render_template("primeiro_acesso.html", erro=erro, etapa=etapa,
                            medico=medico, telefone_digitado=telefone_digitado)


@auth_bp.route("/confirmar-email/<token>")
def confirmar_email(token):
    """Item 1 (pedido do Paulo em 11/09/2026): link mandado por e-mail
    toda vez que o admin cadastra/altera o e-mail de um médico (Clientes
    > Inserir novo / Editar dados). Ao clicar, a ⭐ aparece do lado do
    e-mail dele na lista de Clientes do admin -- ver
    recuperacao_senha_service.confirmar_email."""
    medico = rec_senha.confirmar_email(token)
    return render_template("confirmar_email.html", medico=medico)


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per minute", methods=["POST"])
def login():
    erro = None
    if request.method == "POST":
        telefone = agenda_fixos_service.normalizar_telefone(request.form.get("telefone", ""))
        senha = request.form.get("senha", "")

        medico = db.get_medico_by_telefone(telefone) if telefone else None
        if medico is None or not auth_service.verificar_senha(senha, medico.get("senha_hash")):
            erro = "Telefone ou senha incorretos."
        else:
            auth_service.login_medico(medico["id"])
            destino = request.args.get("next") or url_for("medico_painel.painel")
            return redirect(destino)

    return render_template("login.html", erro=erro)


@auth_bp.route("/logout")
def logout():
    auth_service.logout_medico()
    return redirect(url_for("auth.login"))


@auth_bp.route("/esqueci-senha", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def esqueci_senha():
    enviado = False
    if request.method == "POST":
        telefone = agenda_fixos_service.normalizar_telefone(request.form.get("telefone", "")) or ""
        rec_senha.solicitar_recuperacao("medico", telefone)
        # Mensagem sempre igual, telefone cadastrado ou não -- evita que
        # alguém descubra, tentando telefones ao acaso, quais têm conta.
        enviado = True

    return render_template("esqueci_senha.html", enviado=enviado,
                            rota_login=url_for("auth.login"), tipo="medico")


@auth_bp.route("/redefinir-senha", methods=["GET", "POST"])
@limiter.limit("8 per minute", methods=["POST"])
def redefinir_senha():
    token = request.args.get("token", "") or request.form.get("token", "")
    erro = None
    sucesso = False

    registro = rec_senha.validar_token(token)
    primeiro_acesso = bool(registro) and registro.get("contexto") == "primeiro_acesso"

    # Pedido do Paulo em 21/09/2026: quem chega por um link de "primeiro
    # acesso" (migração de clientes do sistema antigo) precisa poder
    # conferir/corrigir o telefone (usado pra login em todo o sistema) e
    # o e-mail cadastrados, sem perder nenhum dado -- por isso a tela
    # mostra os dois campos já preenchidos, mas editáveis.
    medico = None
    telefone_valor = ""
    email_valor = ""
    if registro and primeiro_acesso and registro.get("tipo") == "medico":
        medico = db.get_medico_by_id(registro["usuario_id"])
        if medico is None:
            erro = "Esse cadastro não foi encontrado. Fale com a Lifemax."
            registro = None
        else:
            telefone_valor = medico.get("telefone", "")
            email_valor = medico.get("email") or ""

    if registro is None and erro is None:
        erro = "Esse link expirou ou já foi usado. Peça pra gerarem um novo."
    elif request.method == "POST" and registro is not None:
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar_senha", "")
        telefone_form = request.form.get("telefone", telefone_valor)
        email_form = request.form.get("email", email_valor)

        if primeiro_acesso:
            telefone_valor = agenda_fixos_service.normalizar_telefone(telefone_form) or ""
            email_valor = (email_form or "").strip()

        if len(senha) < 6:
            erro = "A senha precisa ter pelo menos 6 caracteres."
        elif senha != confirmar:
            erro = "As senhas não coincidem."
        elif primeiro_acesso and not telefone_valor.isdigit():
            erro = "Telefone deve conter só números, com DDI e DDD (ex: 5531999999999)."
        elif primeiro_acesso and email_valor and "@" not in email_valor:
            erro = "Digite um e-mail válido (ou deixe em branco)."
        elif primeiro_acesso and telefone_valor != medico.get("telefone") and \
                db.get_medico_by_telefone(telefone_valor) is not None:
            erro = "Esse telefone já está cadastrado para outro médico. Confira o número."
        elif not rec_senha.redefinir_senha(token, senha):
            erro = "Esse link expirou ou já foi usado. Peça pra gerarem um novo."
        else:
            sucesso = True
            if primeiro_acesso:
                db.atualizar_medico(
                    medico["id"], medico["nome"], telefone_valor,
                    medico.get("especialidade") or "", cpf_cnpj=medico.get("cpf_cnpj") or "",
                    email=email_valor or None,
                )
            # Pedido do Paulo em 11/09/2026: quem entra por um link de
            # "primeiro acesso" (mandado pelo admin pra um médico já
            # cadastrado -- ex: migração de clientes do sistema antigo)
            # não deve precisar dar mais um passo (ir pra tela de login e
            # digitar telefone/senha de novo); ao criar a senha, já cai
            # direto no painel dele. O fluxo de "esqueci minha senha"
            # (contexto='recuperacao') continua mostrando a tela de
            # sucesso normal, sem logar sozinho -- não faz sentido logar
            # automaticamente quem só estava trocando a senha.
            if primeiro_acesso and registro.get("tipo") == "medico":
                auth_service.login_medico(registro["usuario_id"])
                return redirect(url_for("medico_painel.painel"))

    return render_template(
        "redefinir_senha.html", erro=erro, sucesso=sucesso, token=token,
        rota_login=url_for("auth.login"), primeiro_acesso=primeiro_acesso,
        telefone_valor=telefone_valor, email_valor=email_valor,
    )
