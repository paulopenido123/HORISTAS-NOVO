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
from app.services import telefone_utils
from app.extensions import limiter

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Primeiro acesso por E-MAIL (22/10/2026, pedido do Paulo -- antes era por telefone):
    o profissional digita o e-mail que a Lifemax tem cadastrado e cria a senha.
    O auto-cadastro por telefone foi desativado: quem não é encontrado é orientado a falar com a Lifemax."""
    erro = None
    etapa = "email"
    medico = None
    email_digitado = (request.form.get("email", "") or "").strip().lower()

    def _sem_senha(lista):
        return [m for m in lista if not creditos_db.medico_tem_senha(m)]

    if request.method == "POST":
        etapa_enviada = request.form.get("etapa", "email")
        encontrados = db.listar_medicos_por_email(email_digitado) if "@" in email_digitado else []
        pendentes = _sem_senha(encontrados)

        if not encontrados:
            erro = ("Não encontramos esse e-mail. Confira se é o mesmo e-mail informado à Lifemax ou fale com a "
                    "equipe pelos telefones (31) 99754-6473 ou (31) 97207-8423.")
        elif not pendentes:
            erro = "Esse e-mail já tem senha cadastrada. Use a tela de login."
        elif etapa_enviada == "email":
            medico = pendentes[0]
            etapa = "senha"
        else:
            medico = pendentes[0]
            senha = request.form.get("senha", "")
            confirmar = request.form.get("confirmar_senha", "")
            etapa = "senha"
            if len(senha) < 6:
                erro = "A senha precisa ter pelo menos 6 caracteres."
            elif senha != confirmar:
                erro = "As senhas não coincidem."
            else:
                creditos_db.definir_senha_medico(medico["id"], auth_service.gerar_hash_senha(senha))
                auth_service.login_medico(medico["id"])
                return redirect(url_for("medico_painel.painel"))

    return render_template("primeiro_acesso.html", erro=erro, etapa=etapa,
                            medico=medico, email_digitado=email_digitado)


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
        # Um único campo aceita e-mail OU telefone (22/10/2026). Quem digita "@"
        # entra pelo e-mail; senão, pelo telefone cadastrado.
        identificador = (request.form.get("identificador") or request.form.get("telefone") or "").strip()
        senha = request.form.get("senha", "")

        medico = None
        if "@" in identificador:
            for candidato in db.listar_medicos_por_email(identificador):
                if auth_service.verificar_senha(senha, candidato.get("senha_hash")):
                    medico = candidato
                    break
        else:
            telefone = telefone_utils.normalizar_telefone(identificador)
            candidato = db.get_medico_by_telefone(telefone) if telefone else None
            if candidato is not None and auth_service.verificar_senha(senha, candidato.get("senha_hash")):
                medico = candidato

        if medico is None:
            erro = "E-mail/telefone ou senha incorretos."
        else:
            auth_service.login_medico(medico["id"])
            # "Lembrar dados no próximo acesso": mantém este aparelho
            # conectado por até 30 dias (cookie assinado e HttpOnly -- a
            # senha NUNCA é guardada em lugar nenhum).
            session["lembrar"] = request.form.get("lembrar") == "1"
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
        identificador = (request.form.get("identificador") or request.form.get("telefone") or "").strip()
        if "@" not in identificador:
            identificador = telefone_utils.normalizar_telefone(identificador) or ""
        rec_senha.solicitar_recuperacao("medico", identificador)
        # Mensagem sempre igual, e-mail/telefone cadastrado ou não -- evita que
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
    email_valor = ""
    if registro and primeiro_acesso and registro.get("tipo") == "medico":
        medico = db.get_medico_by_id(registro["usuario_id"])
        if medico is None:
            erro = "Esse cadastro não foi encontrado. Fale com a Lifemax."
            registro = None
        else:
            email_valor = medico.get("email") or ""

    if registro is None and erro is None:
        erro = "Esse link expirou ou já foi usado. Peça pra gerarem um novo."
    elif request.method == "POST" and registro is not None:
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar_senha", "")
        email_form = request.form.get("email", email_valor)

        if primeiro_acesso:
            email_valor = (email_form or "").strip().lower()

        if len(senha) < 6:
            erro = "A senha precisa ter pelo menos 6 caracteres."
        elif senha != confirmar:
            erro = "As senhas não coincidem."
        elif primeiro_acesso and (not email_valor or "@" not in email_valor or "." not in email_valor.split("@")[-1]):
            erro = "Digite um e-mail válido. Ele será usado para entrar no sistema."
        elif primeiro_acesso and any(m["id"] != medico["id"] for m in db.listar_medicos_por_email(email_valor)):
            erro = "Esse e-mail já está cadastrado para outro profissional. Confira o endereço."
        elif not rec_senha.redefinir_senha(token, senha):
            erro = "Esse link expirou ou já foi usado. Peça pra gerarem um novo."
        else:
            sucesso = True
            if primeiro_acesso:
                db.atualizar_medico(
                    medico["id"], medico["nome"], medico.get("telefone") or "",
                    medico.get("especialidade") or "", cpf_cnpj=medico.get("cpf_cnpj") or "",
                    email=email_valor,
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
        email_valor=email_valor,
    )
