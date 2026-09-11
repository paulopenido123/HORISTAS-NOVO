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
from app.services import google_login_service as glogin
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
                # autorizado=False -- pedido do Paulo em 10/09/2026: esse é
                # o auto-cadastro público, ninguém do admin conferiu esse
                # médico antes dele já poder logar. Nasce podendo logar e
                # comprar horas, mas bloqueado de RESERVAR consultório até
                # o admin clicar em "Liberar acesso" em /admin/clientes
                # (ver reserva_service.NaoAutorizadoError). Diferente do
                # import de agenda fixa em agenda_fixos_service.py, que
                # continua nascendo autorizado=True (default) porque quem
                # cadastra ali é o próprio admin, a partir de uma planilha
                # já conferida por ele -- não tem o mesmo risco.
                novo_medico = db.criar_medico(nome, telefone_digitado, especialidade, autorizado=False)
                creditos_db.definir_senha_medico(novo_medico["id"], auth_service.gerar_hash_senha(senha))
                auth_service.login_medico(novo_medico["id"])

                from app.services import notificacoes_operacionais_service as notif_op
                notif_op.avisar_admins(
                    f"👋 Novo médico se cadastrou pelo site: {nome} ({telefone_digitado}). "
                    f"O assistente de WhatsApp dele só é liberado depois do primeiro pagamento."
                )

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


@auth_bp.route("/login/google")
def login_google():
    """Botão "Entrar com Google" da tela de login -- manda o médico pro
    Google escolher a conta. Não substitui o login por telefone/senha,
    é só mais uma porta de entrada pra quem já é cadastrado."""
    try:
        url = glogin.gerar_url_autorizacao()
    except glogin.GoogleLoginNaoConfiguradoError as e:
        flash(str(e), "erro")
        return redirect(url_for("auth.login"))
    return redirect(url)


@auth_bp.route("/login/google/callback")
def login_google_callback():
    """O Google chama essa URL de volta, com um 'code' de uso único.
    Trocamos esse código só pela identidade da conta (e-mail/nome) --
    nunca por acesso a nada mais -- e casamos com um médico já
    cadastrado pelo e-mail. Não cadastra médico novo por aqui (ver
    google_login_service.py para o motivo: falta o telefone, obrigatório
    pro assistente de WhatsApp)."""
    code = request.args.get("code")
    if not code:
        flash("Não consegui completar o login com o Google. Tente de novo.", "erro")
        return redirect(url_for("auth.login"))

    try:
        identidade = glogin.obter_identidade_da_conta(code)
    except glogin.GoogleLoginNaoConfiguradoError as e:
        flash(str(e), "erro")
        return redirect(url_for("auth.login"))
    except Exception as e:
        # Antes, esse erro sumia sem deixar rastro nenhum -- só a
        # mensagem genérica na tela, sem dar pra saber o motivo real, e
        # o log do Render era difícil de achar na prática. Agora mostra
        # o tipo do erro direto na própria tela (mais fácil de me
        # mandar um print) e ainda imprime o traceback completo no log,
        # pra quando precisar do detalhe fino.
        import traceback
        traceback.print_exc()
        flash(
            f"Não consegui confirmar sua conta Google agora (erro técnico: {type(e).__name__}). "
            "Tente de novo em instantes ou avise o suporte com esse código.",
            "erro",
        )
        return redirect(url_for("auth.login"))

    medico = db.get_medico_por_email(identidade["email"]) if identidade["email"] else None
    if medico is None:
        flash(
            f"Não encontrei nenhum cadastro com o e-mail \"{identidade['email']}\" (o mesmo da "
            "conta Google que você escolheu). Confirme com a secretária ou o administrador que "
            "seu cadastro já foi feito e que esse é exatamente o e-mail cadastrado, ou entre com "
            "telefone e senha.",
            "erro",
        )
        return redirect(url_for("auth.login"))

    auth_service.login_medico(medico["id"])
    return redirect(url_for("medico_painel.painel"))


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
    if registro is None:
        erro = "Esse link expirou ou já foi usado. Peça pra gerarem um novo."
    elif request.method == "POST":
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar_senha", "")
        if len(senha) < 6:
            erro = "A senha precisa ter pelo menos 6 caracteres."
        elif senha != confirmar:
            erro = "As senhas não coincidem."
        elif not rec_senha.redefinir_senha(token, senha):
            erro = "Esse link expirou ou já foi usado. Peça pra gerarem um novo."
        else:
            sucesso = True
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

    return render_template("redefinir_senha.html", erro=erro, sucesso=sucesso, token=token,
                            rota_login=url_for("auth.login"), primeiro_acesso=primeiro_acesso)
