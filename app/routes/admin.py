from datetime import date, datetime, timedelta, timezone
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.services import supabase_client as db
from app.services import auth_service
from app.services import neon_storage
from app.services import creditos_service as creditos_db
from app.services import relatorios_service
from app.services import recuperacao_senha_service as rec_senha
from app.services import nfe_service
from app.services import template_service
from app.services import reserva_service
from app.extensions import csrf, limiter
from app.services import usuarios_admin_service as usuarios_admin
import secrets

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def _admin(view):
    return auth_service.requer_admin(view)


def _admin_total(view):
    """Só perfil Administrador (a secretária não acessa Horas, Relatórios, Usuários nem altera saldo)."""
    return auth_service.requer_admin_total(view)


@admin_bp.context_processor
def _perfil_admin_nos_templates():
    """Menus/atalhos escondem o que a secretária não pode usar."""
    perfil = auth_service.admin_perfil()
    return {'admin_perfil': perfil, 'admin_total': perfil == 'admin'}


@admin_bp.route('/login', methods=['GET','POST'])
@limiter.limit("10 per minute", methods=["POST"])
def admin_login():
    erro = None
    if request.method == 'POST':
        ident = request.form.get('identificador', '').strip()
        senha = request.form.get('senha', '')
        usuario = usuarios_admin.autenticar(ident, senha) if ident else None
        if usuario:
            auth_service.login_admin(usuario['id'])
            return redirect(request.args.get('next') or url_for('admin.dashboard'))
        # Transição: senha única antiga (ADMIN_PASSWORD) só vale enquanto não há usuário ativo cadastrado.
        from app.config import Config
        if (not ident and senha and Config.ADMIN_PASSWORD and secrets.compare_digest(senha, Config.ADMIN_PASSWORD)
                and usuarios_admin.contar_ativos() == 0):
            auth_service.login_admin()
            return redirect(request.args.get('next') or url_for('admin.dashboard'))
        erro = 'E-mail/telefone ou senha incorretos, ou usuário bloqueado.'
    return render_template('admin_login.html', erro=erro, transicao=usuarios_admin.contar_ativos() == 0)


@admin_bp.route('/esqueci-senha', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def admin_esqueci_senha():
    """Recuperação de senha do acesso administrativo: reenvia o link de acesso ao e-mail cadastrado.
    A resposta é sempre a mesma, exista o e-mail ou não."""
    enviado = False
    if request.method == 'POST':
        usuarios_admin.solicitar_recuperacao(request.form.get('email', ''))
        enviado = True
    return render_template('admin_esqueci_senha.html', enviado=enviado)


@admin_bp.route('/logout')
def admin_logout():
    auth_service.logout_admin()
    return redirect(url_for('admin.admin_login'))


@admin_bp.route('')
@_admin
def dashboard():
    consultorios = db.listar_todos_consultorios()
    medicos = db.listar_medicos_ativos()
    reservas = db.get_client().table('reservas').select('id,status,data,consultorio_id,medico_id,criado_em,consultorios(nome),medicos(nome)').order('data', desc=True).limit(30).execute().data
    # Aviso vermelho no topo do dashboard quando tem cliente esperando
    # liberação -- pedido do Paulo em 10/09/2026: antes só dava pra saber
    # entrando em /admin/clientes; agora aparece já na primeira tela.
    medicos_pendentes = (
        db.get_client().table('medicos').select('id, nome')
        .eq('ativo', True).eq('autorizado', False).order('nome').execute().data
    )
    return render_template('admin_dashboard.html', consultorios=consultorios, medicos=medicos, reservas=reservas,
                            medicos_pendentes=medicos_pendentes)


_NOMES_MESES = [
    None, 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
    'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro',
]


@admin_bp.route('/horas')
@_admin_total
def horas():
    """Painel "Horas" do admin -- pedido do Paulo em 10/09/2026 (mandou
    print de uma tela parecida do sistema maior original): horas
    vendidas e horas utilizadas num mês escolhido, mais o saldo total de
    horas "na praça" (soma do saldo de todo mundo, sem filtro de mês --
    ver creditos_service.estatisticas_horas)."""
    hoje = date.today()
    mes_valor = request.args.get('mes') or f"{hoje.year:04d}-{hoje.month:02d}"
    try:
        ano, mes = (int(p) for p in mes_valor.split('-', 1))
        if not (1 <= mes <= 12):
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
        mes_valor = f"{ano:04d}-{mes:02d}"

    stats = creditos_db.estatisticas_horas(mes, ano)
    endereco = creditos_db.obter_endereco_padrao()
    return render_template(
        'admin_horas.html', stats=stats, mes=mes, ano=ano,
        mes_valor=mes_valor, mes_nome=_NOMES_MESES[mes], endereco=endereco,
        inicio_contagem='/'.join(reversed(creditos_db.DATA_INICIO_CONTAGEM_HORAS.split('-'))),
    )


@admin_bp.route('/horas/endereco-padrao', methods=['POST'])
@_admin_total
def atualizar_endereco_padrao():
    """Salva o endereço padrão da Lifemax (usado no e-mail de agendamento
    pro paciente -- ver reserva_service.enviar_confirmacao_consulta)
    -- pedido do Paulo em 11/09/2026."""
    creditos_db.atualizar_endereco_padrao(
        rua=(request.form.get('rua') or '').strip(),
        numero=(request.form.get('numero') or '').strip(),
        complemento=(request.form.get('complemento') or '').strip(),
        bairro=(request.form.get('bairro') or '').strip(),
        cidade=(request.form.get('cidade') or '').strip(),
        estado=(request.form.get('estado') or '').strip()[:2].upper(),
        cep=(request.form.get('cep') or '').strip(),
    )
    flash('Endereço padrão atualizado.', 'ok')
    return redirect(url_for('admin.horas'))


@admin_bp.route('/clientes')
@_admin
def clientes():
    """Lista de médicos cadastrados pra uso administrativo -- pedido do
    Paulo em 10/09/2026, junto com o botão "Alterar saldo" (ver rota
    abaixo) pra creditar/debitar saldo manualmente sem precisar mexer
    direto no banco (ex: crédito de teste, cortesia, correção de erro).
    """
    busca = (request.args.get('busca') or '').strip().lower()
    lista = db.get_client().table('medicos').select('*').order('nome').execute().data
    if busca:
        lista = [
            m for m in lista
            if busca in (m.get('nome') or '').lower()
            or busca in (m.get('telefone') or '')
            or busca in (m.get('email') or '').lower()
        ]
    # Saldo de horas de cada um, pra mostrar na lista.
    #
    # ⚠️ Corrigido em 11/09/2026 (a tela estava demorando muito pra abrir
    # depois da migração dos ~130 médicos horistas do Life Max): antes,
    # esse loop chamava creditos_db.saldo_em_horas_medico(m['id']) PRA CADA MÉDICO -- e
    # saldo_em_horas_medico, por baixo dos panos, ainda rebuscava a lista
    # de pacotes de hora (listar_pacotes_horas()) do zero a cada chamada.
    # Isso dava 3 consultas SEPARADAS ao banco por médico (~390 no total
    # com 130 médicos) só pra abrir essa tela -- e o "*" do select acima
    # já tinha trazido saldo_creditos de todo mundo de uma vez!
    # Agora: busca os pacotes de hora UMA única vez (fora do loop) e
    # calcula o saldo em horas direto dos dados que já vieram no
    # select("*"), sem nenhuma consulta extra por médico.
    pacotes_horas = creditos_db.listar_pacotes_horas()
    for m in lista:
        m['saldo_horas'] = creditos_db.estimar_horas_compraveis(m.get('saldo_creditos') or 0, pacotes_horas)
    return render_template('admin_clientes.html', medicos=lista, busca=request.args.get('busca') or '')


@admin_bp.route('/clientes/<medico_id>/autorizacao', methods=['POST'])
@_admin
def autorizacao_cliente(medico_id):
    """Liga/desliga o toggle "Usuário autorizado no sistema" -- pedido do
    Paulo em 10/09/2026 (print da tela do sistema maior original). Quem se
    autocadastra pelo site (/primeiro-acesso) nasce NÃO autorizado e o
    nome aparece em vermelho na lista de Clientes até o admin clicar em
    "Liberar acesso" aqui; enquanto não liberado, o médico consegue logar
    e comprar horas normalmente mas fica bloqueado de RESERVAR consultório
    (ver reserva_service.NaoAutorizadoError)."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        flash('Cliente não encontrado.', 'erro')
        return redirect(url_for('admin.clientes'))
    novo_valor = request.form.get('autorizado') == '1'
    db.definir_autorizacao_medico(medico_id, novo_valor)
    if novo_valor:
        flash(f'Acesso de {medico["nome"]} liberado -- já pode reservar consultório.', 'ok')
        # Item 3 (pedido do Paulo em 11/09/2026): avisa o médico por
        # e-mail que ele já está apto a usar o sistema/comprar horas --
        # só quando ele TEM e-mail cadastrado; sem SMTP configurado só
        # não manda (padrão de sempre).
        if medico.get('email'):
            from app.services import email_service
            email_service.notificar_acesso_liberado(medico['nome'], medico['email'])
    else:
        flash(f'Acesso de {medico["nome"]} bloqueado -- não vai conseguir reservar consultório até ser liberado de novo.', 'ok')
    return redirect(url_for('admin.clientes', busca=request.form.get('busca') or ''))


@admin_bp.route('/clientes/<medico_id>/enviar-link', methods=['POST'])
@_admin
def enviar_link_cliente(medico_id):
    """Manda por e-mail um link de primeiro acesso pra um médico JÁ
    CADASTRADO -- pedido do Paulo em 11/09/2026, pra reaproveitar clientes
    importados do sistema antigo (Life Max): em vez de pedir pra cada um
    se cadastrar do zero (nome, telefone etc., que já temos), o admin só
    confere/digita o e-mail aqui e manda o link. O médico clica, cria uma
    senha (única etapa que falta) e já entra direto no painel dele --
    ver auth.redefinir_senha, que agora loga automaticamente quando o
    token é desse tipo (contexto='primeiro_acesso').

    Exige que EMAIL_FROM/SMTP_* estejam configurados (ver .env.example,
    seção "Email") -- sem isso, `email_service.enviar_email` levanta erro
    e a página mostra a mensagem pro admin, sem quebrar o resto da tela."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        flash('Cliente não encontrado.', 'erro')
        return redirect(url_for('admin.clientes'))

    email = (request.form.get('email') or '').strip()
    try:
        resultado = rec_senha.enviar_link_primeiro_acesso(medico_id, email)
    except ValueError as e:
        flash(str(e), 'erro')
        return redirect(url_for('admin.clientes', busca=request.form.get('busca') or ''))
    except Exception as e:
        flash(
            f'Não consegui enviar o e-mail agora (erro técnico: {type(e).__name__}). '
            'Confira se o envio de e-mail (SMTP_*/EMAIL_FROM) está configurado no sistema.',
            'erro',
        )
        return redirect(url_for('admin.clientes', busca=request.form.get('busca') or ''))

    if resultado['enviado']:
        flash(f'Link de acesso enviado para {email} ({medico["nome"]}) -- o link não expira.', 'ok')
    else:
        # O token já foi criado e o link é válido -- só o envio automático
        # por e-mail falhou (SMTP ainda não configurado). Mostra o link pra
        # o admin poder mandar na mão (WhatsApp, etc.) enquanto isso.
        flash(
            'O envio automático de e-mail ainda não está configurado neste sistema '
            '(SMTP_HOST/SMTP_USER/SMTP_PASSWORD/EMAIL_FROM em .env -- veja .env.example, seção "Email"). '
            f'O link já foi gerado mesmo assim (não expira), copie e mande na mão: {resultado["link"]}',
            'erro',
        )
    return redirect(url_for('admin.clientes', busca=request.form.get('busca') or ''))


@admin_bp.route('/clientes/<medico_id>/ajustar-saldo', methods=['POST'])
@_admin_total
def ajustar_saldo_cliente(medico_id):
    """Credita (valor positivo) ou debita (valor negativo) saldo de um
    médico direto pelo painel admin -- vira uma
    transação tipo 'ajuste' em creditos_transacoes, igual qualquer outro
    lançamento (fica no histórico do médico, não é uma mudança
    "invisível" direto no banco).

    Pedido do Paulo em 10/09/2026: a carteira de Salas/Horas é sempre
    medida em HORAS (não em dinheiro) em qualquer lugar do sistema, então
    esse ajuste também é feito em horas quando a carteira é 'salas' -- o
    admin digita "15" (horas), e aqui a gente converte pro valor em R$
    equivalente (preço da hora avulsa) só pra manter o mesmo mecanismo
    interno de saldo que o resto do sistema usa.

    ⚠️ Em 11/09/2026 o botão "Alterar saldo" saiu da lista de clientes e
    foi pra dentro da tela "Visualizar" de cada cliente (pedido do Paulo)
    -- por isso todo redirect aqui agora volta pra
    admin.visualizar_cliente (não mais admin.clientes)."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        flash('Cliente não encontrado.', 'erro')
        return redirect(url_for('admin.clientes'))

    try:
        quantidade = float((request.form.get('quantidade') or '0').replace(',', '.'))
    except ValueError:
        flash('Quantidade inválida -- use só números (horas, ex: 15 ou -5).', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    if quantidade == 0:
        flash('Informe uma quantidade diferente de zero (positivo credita, negativo debita).', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    descricao = (request.form.get('descricao') or '').strip() or 'Ajuste manual pelo admin'

    horas = round(quantidade)  # carteira de horas trabalha sempre em números inteiros de hora
    if horas == 0:
        flash('Informe uma quantidade de horas diferente de zero.', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))
    valor = round(horas * creditos_db.preco_hora_avulsa(), 2)
    quantidade_horas_param = abs(horas)

    try:
        creditos_db.registrar_transacao(
            medico_id, tipo='ajuste', valor=valor, descricao=descricao, carteira='salas',
            quantidade_horas=quantidade_horas_param,
        )
    except Exception as e:
        flash(f'Não foi possível ajustar o saldo: {e}', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    acao = 'creditado' if quantidade > 0 else 'debitado'
    flash(f'Saldo de Salas/Horas de {medico["nome"]} {acao} em {abs(horas)}h.', 'ok')
    return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))


@admin_bp.route('/api/clientes/enviar-email-lote', methods=['POST'])
@_admin
def api_clientes_enviar_email_lote():
    """Pedido do Paulo em 23/09/2026 (item 2): botão "Enviar e-mail para
    clientes" -- o admin seleciona uma lista de médicos (checkbox na tela
    de Clientes), escreve uma mensagem e, opcionalmente, anexa uma
    imagem promocional (mostrada embutida no corpo do e-mail, não como
    anexo pra baixar), e manda um e-mail PRA CADA médico selecionado que
    tenha e-mail cadastrado.

    Manda um e-mail por vez (em vez de um e-mail só com todo mundo no
    "Para:") de propósito -- pra não expor o e-mail de um cliente pros
    outros (LGPD, ver contrato_service cláusula 7ª)."""
    from app.services import email_service

    medico_ids = request.form.getlist('medico_ids')
    assunto = (request.form.get('assunto') or '').strip() or 'Aviso Lifemax'
    mensagem = (request.form.get('mensagem') or '').strip()
    arquivo = request.files.get('imagem')

    if not medico_ids:
        return {'erro': 'Selecione pelo menos um cliente.'}, 400
    if not mensagem:
        return {'erro': 'Escreva uma mensagem.'}, 400

    imagem_bytes = None
    imagem_mimetype = None
    if arquivo and arquivo.filename:
        if not (arquivo.mimetype or '').startswith('image/'):
            return {'erro': 'O arquivo anexado precisa ser uma imagem.'}, 400
        imagem_bytes = arquivo.read()
        imagem_mimetype = arquivo.mimetype

    # Corpo do e-mail: a mensagem digitada pelo admin (uma linha por
    # parágrafo) + a imagem embutida no topo, se tiver.
    from app.services.email_service import _esc
    paragrafos = "".join(f"<p>{_esc(linha)}</p>" for linha in mensagem.splitlines() if linha.strip())
    corpo_imagem = '<p><img src="cid:promo" style="max-width:100%; border-radius:8px;"></p>' if imagem_bytes else ''
    corpo_html = f"""
    <div style="font-family:Arial,sans-serif; color:#102A43; max-width:560px;">
      {corpo_imagem}
      {paragrafos}
      <p style="margin-top:24px; color:#62788A; font-size:12px;">Lifemax Coworking</p>
    </div>
    """

    enviados = []
    sem_email = []
    falhas = []
    for medico_id in medico_ids:
        medico = db.get_medico_by_id(medico_id)
        if not medico:
            continue
        if not medico.get('email'):
            sem_email.append(medico['nome'])
            continue
        imagens_inline = [("promo", imagem_bytes, imagem_mimetype)] if imagem_bytes else None
        try:
            ok = email_service.enviar_email([medico['email']], assunto, corpo_html, imagens_inline=imagens_inline)
        except Exception:
            ok = False
        if ok:
            enviados.append(medico['nome'])
        else:
            falhas.append(medico['nome'])

    return {'enviados': enviados, 'sem_email': sem_email, 'falhas': falhas}


@admin_bp.route('/api/clientes/enviar-link-lote', methods=['POST'])
@_admin
def api_clientes_enviar_link_lote():
    """Pedido do Paulo em 23/09/2026 (item 3): botão "Enviar link de
    acesso" em lote -- mesma coisa que o "Enviar link por e-mail" que já
    existia por cliente (ver enviar_link_cliente acima e
    rec_senha.enviar_link_primeiro_acesso), só que aplicado de uma vez
    pra uma lista de médicos selecionados. Só manda pra quem já tem
    e-mail cadastrado (sem um campo novo pra digitar e-mail um por um,
    já que é uma ação em massa)."""
    medico_ids = request.form.getlist('medico_ids')
    if not medico_ids:
        return {'erro': 'Selecione pelo menos um cliente.'}, 400

    enviados = []
    sem_email = []
    falhas = []
    for medico_id in medico_ids:
        medico = db.get_medico_by_id(medico_id)
        if not medico:
            continue
        if not medico.get('email'):
            sem_email.append(medico['nome'])
            continue
        try:
            resultado = rec_senha.enviar_link_primeiro_acesso(medico_id, medico['email'])
        except Exception:
            falhas.append(medico['nome'])
            continue
        if resultado['enviado']:
            enviados.append(medico['nome'])
        else:
            falhas.append(medico['nome'])

    return {'enviados': enviados, 'sem_email': sem_email, 'falhas': falhas}


@admin_bp.route('/clientes/novo', methods=['GET', 'POST'])
@_admin
def novo_cliente():
    """"Inserir novo" -- pedido do Paulo em 11/09/2026: cadastra um cliente
    (médico) manualmente pelo admin, com os mesmos campos padrão que o
    sistema já usa em qualquer outro cadastro de médico (ver
    supabase_client.criar_medico)."""
    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        telefone = (request.form.get('telefone') or '').strip()
        if not nome or not telefone:
            flash('Nome e telefone são obrigatórios.', 'erro')
            return redirect(url_for('admin.novo_cliente'))
        if db.get_medico_by_telefone(telefone) is not None:
            flash('Já existe um cliente cadastrado com esse telefone.', 'erro')
            return redirect(url_for('admin.novo_cliente'))

        convenios = [c.strip() for c in (request.form.get('convenios') or '').split(',') if c.strip()]
        medico = db.criar_medico(
            nome=nome,
            telefone=telefone,
            especialidade=(request.form.get('especialidade') or '').strip(),
            # Pedido do Paulo em 30/09/2026: todo médico cadastrado é
            # "avulso" -- não existe mais escolha de tipo de vínculo no
            # formulário (a tela "Agenda Horistas" e a Agenda Fixos foram
            # removidas do sistema).
            tipo_vinculo='avulso',
            email=(request.form.get('email') or '').strip(),
            crm=(request.form.get('crm') or '').strip(),
            cpf_cnpj=(request.form.get('cpf_cnpj') or '').strip(),
            endereco_cep=(request.form.get('endereco_cep') or '').strip(),
            endereco_rua=(request.form.get('endereco_rua') or '').strip(),
            endereco_numero=(request.form.get('endereco_numero') or '').strip(),
            endereco_complemento=(request.form.get('endereco_complemento') or '').strip(),
            endereco_bairro=(request.form.get('endereco_bairro') or '').strip(),
            endereco_cidade=(request.form.get('endereco_cidade') or '').strip(),
            endereco_estado=(request.form.get('endereco_estado') or '').strip()[:2].upper(),
            convenios=convenios,
            autorizado=True,
        )
        # Cadastrado manualmente pelo admin (mesma lógica de sempre pra
        # importações/cadastros feitos por quem já confere os dados antes
        # -- ver comentário em scripts_migracao/importar_horistas_lifemax.py):
        # já nasce com termo aceito, não precisa passar pela tela de termo.
        db.get_client().table('medicos').update({'termo_aceito': True}).eq('id', medico['id']).execute()

        # Item 1 (pedido do Paulo em 11/09/2026): se já nasceu com
        # e-mail, manda o link de confirmação -- a ⭐ aparece do lado do
        # e-mail na lista de Clientes assim que ele confirmar.
        if medico.get('email'):
            rec_senha.enviar_confirmacao_email(medico['id'], medico['email'])

        flash(f'Cliente "{nome}" cadastrado com sucesso.', 'ok')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico['id']))

    return render_template('admin_cliente_form.html', medico=None, modo='novo')


@admin_bp.route('/clientes/<medico_id>', methods=['GET'])
@_admin
def visualizar_cliente(medico_id):
    """Tela "Visualizar" de um cliente -- pedido do Paulo em 11/09/2026:
    mostra todos os dados cadastrados (telefone, e-mail etc.) numa tela
    separada, com os botões "Editar dados" e "Alterar saldo" (esse último
    tirado da lista de clientes e trazido pra cá) e o histórico de
    transações + saldo de horas (mesma listagem/formatação usada no
    "Histórico" do painel do próprio médico -- ver
    creditos_service.listar_transacoes_medico)."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        flash('Cliente não encontrado.', 'erro')
        return redirect(url_for('admin.clientes'))
    medico['saldo_horas'] = creditos_db.saldo_em_horas_medico(medico_id)
    transacoes = creditos_db.listar_transacoes_medico(medico_id, limite=200)
    return render_template('admin_cliente_visualizar.html', medico=medico, transacoes=transacoes)


@admin_bp.route('/clientes/<medico_id>/editar', methods=['GET', 'POST'])
@_admin
def editar_cliente(medico_id):
    """Botão "Editar" dentro da tela "Visualizar" -- pedido do Paulo em
    11/09/2026."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        flash('Cliente não encontrado.', 'erro')
        return redirect(url_for('admin.clientes'))

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        telefone = (request.form.get('telefone') or '').strip()
        if not nome or not telefone:
            flash('Nome e telefone são obrigatórios.', 'erro')
            return redirect(url_for('admin.editar_cliente', medico_id=medico_id))
        outro = db.get_medico_by_telefone(telefone)
        if outro and outro['id'] != medico_id:
            flash('Já existe OUTRO cliente cadastrado com esse telefone.', 'erro')
            return redirect(url_for('admin.editar_cliente', medico_id=medico_id))

        convenios = [c.strip() for c in (request.form.get('convenios') or '').split(',') if c.strip()]
        email_antigo = medico.get('email') or ''
        email_novo = (request.form.get('email') or '').strip()
        db.atualizar_medico(
            medico_id=medico_id,
            nome=nome,
            telefone=telefone,
            especialidade=(request.form.get('especialidade') or '').strip(),
            cpf_cnpj=(request.form.get('cpf_cnpj') or '').strip(),
            email=email_novo,
            crm=(request.form.get('crm') or '').strip(),
            endereco_cep=(request.form.get('endereco_cep') or '').strip(),
            endereco_rua=(request.form.get('endereco_rua') or '').strip(),
            endereco_numero=(request.form.get('endereco_numero') or '').strip(),
            endereco_complemento=(request.form.get('endereco_complemento') or '').strip(),
            endereco_bairro=(request.form.get('endereco_bairro') or '').strip(),
            endereco_cidade=(request.form.get('endereco_cidade') or '').strip(),
            endereco_estado=(request.form.get('endereco_estado') or '').strip()[:2].upper(),
            convenios=convenios,
        )

        # Item 1 (pedido do Paulo em 11/09/2026): se o e-mail mudou (ou
        # nasceu agora), a confirmação anterior não vale mais pro e-mail
        # novo -- tira a ⭐ e manda um novo link de confirmação.
        if email_novo and email_novo != email_antigo:
            db.definir_email_confirmado(medico_id, False)
            rec_senha.enviar_confirmacao_email(medico_id, email_novo)

        flash(f'Dados de "{nome}" atualizados.', 'ok')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    return render_template('admin_cliente_form.html', medico=medico, modo='editar')


@admin_bp.route('/relatorios')
@_admin_total
def relatorios():
    """Aba "Relatórios" -- pedido do Paulo em 10/09/2026, print de tela do
    sistema maior original: 2 relatórios (Agendamentos e Transações),
    cada um com seus próprios filtros. Ver relatorios_service.py pra
    entender como cada um é montado a partir do que esse pacote reduzido
    realmente guarda.

    "Transações ainda não faturadas" / "Transações faturadas" foram
    adicionados em 11/09/2026 (junto com o botão "Emitir NF") -- ao
    contrário de "Transações" (extrato em horas, creditos_transacoes),
    esses dois leem pagamentos_pix (os pagamentos em R$ recebidos de
    verdade) e separam pelo status da nota fiscal."""
    tipo = request.args.get('tipo', 'agendamentos')
    if tipo not in ('agendamentos', 'transacoes', 'nao_faturadas', 'faturadas', 'receitas'):
        tipo = 'agendamentos'

    consultorios = db.listar_todos_consultorios()
    medicos = db.listar_medicos_ativos()

    filtros = {
        'data_inicio': request.args.get('data_inicio', '').strip(),
        'data_fim': request.args.get('data_fim', '').strip(),
        'consultorio_id': request.args.get('consultorio_id', '').strip(),
        'medico_id': request.args.get('medico_id', '').strip(),
        'cliente': request.args.get('cliente', '').strip(),
        'operacao': request.args.get('operacao', '').strip(),
        'ordenar': request.args.get('ordenar', 'desc').strip() or 'desc',
    }

    total_horas = None
    total_valor = None
    resumo_dias = []
    ranking = []
    visao_receitas = 'pagamentos'
    mes_receitas = request.args.get('mes', '').strip()
    if tipo == 'receitas':
        # "Receitas" (22/10/2026): tudo que entrou de dinheiro, por data de pagamento.
        # Sem filtro, mostra os últimos 120 dias; "mes" (AAAA-MM) vale mais que de/até.
        ini, fim = relatorios_service.periodo_receitas(filtros['data_inicio'], filtros['data_fim'], mes_receitas)
        filtros['data_inicio'], filtros['data_fim'] = ini, fim
        linhas, resumo_dias, total_valor = relatorios_service.listar_receitas(
            ini, fim, medico_id=filtros['medico_id'] or None, cliente_busca=filtros['cliente'])
        visao_receitas = 'profissionais' if request.args.get('visao') == 'profissionais' else 'pagamentos'
        ranking = relatorios_service.ranking_profissionais(linhas) if visao_receitas == 'profissionais' else []
        if request.args.get('formato') == 'csv':
            import csv, io
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=';')
            if visao_receitas == 'profissionais':
                w.writerow(['Profissional', 'Compras', 'Total (R$)'])
                for d in ranking:
                    w.writerow([d['nome'], d['compras'], f"{d['total']:.2f}".replace('.', ',')])
            else:
                w.writerow(['Data', 'Hora', 'Profissional', 'Forma', 'Descrição', 'Valor (R$)'])
                for l in linhas:
                    w.writerow([f"{l['data'][8:10]}/{l['data'][5:7]}/{l['data'][:4]}", l['hora'], l['cliente'], l['forma'],
                                l['descricao'], f"{l['valor']:.2f}".replace('.', ',')])
            w.writerow([]); w.writerow(['TOTAL', len(linhas), f"{total_valor:.2f}".replace('.', ',')])
            from flask import Response
            return Response('\ufeff' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                            headers={'Content-Disposition': f'attachment; filename=receitas_{ini}_a_{fim}.csv'})
    elif tipo == 'transacoes':
        linhas, total_horas = relatorios_service.listar_transacoes(
            data_inicio=filtros['data_inicio'] or None, data_fim=filtros['data_fim'] or None,
            medico_id=filtros['medico_id'] or None, cliente_busca=filtros['cliente'],
            ordenar=filtros['ordenar'],
        )
    elif tipo in ('nao_faturadas', 'faturadas'):
        linhas, total_valor = relatorios_service.listar_faturamento(
            faturadas=(tipo == 'faturadas'),
            data_inicio=filtros['data_inicio'] or None, data_fim=filtros['data_fim'] or None,
            medico_id=filtros['medico_id'] or None, cliente_busca=filtros['cliente'],
            ordenar=filtros['ordenar'],
        )
    else:
        linhas = relatorios_service.listar_agendamentos(
            data_inicio=filtros['data_inicio'] or None, data_fim=filtros['data_fim'] or None,
            consultorio_id=filtros['consultorio_id'] or None, medico_id=filtros['medico_id'] or None,
            cliente_busca=filtros['cliente'], operacao=filtros['operacao'] or None,
            ordenar=filtros['ordenar'],
        )

    return render_template(
        'admin_relatorios.html', tipo=tipo, consultorios=consultorios, medicos=medicos,
        linhas=linhas, total_horas=total_horas, total_valor=total_valor, filtros=filtros,
        resumo_dias=resumo_dias, mes_receitas=mes_receitas, ranking=ranking, visao_receitas=visao_receitas,
        operacoes=relatorios_service.OPERACOES_AGENDAMENTOS,
        nfe_configurado=nfe_service.configurado(),
    )


@admin_bp.route('/pagamentos/<pagamento_id>/emitir-nf', methods=['POST'])
@_admin_total
def emitir_nf_pagamento(pagamento_id):
    """Botão "Emitir NF" em Relatórios > Transações ainda não faturadas --
    pedido do Paulo em 11/09/2026. Enquanto o certificado A1/CNPJ da
    Lifemax não estiverem configurados (NFE_* no .env), nfe_service.emitir_nf
    sempre levanta NfeNaoConfiguradaError e a tela mostra esse aviso, sem
    quebrar o resto (mesmo padrão do envio de e-mail/SMTP)."""
    pagamento = creditos_db.obter_pagamento_por_id(pagamento_id)
    if not pagamento:
        flash('Pagamento não encontrado.', 'erro')
        return redirect(url_for('admin.relatorios', tipo='nao_faturadas'))

    try:
        resultado = nfe_service.emitir_nf(pagamento)
    except nfe_service.NfeNaoConfiguradaError as e:
        flash(str(e), 'erro')
        return redirect(url_for('admin.relatorios', tipo='nao_faturadas'))
    except Exception as e:
        flash(
            f'Não consegui emitir a nota fiscal agora (erro técnico: {type(e).__name__}). '
            'Confira a configuração do certificado A1 (NFE_* no .env).',
            'erro',
        )
        return redirect(url_for('admin.relatorios', tipo='nao_faturadas'))

    creditos_db.marcar_nota_fiscal_emitida(pagamento_id, resultado['numero'], resultado['url'])
    flash(f'Nota fiscal {resultado["numero"]} emitida com sucesso.', 'ok')
    return redirect(url_for('admin.relatorios', tipo='nao_faturadas'))


@admin_bp.route('/consultorios', methods=['GET','POST'])
@_admin
def consultorios():
    erro = None
    if request.method == 'POST':
        nome = request.form.get('nome','').strip()
        descricao = request.form.get('descricao','').strip()
        if not nome:
            erro = 'Informe o nome do consultório.'
        else:
            # "Preço base" (preco_periodo) não é mais pedido no cadastro --
            # pedido do Paulo em 10/09/2026: consultório não tem preço
            # próprio, a reserva é sempre cobrada em HORAS, no preço
            # único da hora avulsa (ver creditos_service.preco_hora_avulsa,
            # vem de pacotes_horas_avulsas -- é o mesmo pra qualquer
            # consultório). A coluna continua existindo no banco só por
            # compatibilidade (nada mais lê ela), então passa 0.
            #
            # "Andar" também não é mais digitado aqui -- pedido do Paulo
            # em 10/09/2026: o andar já é o começo do número da sala (ex:
            # "402" -> andar 4, "1101" -> andar 11), então criar_consultorio
            # calcula sozinho (ver db.andar_a_partir_do_nome).
            db.criar_consultorio(nome, descricao, 0)
            flash('Consultório criado.', 'ok')
            return redirect(url_for('admin.consultorios'))
    lista = db.ordenar_consultorios(db.get_client().table('consultorios').select('*').order('nome').execute().data)
    return render_template('admin_consultorios.html', consultorios=lista, erro=erro)


@admin_bp.route('/consultorios/<consultorio_id>/editar', methods=['POST'])
@_admin
def editar_consultorio(consultorio_id):
    # "Preço base" (preco_periodo) não faz mais parte desse formulário
    # (ver comentário no POST de /consultorios acima) -- não mexe nesse
    # campo aqui, só no que a tela realmente edita.
    nome = request.form.get('nome','').strip()
    dados = {
        'nome': nome,
        'descricao': request.form.get('descricao','').strip(),
        # Andar recalculado a partir do nome a cada edição -- não é mais
        # um campo do formulário (pedido do Paulo em 10/09/2026): se o
        # admin renomear a sala, o andar acompanha automaticamente.
        'andar': db.andar_a_partir_do_nome(nome),
        'ativo': request.form.get('ativo') == 'on',
    }
    db.get_client().table('consultorios').update(dados).eq('id', consultorio_id).execute()
    flash('Consultório atualizado.', 'ok')
    return redirect(url_for('admin.consultorios'))


@admin_bp.route('/consultorios/<consultorio_id>/excluir', methods=['POST'])
@_admin
def excluir_consultorio(consultorio_id):
    resultado = db.excluir_consultorio(consultorio_id)
    flash('Consultório excluído.' if resultado == 'apagado' else 'Consultório desativado para preservar o histórico.', 'ok')
    return redirect(url_for('admin.consultorios'))


@admin_bp.route('/consultorios/<consultorio_id>/fotos', methods=['GET','POST'])
@_admin
def fotos_consultorio(consultorio_id):
    consultorio = db.get_consultorio_by_id(consultorio_id)
    if not consultorio:
        flash('Consultório não encontrado.', 'erro')
        return redirect(url_for('admin.consultorios'))
    if request.method == 'POST':
        # getlist (não .get) -- o campo "foto" no formulário aceita
        # selecionar VÁRIOS arquivos de uma vez (input multiple, ver
        # admin_fotos.html) desde 10/09/2026, pedido do Paulo: antes só
        # dava pra mandar 1 foto por envio, obrigando a repetir o
        # formulário uma vez pra cada foto do consultório.
        arquivos = [a for a in request.files.getlist('foto') if a and a.filename]
        if not arquivos:
            flash('Selecione ao menos uma foto.', 'erro')
        else:
            urls_ok = []
            erros = []
            for arquivo in arquivos:
                ext = arquivo.filename.rsplit('.',1)[-1].lower() if '.' in arquivo.filename else 'jpg'
                if ext not in {'jpg','jpeg','png','webp'}:
                    erros.append(f'{arquivo.filename}: use JPG, PNG ou WEBP.')
                    continue
                # Prefixo "consultorios/" dentro do bucket compartilhado
                # (lifemax-reserva-horas) -- o Neon Object Storage usa um
                # bucket só, então separamos por pasta/prefixo em vez de
                # um bucket por finalidade como era no Supabase.
                caminho = f"consultorios/{consultorio_id}/{date.today().isoformat()}-{arquivo.filename.rsplit('/',1)[-1]}"
                try:
                    data = arquivo.read()
                    url = neon_storage.upload_arquivo(caminho, data, arquivo.mimetype or 'image/jpeg')
                    urls_ok.append(url)
                except Exception as e:
                    erros.append(f'{arquivo.filename}: {e}')
            if urls_ok:
                # Um update só com TODAS as fotos novas de uma vez (em vez
                # de um update por foto) -- evita qualquer race condition
                # se o navegador mandasse envios paralelos, e é mais rápido.
                db.adicionar_fotos_consultorio(consultorio_id, urls_ok)
                flash(f'{len(urls_ok)} foto(s) adicionada(s).' if len(urls_ok) > 1 else 'Foto adicionada.', 'ok')
            for msg in erros:
                flash(f'Não foi possível enviar {msg}', 'erro')
        return redirect(url_for('admin.fotos_consultorio', consultorio_id=consultorio_id))
    consultorio = db.get_consultorio_by_id(consultorio_id)
    return render_template('admin_fotos.html', consultorio=consultorio)


@admin_bp.route('/consultorios/<consultorio_id>/fotos/excluir', methods=['POST'])
@_admin
def excluir_foto(consultorio_id):
    url = request.form.get('url','')
    if url:
        db.remover_foto_consultorio(consultorio_id, url)
    return redirect(url_for('admin.fotos_consultorio', consultorio_id=consultorio_id))


@admin_bp.route('/matriz')
@_admin_total
def matriz():
    # Pedido do Paulo em 21/09/2026: deixou de ser uma grade por semana
    # (setas "<" ">") e virou um padrão semanal único, sem data -- a tela
    # busca tudo via /admin/api/matriz/template (ver api_matriz_template
    # abaixo), então não precisa montar nada aqui.
    return render_template('admin_matriz.html')


@admin_bp.route('/matriz/visualizar-agenda')
@_admin
def matriz_visualizar_agenda():
    """Botão "Visualizar agenda" na tela da Matriz -- pedido do Paulo em
    24/09/2026 (item 2), no lugar do antigo botão "Relatório": mostra a
    agenda completa (somente leitura) com TODOS os dias que já têm matriz
    replicada de verdade (matriz_reservas_admin), com rolagem horizontal
    E vertical, sem setas de avançar/voltar -- ver
    admin_matriz_visualizar_agenda.html."""
    return render_template('admin_matriz_visualizar_agenda.html')


@admin_bp.route('/api/matriz/grade', methods=['GET'])
@_admin
def api_matriz_grade():
    """Grade completa (todos os consultórios, todos os horários da semana,
    com o nome do médico em cada reserva) -- usada pela tela "Visualizar
    agenda" da Matriz. Morava em /api/agenda-horistas/grade (pedido do
    Paulo em 14/09/2026) até a tela "Agenda Horistas" ser removida do
    sistema em 30/09/2026 (todos os médicos viraram "avulso"); essa rota
    continuou porque "Visualizar agenda" ainda depende dela."""
    data_inicio_str = request.args.get('data_inicio', date.today().isoformat())
    dias = int(request.args.get('dias', 7))

    data_inicio = date.fromisoformat(data_inicio_str)
    data_fim = data_inicio + timedelta(days=dias - 1)

    # grade_de_turnos já retorna o nome de cada médico (join com
    # medicos(nome)) -- diferente da rota do médico em /api/turnos/grade,
    # aqui NÃO precisamos ocultar nomes: é a visão do administrador.
    grade = db.grade_de_turnos(data_inicio.isoformat(), data_fim.isoformat())
    grade['data_inicio'] = data_inicio.isoformat()
    grade['data_fim'] = data_fim.isoformat()
    grade['dias'] = dias
    # A tela do admin não usa as fotos dos consultórios (listas de URLs
    # que engordavam a resposta à toa) -- 21/10/2026, velocidade.
    for c in grade.get('consultorios', []):
        c.pop('fotos', None)
    grade['bloqueios_template'] = template_service.listar_bloqueios()
    inicio = data_inicio.isoformat(); fim = data_fim.isoformat()
    client = db.get_client()
    grade['reservas_admin'] = (client.table('matriz_reservas_admin')
        .select('id,consultorio_id,data,horario,descricao,criado_por')
        .gte('data', inicio).lte('data', fim).execute().data)
    grade['dias_ocultos'] = template_service.listar_dias_ocultos(inicio, fim)
    # Nomes pra sugestão ao dar nome a um horário (botão direito) -- só
    # nome, texto livre continua permitido.
    grade['medicos_nomes'] = sorted({m['nome'] for m in db.listar_medicos_ativos() if m.get('nome')})
    return grade


def _data_str(v):
    """'data'/'horario' voltam como datetime.date/time (RealDictCursor do
    psycopg2, ver pg_query.py) -- não são strings, então normaliza antes
    de comparar/montar chave."""
    return v.isoformat() if hasattr(v, "isoformat") else str(v)[:10]


def _hora_str(v):
    return v.strftime("%H:%M") if hasattr(v, "strftime") else str(v)[:5]


def _dia_semana(d: date) -> int:
    """0=domingo...6=sábado -- mesma convenção de template_service.dia_semana_de."""
    return (d.weekday() + 1) % 7


@admin_bp.route('/api/matriz/template', methods=['GET'])
@_admin_total
def api_matriz_template():
    """Pedido do Paulo em 21/09/2026: a Matriz deixou de ser editada
    semana a semana (setas "<" ">") e passou a ser um ÚNICO padrão
    semanal (sem data), igual à Semana Padrão -- só que aqui marca
    "reservado" em vez de "bloqueado". Esse padrão depois é REPLICADO em
    cima de datas reais pelos botões "Replicar por período"/"por mês"."""
    client = db.get_client()
    consultorios = db.ordenar_consultorios(client.table('consultorios').select('id,nome,andar').execute().data)
    template = client.table('matriz_template').select('consultorio_id,dia_semana,horario').execute().data
    # Mesmos bloqueios da Semana Padrão (inclui a regra fixa de fim de
    # semana) -- pra Matriz não deixar marcar como "reservado" um
    # horário que já está bloqueado pra reserva em qualquer consultório.
    bloqueios = template_service.listar_bloqueios()
    return {'consultorios': consultorios, 'template': template, 'bloqueios': bloqueios}


@admin_bp.route('/api/matriz/template/toggle', methods=['POST'])
@_admin_total
def api_matriz_template_toggle():
    body = request.get_json(force=True)
    consultorio_id = body.get('consultorio_id')
    dia_semana = body.get('dia_semana')
    horario = body.get('horario')
    if consultorio_id is None or dia_semana is None or not horario:
        return {'erro': 'consultorio_id, dia_semana e horario são obrigatórios'}, 400
    client = db.get_client()
    # Uma ida ao banco no caso de "liberar" (DELETE ... RETURNING) e duas
    # só no de "marcar" -- antes eram sempre duas (SELECT + DELETE/INSERT).
    removidos = (client.table('matriz_template').delete()
                 .eq('consultorio_id', consultorio_id).eq('dia_semana', dia_semana).eq('horario', horario)
                 .execute().data)
    if removidos:
        return {'status': 'removido'}
    client.table('matriz_template').insert(
        {'consultorio_id': consultorio_id, 'dia_semana': dia_semana, 'horario': horario}
    ).execute()
    return {'status': 'adicionado'}


def _aplicar_template_no_periodo(data_inicio: date, data_fim: date, tipo: str, confirmar: bool):
    """Lógica comum aos botões "Replicar matriz por período" e "Replicar
    matriz por mês".

    Reescrita em 24/09/2026 (pedido do Paulo): a matriz nova precisa
    SOBREPOR a antiga no período escolhido, nos dois sentidos --
      1) todo horário que o padrão semanal ATUAL marca fica reservado
         nesse período (cria o que falta);
      2) todo horário que tinha sido marcado por uma replicação
         ANTERIOR mas não faz mais parte do padrão atual é LIBERADO
         (removido de matriz_reservas_admin) -- antes isso nunca
         acontecia (só inserção, nunca remoção), então tirar um horário
         do padrão semanal e replicar de novo não tinha efeito nenhum
         nas datas já aplicadas.
    As reservas de VERDADE de médico (tabela `reservas`) NUNCA são
    tocadas sem confirmação explícita: se uma célula que o padrão atual
    quer reservar já tem uma reserva de médico em cima, a função para e
    devolve `precisa_confirmar` com a lista de conflitos (sala/dia/
    horário/médico) pra tela mostrar em vermelho e pedir "Confirmar
    sobreposição" -- só quando `confirmar=True` (o admin já viu e
    confirmou) é que a reserva do médico é CANCELADA de verdade (mesma
    regra de reembolso/aviso de sempre, ver reserva_service.
    cancelar_reserva_admin) antes de aplicar o bloqueio administrativo
    por cima dela. Liberar um horário (passo 2 acima) nunca gera
    conflito -- só cria/mantém um bloqueio administrativo pode colidir
    com uma reserva de médico."""
    client = db.get_client()
    template = client.table('matriz_template').select('*').execute().data
    if not template:
        return {'erro': 'A matriz ainda não tem nenhum horário marcado no padrão semanal. '
                         'Marque os horários na tela antes de replicar.'}, 400

    consultorios_nome = {c['id']: c['nome'] for c in client.table('consultorios').select('id,nome').execute().data}

    # Todas as células-alvo (consultorio, data, horario) que o padrão
    # ATUAL gera dentro do período pedido -- set, não lista: cada célula
    # entra uma vez só, e dá pra comparar direto com o que já existe.
    alvo = set()
    d = data_inicio
    while d <= data_fim:
        dw = _dia_semana(d)
        for t in template:
            if t['dia_semana'] == dw:
                alvo.add((t['consultorio_id'], d.isoformat(), t['horario']))
        d += timedelta(days=1)

    if not alvo:
        return {'erro': 'Nenhum dia do período escolhido cai nos dias da semana marcados na matriz.'}, 400

    # Reservas de VERDADE (médico) dentro do período -- essas geram
    # conflito e precisam de confirmação; guarda o id da reserva também,
    # pra poder cancelá-la de verdade se o admin confirmar a sobreposição.
    reservas_reais = (
        # medico_id PRECISA estar na lista (mesmo sem ser usado direto
        # aqui) -- é a FK que o embed "medicos(nome)" usa pra buscar o
        # nome; sem ela no select, o embutido não acha o médico e o nome
        # vem sempre vazio (bug encontrado e corrigido em 24/09/2026,
        # pedido do Paulo: a mensagem de sobreposição mostrava só a
        # palavra genérica "Médico" em vez do nome de verdade -- ver
        # pg_query.py._attach_embeds, que resolve o embed a partir da
        # coluna FK já selecionada na linha, não busca ela de novo).
        client.table('reservas').select('id,consultorio_id,data,hora_inicio,medico_id,medicos(nome)')
        .gte('data', data_inicio.isoformat()).lte('data', data_fim.isoformat())
        .neq('status', 'cancelada').execute().data
    )
    reserva_por_chave = {}
    for r in reservas_reais:
        if not r.get('hora_inicio'):
            continue
        chave = (r['consultorio_id'], _data_str(r['data']), _hora_str(r['hora_inicio']))
        reserva_por_chave[chave] = r

    conflitos = [
        {
            'reserva_id': reserva_por_chave[(c, dt, h)]['id'],
            'consultorio_nome': consultorios_nome.get(c, '—'),
            'data': dt, 'horario': h,
            'medico_nome': (reserva_por_chave[(c, dt, h)].get('medicos') or {}).get('nome') or 'Médico',
        }
        for (c, dt, h) in alvo if (c, dt, h) in reserva_por_chave
    ]

    if conflitos and not confirmar:
        return {'precisa_confirmar': True, 'conflitos': conflitos, 'total_alvo': len(alvo)}

    # O admin já confirmou (ou não havia conflito nenhum): cancela de
    # verdade a reserva de cada médico em conflito -- mesma regra de
    # reembolso (12h) e mesmo e-mail de aviso que qualquer outro
    # cancelamento feito pelo admin -- antes de aplicar o bloqueio da
    # matriz por cima daquela célula.
    canceladas = 0
    for cf in conflitos:
        try:
            reserva_service.cancelar_reserva_admin(cf['reserva_id'])
            canceladas += 1
        except ValueError:
            pass  # já cancelada nesse meio-tempo -- segue aplicando o resto

    # Estado atual da Matriz nesse período.
    existentes_rows = (
        client.table('matriz_reservas_admin').select('id,consultorio_id,data,horario,descricao,criado_por')
        .gte('data', data_inicio.isoformat()).lte('data', data_fim.isoformat()).execute().data
    )
    existentes = {
        (h['consultorio_id'], _data_str(h['data']), _hora_str(h['horario'])): h
        for h in existentes_rows
    }

    # Libera (remove) o que uma replicação anterior tinha marcado e que
    # não faz mais parte do padrão semanal atual -- é a "sobreposição"
    # no sentido de liberar horários, pedido do Paulo em 24/09/2026.
    # 21/10/2026: só mexe no que a PRÓPRIA matriz criou (criado_por='admin');
    # bloqueio feito/nomeado à mão em Visualizar agenda ('admin-manual')
    # nunca é liberado por uma replicação.
    a_remover = [h for chave, h in existentes.items()
                 if chave not in alvo and (h.get('criado_por') or 'admin') == 'admin']

    # Cria o que o padrão atual quer reservar e ainda não existe (as
    # células em conflito já foram liberadas acima ao cancelar a reserva
    # do médico, então entram aqui normalmente).
    novos = [
        {'consultorio_id': c, 'data': dt, 'horario': h, 'descricao': '', 'criado_por': 'admin'}
        for (c, dt, h) in alvo if (c, dt, h) not in existentes
    ]

    # Registro da replicação ANTES de mexer nos bloqueios, com o detalhe
    # item a item (matriz_replicacao_itens) -- é o que permite "Desfazer a
    # matriz" depois (pedido do Paulo em 21/10/2026).
    base_registro = {'tipo': tipo, 'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat(),
                     'aplicados': len(novos), 'conflitos': len(conflitos)}
    try:
        replicacao = client.table('matriz_replicacoes').insert({
            **base_registro, 'liberados': len(a_remover),
            'canceladas_medico': canceladas, 'com_registro': True,
        }).execute().data[0]
    except Exception as e:
        # Migração sql/migration_matriz_desfazer_e_ocultar_dias.sql ainda não
        # rodada: replica do jeito antigo (sem poder desfazer) em vez de quebrar.
        print(f'[matriz] colunas novas ausentes em matriz_replicacoes ({e}); registrando no formato antigo.')
        replicacao = client.table('matriz_replicacoes').insert(base_registro).execute().data[0]
        itens_ok = False
    else:
        itens_ok = True

    itens = (
        [{'replicacao_id': replicacao['id'], 'acao': 'liberou', 'consultorio_id': h['consultorio_id'],
          'data': _data_str(h['data']), 'horario': _hora_str(h['horario']), 'descricao': h.get('descricao') or ''}
         for h in a_remover]
        + [{'replicacao_id': replicacao['id'], 'acao': 'criou', 'consultorio_id': n['consultorio_id'],
            'data': n['data'], 'horario': n['horario'], 'descricao': ''} for n in novos]
    )
    if itens and itens_ok:
        try:
            client.table('matriz_replicacao_itens').insert(itens).execute()
        except Exception as e:
            print(f'[matriz] não consegui gravar o detalhe da replicação ({e}); não poderá ser desfeita.')
            try:
                client.table('matriz_replicacoes').update({'com_registro': False}).eq('id', replicacao['id']).execute()
            except Exception:
                pass

    # Operações em LOTE (uma ida ao banco cada) -- antes o "liberar" apagava
    # um por um, o que deixava a replicação lenta.
    if a_remover:
        client.table('matriz_reservas_admin').delete().in_('id', [h['id'] for h in a_remover]).execute()
    if novos:
        client.table('matriz_reservas_admin').insert(novos).execute()

    return {'aplicados': len(novos), 'liberados': len(a_remover), 'conflitos': len(conflitos),
            'canceladas_medico': canceladas,
            'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat()}


@admin_bp.route('/api/matriz/replicar-periodo', methods=['POST'])
@_admin_total
def api_matriz_replicar_periodo():
    """Botão "Replicar matriz por período" -- pedido do Paulo em
    21/09/2026: admin escolhe data de início e fim, o sistema aplica o
    padrão semanal da matriz em cima de todas as datas do período
    (respeitando o dia da semana de cada horário marcado)."""
    body = request.get_json(force=True)
    try:
        data_inicio = date.fromisoformat(body.get('data_inicio', ''))
        data_fim = date.fromisoformat(body.get('data_fim', ''))
    except ValueError:
        return {'erro': 'Datas inválidas.'}, 400
    if data_fim < data_inicio:
        return {'erro': 'A data final não pode ser antes da data inicial.'}, 400
    resultado = _aplicar_template_no_periodo(data_inicio, data_fim, 'periodo', bool(body.get('confirmar')))
    return resultado


@admin_bp.route('/api/matriz/replicar-mes', methods=['POST'])
@_admin_total
def api_matriz_replicar_mes():
    """Botão "Replicar matriz por mês" -- pedido do Paulo em 21/09/2026:
    admin escolhe um mês/ano, o sistema aplica o padrão semanal da
    matriz em todas as datas daquele mês."""
    import calendar
    body = request.get_json(force=True)
    try:
        mes = int(body.get('mes'))
        ano = int(body.get('ano'))
    except (TypeError, ValueError):
        return {'erro': 'Mês/ano inválidos.'}, 400
    if not (1 <= mes <= 12):
        return {'erro': 'Mês inválido.'}, 400
    data_inicio = date(ano, mes, 1)
    data_fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    resultado = _aplicar_template_no_periodo(data_inicio, data_fim, 'mes', bool(body.get('confirmar')))
    return resultado


@admin_bp.route('/api/matriz/relatorio', methods=['GET'])
@_admin_total
def api_matriz_relatorio():
    """Botão "Relatório" -- histórico de todas as vezes que a matriz foi
    replicada, mais recente primeiro."""
    resp = (db.get_client().table('matriz_replicacoes').select('*')
            .order('criado_em', desc=True).limit(200).execute())
    return {'replicacoes': resp.data}


DIAS_PASSADOS_VISUALIZAR_AGENDA = 5


@admin_bp.route('/api/matriz/intervalo-criado', methods=['GET'])
@_admin
def api_matriz_intervalo_criado():
    """Usado pela tela "Visualizar agenda" (item 2, pedido do Paulo em
    24/09/2026; janela de dias passados ajustada em 24/09/2026, item 1):
    descobre o intervalo de datas a mostrar -- só os últimos
    DIAS_PASSADOS_VISUALIZAR_AGENDA dias passados, mais hoje, mais todo o
    futuro que já tem matriz replicada de verdade (matriz_reservas_admin
    -- é o que "Replicar matriz por período/mês" cria).

    Também é AQUI que a limpeza automática acontece: bloqueio
    administrativo (matriz_reservas_admin) com mais de
    DIAS_PASSADOS_VISUALIZAR_AGENDA dias de passado é apagado do banco
    direto, sem arquivar em lugar nenhum -- pedido explícito do Paulo.
    Isso NUNCA toca a reserva de verdade do médico (tabela `reservas`)
    nem o extrato financeiro (`creditos_transacoes`): essas continuam
    intactas e aparecem normalmente em Relatórios/Histórico, que não
    dependem de matriz_reservas_admin pra nada -- só o registro de "esse
    horário foi bloqueado pela matriz" é descartado, porque essa tela é
    a única que usa esse dado, e ele deixou de fazer sentido reter pra
    trás de 5 dias."""
    cliente = db.get_client()
    hoje = date.today()
    limite_antigo = (hoje - timedelta(days=DIAS_PASSADOS_VISUALIZAR_AGENDA)).isoformat()
    cliente.table('matriz_reservas_admin').delete().lt('data', limite_antigo).execute()
    try:
        cliente.table('matriz_replicacao_itens').delete().lt('data', limite_antigo).execute()
    except Exception as e:  # migração ainda não rodada: tabela não existe
        print(f'[matriz] matriz_replicacao_itens indisponível: {e}')

    ultima = cliente.table('matriz_reservas_admin').select('data').order('data', desc=True).limit(1).execute().data
    if not ultima:
        return {'data_inicio': None, 'data_fim': None, 'dias': 0}
    data_fim = date.fromisoformat(ultima[0]['data'])
    data_inicio = hoje - timedelta(days=DIAS_PASSADOS_VISUALIZAR_AGENDA)
    if data_fim < data_inicio:
        return {'data_inicio': None, 'data_fim': None, 'dias': 0}
    dias = (data_fim - data_inicio).days + 1
    return {'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat(), 'dias': dias,
            'hoje': hoje.isoformat()}


# =====================================================================
# Matriz v2 (pedido do Paulo em 21/10/2026)
#   - Matrizes geradas / Desfazer a matriz
#   - Visualizar agenda: bloquear/desbloquear célula, nome do médico na
#     célula (botão direito) e ocultar/exibir um dia para os médicos
# =====================================================================

_FUSO_BRASILIA = timezone(timedelta(hours=-3))


def _data_hora_br(v):
    """criado_em/desfeita_em -> 'dd/mm/aaaa hh:mm' no horário de Brasília."""
    if not v:
        return ''
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            return v
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(_FUSO_BRASILIA).strftime('%d/%m/%Y %H:%M')


def _data_br(v):
    s = _data_str(v)
    return f'{s[8:10]}/{s[5:7]}/{s[0:4]}'


@admin_bp.route('/api/matriz/replicacoes', methods=['GET'])
@_admin_total
def api_matriz_replicacoes():
    """Botão "Matrizes geradas": as 5 últimas replicações (mais recente
    primeiro), com data/hora de geração em horário de Brasília."""
    linhas = (db.get_client().table('matriz_replicacoes').select('*')
              .order('criado_em', desc=True).limit(5).execute().data)
    saida = []
    for r in linhas:
        desfeita = bool(r.get('desfeita_em'))
        com_registro = bool(r.get('com_registro'))
        saida.append({
            'id': r['id'],
            'gerada_em': _data_hora_br(r.get('criado_em')),
            'tipo': r.get('tipo'),
            'periodo': f"{_data_br(r['data_inicio'])} a {_data_br(r['data_fim'])}",
            'aplicados': r.get('aplicados') or 0,
            'liberados': r.get('liberados') or 0,
            'canceladas_medico': r.get('canceladas_medico') or 0,
            'desfeita': desfeita,
            'desfeita_em': _data_hora_br(r.get('desfeita_em')) if desfeita else '',
            'pode_desfazer': com_registro and not desfeita,
            'motivo_sem_desfazer': ('Já foi desfeita.' if desfeita else
                                    'Gerada antes desta função existir: não há registro do que ela mudou.'
                                    if not com_registro else ''),
        })
    return {'replicacoes': saida}


@admin_bp.route('/api/matriz/replicacoes/<replicacao_id>/desfazer', methods=['POST'])
@_admin_total
def api_matriz_desfazer_replicacao(replicacao_id):
    """"Desfazer a matriz": devolve matriz_reservas_admin ao estado de ANTES
    daquela replicação -- apaga o que ela criou e recria o que ela liberou.
    Não mexe em bloqueios feitos/nomeados à mão (criado_por='admin-manual')
    nem em reservas de médicos (as que a replicação cancelou NÃO voltam:
    o médico já foi avisado e reembolsado conforme a regra das 12h)."""
    client = db.get_client()
    achadas = client.table('matriz_replicacoes').select('*').eq('id', replicacao_id).limit(1).execute().data
    if not achadas:
        return {'erro': 'Matriz gerada não encontrada.'}, 404
    rep = achadas[0]
    if rep.get('desfeita_em'):
        return {'erro': 'Essa matriz já foi desfeita.'}, 400
    if not rep.get('com_registro'):
        return {'erro': 'Essa matriz foi gerada antes desta função existir; não há registro do que ela mudou, '
                        'então não dá pra desfazer com segurança.'}, 400

    itens = client.table('matriz_replicacao_itens').select('*').eq('replicacao_id', replicacao_id).execute().data
    criados = [i for i in itens if i['acao'] == 'criou']
    liberados = [i for i in itens if i['acao'] == 'liberou']

    # 1) apaga o que a replicação criou (só se continua "da matriz", ou seja,
    #    sem ter sido nomeado/editado à mão depois)
    removidos = 0
    if criados:
        chaves = {(i['consultorio_id'], _data_str(i['data']), _hora_str(i['horario'])) for i in criados}
        datas = sorted({k[1] for k in chaves})
        atuais = (client.table('matriz_reservas_admin').select('id,consultorio_id,data,horario,criado_por')
                  .gte('data', datas[0]).lte('data', datas[-1]).execute().data)
        ids = [a['id'] for a in atuais
               if (a['consultorio_id'], _data_str(a['data']), _hora_str(a['horario'])) in chaves
               and (a.get('criado_por') or 'admin') == 'admin']
        if ids:
            client.table('matriz_reservas_admin').delete().in_('id', ids).execute()
        removidos = len(ids)

    # 2) recria o que a replicação liberou (se a célula já não estiver ocupada)
    recriados = 0
    if liberados:
        datas = sorted({_data_str(i['data']) for i in liberados})
        atuais = (client.table('matriz_reservas_admin').select('consultorio_id,data,horario')
                  .gte('data', datas[0]).lte('data', datas[-1]).execute().data)
        ocupadas = {(a['consultorio_id'], _data_str(a['data']), _hora_str(a['horario'])) for a in atuais}
        a_criar = [
            {'consultorio_id': i['consultorio_id'], 'data': _data_str(i['data']), 'horario': _hora_str(i['horario']),
             'descricao': i.get('descricao') or '', 'criado_por': 'admin'}
            for i in liberados
            if (i['consultorio_id'], _data_str(i['data']), _hora_str(i['horario'])) not in ocupadas
        ]
        if a_criar:
            client.table('matriz_reservas_admin').insert(a_criar).execute()
        recriados = len(a_criar)

    client.table('matriz_replicacoes').update(
        {'desfeita_em': db.agora_iso()}
    ).eq('id', replicacao_id).execute()
    return {'desfeita': True, 'removidos': removidos, 'recriados': recriados,
            'canceladas_medico_nao_restauradas': rep.get('canceladas_medico') or 0}


# ---------- Visualizar agenda: células ----------

def _horarios_cobertos_pela_reserva(r: dict) -> list[str]:
    if r.get('tipo_reserva') == 'hora' and r.get('hora_inicio'):
        return template_service.horas_da_reserva_por_hora(_hora_str(r['hora_inicio']), r.get('quantidade_horas') or 1)
    return template_service.HORARIOS_POR_PERIODO.get(r.get('periodo'), [])


def _validar_celula(body):
    """Valida consultorio_id/data/horario do corpo; devolve (dados, erro)."""
    consultorio_id = body.get('consultorio_id')
    data_iso = body.get('data')
    horario = (body.get('horario') or '')[:5]
    if not consultorio_id or not data_iso or horario not in template_service.HORARIOS_DO_DIA:
        return None, ({'erro': 'consultorio_id, data e horario (um dos horários da grade) são obrigatórios.'}, 400)
    try:
        date.fromisoformat(data_iso)
    except ValueError:
        return None, ({'erro': 'Data inválida.'}, 400)
    return (consultorio_id, data_iso, horario), None


def _reserva_de_medico_na_celula(client, consultorio_id, data_iso, horario):
    """Nome do médico se há reserva REAL (não cancelada) cobrindo essa célula; senão None."""
    reservas = (client.table('reservas')
                .select('id,consultorio_id,data,tipo_reserva,hora_inicio,quantidade_horas,periodo,medico_id,medicos(nome)')
                .eq('consultorio_id', consultorio_id).eq('data', data_iso).neq('status', 'cancelada').execute().data)
    for r in reservas:
        if horario in _horarios_cobertos_pela_reserva(r):
            return (r.get('medicos') or {}).get('nome') or 'um médico'
    return None


def _celula_indisponivel_semana_padrao(consultorio_id, data_iso, horario):
    return template_service.esta_bloqueado(
        template_service.listar_bloqueios(), consultorio_id, template_service.dia_semana_de(data_iso), horario)


@admin_bp.route('/api/matriz/celula/bloquear', methods=['POST'])
@_admin
def api_matriz_celula_bloquear():
    """Botão "Bloquear/desbloquear horários" (Visualizar agenda): se a célula
    está livre, bloqueia; se já está bloqueada pelo administrador, desbloqueia."""
    dados, erro = _validar_celula(request.get_json(force=True))
    if erro:
        return erro
    consultorio_id, data_iso, horario = dados
    client = db.get_client()

    removidos = (client.table('matriz_reservas_admin').delete()
                 .eq('consultorio_id', consultorio_id).eq('data', data_iso).eq('horario', horario)
                 .execute().data)
    if removidos:
        return {'status': 'liberado'}

    if _celula_indisponivel_semana_padrao(consultorio_id, data_iso, horario):
        return {'erro': 'Esse horário é indisponível pela regra fixa (fim de semana/semana padrão).'}, 400
    medico = _reserva_de_medico_na_celula(client, consultorio_id, data_iso, horario)
    if medico:
        return {'erro': f'Esse horário tem reserva de {medico}. Cancele a reserva antes de bloquear.'}, 409
    client.table('matriz_reservas_admin').insert({
        'consultorio_id': consultorio_id, 'data': data_iso, 'horario': horario,
        'descricao': '', 'criado_por': 'admin-manual',
    }).execute()
    return {'status': 'bloqueado', 'descricao': ''}


@admin_bp.route('/api/matriz/celula/nome', methods=['POST'])
@_admin
def api_matriz_celula_nome():
    """Botão direito numa célula: define (ou apaga) o nome do médico que vai
    usar o horário. Se a célula estava livre, ela passa a ficar bloqueada com
    esse nome. Nome vazio mantém o bloqueio e só apaga o nome."""
    body = request.get_json(force=True)
    dados, erro = _validar_celula(body)
    if erro:
        return erro
    consultorio_id, data_iso, horario = dados
    nome = (body.get('nome') or '').strip()[:80]
    client = db.get_client()

    atualizados = (client.table('matriz_reservas_admin')
                   .update({'descricao': nome, 'criado_por': 'admin-manual'})
                   .eq('consultorio_id', consultorio_id).eq('data', data_iso).eq('horario', horario)
                   .execute().data)
    if atualizados:
        return {'status': 'nome_salvo', 'descricao': nome}

    if _celula_indisponivel_semana_padrao(consultorio_id, data_iso, horario):
        return {'erro': 'Esse horário é indisponível pela regra fixa (fim de semana/semana padrão).'}, 400
    medico = _reserva_de_medico_na_celula(client, consultorio_id, data_iso, horario)
    if medico:
        return {'erro': f'Esse horário já tem reserva de {medico}.'}, 409
    if not nome:
        return {'status': 'sem_alteracao', 'descricao': ''}
    client.table('matriz_reservas_admin').insert({
        'consultorio_id': consultorio_id, 'data': data_iso, 'horario': horario,
        'descricao': nome, 'criado_por': 'admin-manual',
    }).execute()
    return {'status': 'bloqueado_com_nome', 'descricao': nome}


@admin_bp.route('/api/matriz/dia/ocultar', methods=['POST'])
@_admin
def api_matriz_dia_ocultar():
    """Botão "o" verde sobre cada dia: oculta/exibe o dia inteiro para os
    médicos (alterna). Devolve o novo estado."""
    data_iso = (request.get_json(force=True).get('data') or '')[:10]
    try:
        date.fromisoformat(data_iso)
    except ValueError:
        return {'erro': 'Data inválida.'}, 400
    client = db.get_client()
    removidos = client.table('dias_ocultos').delete().eq('data', data_iso).execute().data
    if removidos:
        return {'oculto': False, 'data': data_iso}
    client.table('dias_ocultos').insert({'data': data_iso}).execute()
    return {'oculto': True, 'data': data_iso}


# ---------------- Usuários do admin (22/10/2026) ----------------
_MASTER_MINUTOS = 15


def _master_liberado() -> bool:
    return session.get('admin_master_ate', 0) > datetime.now(timezone.utc).timestamp()


@admin_bp.route('/usuarios', methods=['GET', 'POST'])
@_admin_total
@limiter.limit("6 per minute", methods=["POST"])
def usuarios():
    """Lista de usuários -- só abre depois da senha master."""
    if not _master_liberado():
        erro = None
        if request.method == 'POST':
            from app.config import Config
            senha = request.form.get('master', '')
            if senha and secrets.compare_digest(senha, Config.ADMIN_MASTER_PASSWORD or ''):
                session['admin_master_ate'] = datetime.now(timezone.utc).timestamp() + _MASTER_MINUTOS * 60
                return redirect(url_for('admin.usuarios'))
            erro = 'Senha master incorreta.'
        return render_template('admin_usuarios_master.html', erro=erro)
    return render_template('admin_usuarios.html', usuarios=usuarios_admin.listar(),
                           meu_id=session.get('admin_usuario_id'), tabela_ok=usuarios_admin.tabela_ok())


def _gate_master(titulo):
    """Tela da senha master (mesma de Usuários, vale 15 min). Devolve a
    resposta a exibir enquanto não liberado, ou None se já liberado."""
    if _master_liberado():
        return None
    erro = None
    if request.method == 'POST' and request.form.get('master') is not None:
        from app.config import Config
        senha = request.form.get('master', '')
        if senha and secrets.compare_digest(senha, Config.ADMIN_MASTER_PASSWORD or ''):
            session['admin_master_ate'] = datetime.now(timezone.utc).timestamp() + _MASTER_MINUTOS * 60
            return redirect(request.path)
        erro = 'Senha master incorreta.'
    return render_template('admin_usuarios_master.html', erro=erro, titulo_gate=titulo)


@admin_bp.route('/backup', methods=['GET', 'POST'])
@_admin_total
@limiter.limit("6 per minute", methods=["POST"])
def backup():
    """Painel de Backup (pedido do Paulo em 25/10/2026): baixar um arquivo com
    TODOS os dados e restaurar a partir de um arquivo. Protegido pela senha master."""
    gate = _gate_master('Backup')
    if gate is not None:
        return gate
    return render_template('admin_backup.html')


@admin_bp.route('/backup/baixar', methods=['POST'])
@_admin_total
@limiter.limit("6 per minute")
def backup_baixar():
    from app.services import backup_service
    if not _master_liberado():
        return redirect(url_for('admin.backup'))
    try:
        arquivo, resumo = backup_service.gerar_backup()
    except Exception as e:
        flash(f'Não foi possível gerar o backup: {e}', 'erro')
        return redirect(url_for('admin.backup'))
    from flask import Response
    nome = f"backup_lifemax_{datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d_%H-%M')}.json.gz"
    print(f"[admin] backup gerado por admin_usuario_id={session.get('admin_usuario_id')}: {sum(resumo.values())} linhas em {len(resumo)} tabelas")
    return Response(arquivo, mimetype='application/gzip',
                    headers={'Content-Disposition': f'attachment; filename={nome}'})


@admin_bp.route('/backup/restaurar', methods=['POST'])
@_admin_total
@limiter.limit("3 per minute")
def backup_restaurar():
    from app.services import backup_service
    if not _master_liberado():
        return redirect(url_for('admin.backup'))
    if (request.form.get('confirmacao') or '').strip().upper() != 'RESTAURAR':
        flash('Para restaurar, digite RESTAURAR no campo de confirmação.', 'erro')
        return redirect(url_for('admin.backup'))
    arq = request.files.get('arquivo')
    if not arq or not arq.filename:
        flash('Escolha o arquivo de backup.', 'erro')
        return redirect(url_for('admin.backup'))
    try:
        pacote = backup_service.ler_arquivo(arq.read())
        gravadas = backup_service.restaurar_backup(pacote)
        print(f"[admin] backup RESTAURADO por admin_usuario_id={session.get('admin_usuario_id')}: {sum(gravadas.values())} linhas")
        flash(f"Backup restaurado: {sum(gravadas.values())} registros em {len([t for t, n in gravadas.items() if n])} tabelas "
              f"(arquivo gerado em {str(pacote.get('gerado_em', ''))[:16].replace('T', ' ')} UTC).", 'ok')
    except ValueError as e:
        flash(str(e), 'erro')
    return redirect(url_for('admin.backup'))


@admin_bp.route('/valores', methods=['GET', 'POST'])
@_admin_total
def valores():
    """"Alterar valores" (pedido do Paulo em 25/10/2026): o admin edita o
    valor/hora de cada opção do quadro "Opções para contratação" do painel
    do médico (tabela pacotes_horas_avulsas) e publica."""
    pacotes = creditos_db.listar_pacotes_horas()
    digitados = {}
    if request.method == 'POST':
        novos = {}
        for p in pacotes:
            bruto = (request.form.get(f"valor_{p['horas']}") or '').strip().replace('R$', '').replace(' ', '')
            if ',' in bruto:
                bruto = bruto.replace('.', '').replace(',', '.')
            try:
                novos[int(p['horas'])] = float(bruto)
            except ValueError:
                novos[int(p['horas'])] = None
            digitados[int(p['horas'])] = request.form.get(f"valor_{p['horas']}") or ''
        validos, erro = creditos_db.validar_novos_valores_pacotes(pacotes, novos)
        if erro:
            flash(erro, 'erro')
        else:
            creditos_db.atualizar_valores_pacotes(validos)
            print(f"[admin] valores dos pacotes alterados por admin_usuario_id={session.get('admin_usuario_id')}: {validos}")
            flash('Novos valores publicados! Já aparecem no painel dos médicos.', 'ok')
            return redirect(url_for('admin.valores'))
    return render_template('admin_valores.html', pacotes=pacotes, digitados=digitados)


@admin_bp.route('/usuarios/novo', methods=['POST'])
@_admin_total
def usuarios_novo():
    if not _master_liberado():
        return redirect(url_for('admin.usuarios'))
    try:
        u = usuarios_admin.criar(request.form.get('nome'), request.form.get('email'), request.form.get('telefone'),
                                 request.form.get('perfil') or 'admin')
        r = usuarios_admin.enviar_link(u['id'])
        flash(f"Usuário cadastrado. " + (f"Link de acesso enviado para {r['email']}." if r['enviado']
              else f"Não foi possível enviar o e-mail (SMTP não configurado). Link para copiar: {r['link']}"), 'ok')
    except ValueError as e:
        flash(str(e), 'erro')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/usuarios/<usuario_id>/link', methods=['POST'])
@_admin_total
def usuarios_link(usuario_id):
    if not _master_liberado():
        return redirect(url_for('admin.usuarios'))
    try:
        r = usuarios_admin.enviar_link(usuario_id)
        flash((f"Link de acesso enviado para {r['email']}." if r['enviado']
               else f"Não foi possível enviar o e-mail (SMTP não configurado). Link para copiar: {r['link']}"), 'ok')
    except ValueError as e:
        flash(str(e), 'erro')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/usuarios/<usuario_id>/ativo', methods=['POST'])
@_admin_total
def usuarios_ativo(usuario_id):
    if not _master_liberado():
        return redirect(url_for('admin.usuarios'))
    if usuario_id == session.get('admin_usuario_id'):
        flash('Você não pode bloquear o próprio usuário.', 'erro')
    else:
        u = usuarios_admin.buscar_por_id(usuario_id)
        if u:
            usuarios_admin.definir_ativo(usuario_id, not u.get('ativo'))
            flash(f"Usuário {'ativado' if not u.get('ativo') else 'bloqueado'}.", 'ok')
    return redirect(url_for('admin.usuarios'))


@admin_bp.route('/definir-senha', methods=['GET', 'POST'])
@limiter.limit("8 per minute", methods=["POST"])
def definir_senha():
    token = request.args.get('token', '') or request.form.get('token', '')
    erro, sucesso = None, False
    reg = usuarios_admin.validar_token(token)
    if reg is None:
        erro = 'Esse link é inválido. Peça um novo ao administrador.'
    elif request.method == 'POST':
        senha, conf = request.form.get('senha', ''), request.form.get('confirmar_senha', '')
        if len(senha) < 6:
            erro = 'A senha precisa ter pelo menos 6 caracteres.'
        elif senha != conf:
            erro = 'As senhas não coincidem.'
        elif usuarios_admin.definir_senha(token, senha):
            sucesso = True
        else:
            erro = 'Esse link é inválido.'
    return render_template('admin_definir_senha.html', token=token, erro=erro, sucesso=sucesso, link_valido=reg is not None)
