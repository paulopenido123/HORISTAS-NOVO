from datetime import date, timedelta
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
from app.services import ia_uso_service as ia_uso
from app.extensions import csrf

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def _admin(view):
    return auth_service.requer_admin(view)


@admin_bp.route('/login', methods=['GET','POST'])
def admin_login():
    erro = None
    if request.method == 'POST':
        senha = request.form.get('senha','')
        if senha and auth_service.verificar_senha(senha, session.get('_admin_hash','')):
            auth_service.login_admin()
            return redirect(request.args.get('next') or url_for('admin.dashboard'))
        # Production uses a single ADMIN_PASSWORD from env; avoid storing it in session.
        from app.config import Config
        if senha and Config.ADMIN_PASSWORD and senha == Config.ADMIN_PASSWORD:
            auth_service.login_admin()
            return redirect(request.args.get('next') or url_for('admin.dashboard'))
        erro = 'Senha administrativa incorreta.'
    return render_template('admin_login.html', erro=erro)


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
@_admin
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
    )


@admin_bp.route('/horas/endereco-padrao', methods=['POST'])
@_admin
def atualizar_endereco_padrao():
    """Salva o endereço padrão da Lifemax (usado no e-mail de agendamento
    pro paciente -- ver reserva_service.enviar_email_agendamento_paciente)
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
    # Saldo de horas (carteira "salas") e saldo de IA (em R$) de cada um,
    # pra mostrar na lista.
    #
    # ⚠️ Corrigido em 11/09/2026 (a tela estava demorando muito pra abrir
    # depois da migração dos ~130 médicos horistas do Life Max): antes,
    # esse loop chamava creditos_db.saldo_em_horas_medico(m['id']) e
    # creditos_db.obter_saldo_ia(m['id']) PRA CADA MÉDICO -- e
    # saldo_em_horas_medico, por baixo dos panos, ainda rebuscava a lista
    # de pacotes de hora (listar_pacotes_horas()) do zero a cada chamada.
    # Isso dava 3 consultas SEPARADAS ao banco por médico (~390 no total
    # com 130 médicos) só pra abrir essa tela -- e o "*" do select acima
    # já tinha trazido saldo_creditos/saldo_ia de todo mundo de uma vez!
    # Agora: busca os pacotes de hora UMA única vez (fora do loop) e
    # calcula o saldo em horas/IA direto dos dados que já vieram no
    # select("*"), sem nenhuma consulta extra por médico.
    pacotes_horas = creditos_db.listar_pacotes_horas()
    for m in lista:
        m['saldo_horas'] = creditos_db.estimar_horas_compraveis(m.get('saldo_creditos') or 0, pacotes_horas)
        m['saldo_ia'] = float(m.get('saldo_ia') or 0)
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
        flash(f'Link de acesso enviado para {email} ({medico["nome"]}) -- válido por 48h.', 'ok')
    else:
        # O token já foi criado e o link é válido -- só o envio automático
        # por e-mail falhou (SMTP ainda não configurado). Mostra o link pra
        # o admin poder mandar na mão (WhatsApp, etc.) enquanto isso.
        flash(
            'O envio automático de e-mail ainda não está configurado neste sistema '
            '(SMTP_HOST/SMTP_USER/SMTP_PASSWORD/EMAIL_FROM em .env -- veja .env.example, seção "Email"). '
            f'O link já foi gerado mesmo assim (válido 48h), copie e mande na mão: {resultado["link"]}',
            'erro',
        )
    return redirect(url_for('admin.clientes', busca=request.form.get('busca') or ''))


@admin_bp.route('/clientes/<medico_id>/ajustar-saldo', methods=['POST'])
@_admin
def ajustar_saldo_cliente(medico_id):
    """Credita (valor positivo) ou debita (valor negativo) saldo de um
    médico direto pelo painel admin, numa das duas carteiras -- vira uma
    transação tipo 'ajuste' em creditos_transacoes, igual qualquer outro
    lançamento (fica no histórico do médico, não é uma mudança
    "invisível" direto no banco).

    Pedido do Paulo em 10/09/2026: a carteira de Salas/Horas é sempre
    medida em HORAS (não em dinheiro) em qualquer lugar do sistema, então
    esse ajuste também é feito em horas quando a carteira é 'salas' -- o
    admin digita "15" (horas), e aqui a gente converte pro valor em R$
    equivalente (preço da hora avulsa) só pra manter o mesmo mecanismo
    interno de saldo que o resto do sistema usa. A carteira de IA continua
    em R$ direto, sem conversão (essa carteira é mesmo medida em dinheiro,
    não em horas).

    ⚠️ Em 11/09/2026 o botão "Alterar saldo" saiu da lista de clientes e
    foi pra dentro da tela "Visualizar" de cada cliente (pedido do Paulo)
    -- por isso todo redirect aqui agora volta pra
    admin.visualizar_cliente (não mais admin.clientes)."""
    medico = db.get_medico_by_id(medico_id)
    if not medico:
        flash('Cliente não encontrado.', 'erro')
        return redirect(url_for('admin.clientes'))

    carteira = request.form.get('carteira', 'salas')
    if carteira not in ('salas', 'ia'):
        flash('Carteira inválida.', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    try:
        quantidade = float((request.form.get('quantidade') or '0').replace(',', '.'))
    except ValueError:
        unidade = 'horas' if carteira == 'salas' else 'reais'
        flash(f'Quantidade inválida -- use só números ({unidade}, ex: 15 ou -5).', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    if quantidade == 0:
        flash('Informe uma quantidade diferente de zero (positivo credita, negativo debita).', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    descricao = (request.form.get('descricao') or '').strip() or 'Ajuste manual pelo admin'

    if carteira == 'salas':
        horas = round(quantidade)  # carteira de horas trabalha sempre em números inteiros de hora
        if horas == 0:
            flash('Informe uma quantidade de horas diferente de zero.', 'erro')
            return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))
        valor = round(horas * creditos_db.preco_hora_avulsa(), 2)
        quantidade_horas_param = abs(horas)
    else:
        valor = quantidade
        quantidade_horas_param = None

    try:
        creditos_db.registrar_transacao(
            medico_id, tipo='ajuste', valor=valor, descricao=descricao, carteira=carteira,
            quantidade_horas=quantidade_horas_param,
        )
    except Exception as e:
        flash(f'Não foi possível ajustar o saldo: {e}', 'erro')
        return redirect(url_for('admin.visualizar_cliente', medico_id=medico_id))

    acao = 'creditado' if quantidade > 0 else 'debitado'
    if carteira == 'salas':
        flash(f'Saldo de Salas/Horas de {medico["nome"]} {acao} em {abs(horas)}h.', 'ok')
    else:
        flash(f'Saldo de IA de {medico["nome"]} {acao} em R$ {abs(valor):.2f}.', 'ok')
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
            tipo_vinculo=(request.form.get('tipo_vinculo') or 'avulso').strip(),
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
    medico['saldo_ia'] = creditos_db.obter_saldo_ia(medico_id)
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
            tipo_vinculo=(request.form.get('tipo_vinculo') or '').strip() or None,
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
@_admin
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
    if tipo not in ('agendamentos', 'transacoes', 'nao_faturadas', 'faturadas'):
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
    if tipo == 'transacoes':
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
        operacoes=relatorios_service.OPERACOES_AGENDAMENTOS,
        nfe_configurado=nfe_service.configurado(),
    )


@admin_bp.route('/pagamentos/<pagamento_id>/emitir-nf', methods=['POST'])
@_admin
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
@_admin
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


@admin_bp.route('/agenda-horistas')
@_admin
def agenda_horistas():
    """Agenda Horistas -- pedido do Paulo em 14/09/2026: mesma grade que o
    médico vê em /turnos (todos os consultórios, todos os turnos
    disponíveis da semana), só que aqui, pra quem administra, o nome do
    profissional aparece dentro do próprio campo de horário reservado.
    O médico continua sem ver o nome de outros profissionais em /turnos
    (ver redação em app/routes/turnos.py api_grade) -- só o admin vê
    todos os nomes, porque essa tela é só de leitura (sem reservar/
    cancelar por aqui, isso continua sendo feito pelo próprio médico ou
    pela Matriz de Agendamento)."""
    return render_template('admin_agenda_horistas.html')


@admin_bp.route('/api/agenda-horistas/grade', methods=['GET'])
@_admin
def api_agenda_horistas_grade():
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
    grade['bloqueios_template'] = template_service.listar_bloqueios()
    inicio = data_inicio.isoformat(); fim = data_fim.isoformat()
    grade['reservas_admin'] = (db.get_client().table('matriz_reservas_admin')
        .select('*').gte('data', inicio).lte('data', fim).execute().data)
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
@_admin
def api_matriz_template():
    """Pedido do Paulo em 21/09/2026: a Matriz deixou de ser editada
    semana a semana (setas "<" ">") e passou a ser um ÚNICO padrão
    semanal (sem data), igual à Semana Padrão -- só que aqui marca
    "reservado" em vez de "bloqueado". Esse padrão depois é REPLICADO em
    cima de datas reais pelos botões "Replicar por período"/"por mês"."""
    client = db.get_client()
    consultorios = db.ordenar_consultorios(client.table('consultorios').select('*').execute().data)
    template = client.table('matriz_template').select('*').execute().data
    # Mesmos bloqueios da Semana Padrão (inclui a regra fixa de fim de
    # semana) -- pra Matriz não deixar marcar como "reservado" um
    # horário que já está bloqueado pra reserva em qualquer consultório.
    bloqueios = template_service.listar_bloqueios()
    return {'consultorios': consultorios, 'template': template, 'bloqueios': bloqueios}


@admin_bp.route('/api/matriz/template/toggle', methods=['POST'])
@_admin
def api_matriz_template_toggle():
    body = request.get_json(force=True)
    consultorio_id = body.get('consultorio_id')
    dia_semana = body.get('dia_semana')
    horario = body.get('horario')
    if consultorio_id is None or dia_semana is None or not horario:
        return {'erro': 'consultorio_id, dia_semana e horario são obrigatórios'}, 400
    client = db.get_client()
    existente = (client.table('matriz_template').select('id')
                 .eq('consultorio_id', consultorio_id).eq('dia_semana', dia_semana).eq('horario', horario)
                 .execute().data)
    if existente:
        client.table('matriz_template').delete().eq('id', existente[0]['id']).execute()
        return {'status': 'removido'}
    client.table('matriz_template').insert(
        {'consultorio_id': consultorio_id, 'dia_semana': dia_semana, 'horario': horario}
    ).execute()
    return {'status': 'adicionado'}


def _aplicar_template_no_periodo(data_inicio: date, data_fim: date, tipo: str, confirmar: bool):
    """Lógica comum aos botões "Replicar matriz por período" e "Replicar
    matriz por mês" -- pedido do Paulo em 21/09/2026: pega o padrão
    semanal marcado em matriz_template e cria os registros de verdade
    (matriz_reservas_admin) pra cada data do período que cai no dia da
    semana certo. Se algum desses horários já tiver uma reserva de
    VERDADE de um médico, não aplica de cara -- devolve a lista de
    conflitos pra tela de revisão confirmar (`confirmar=True` reenvia
    depois de o admin já ter visto e confirmado, ciente de que precisa
    avisar os médicos envolvidos)."""
    client = db.get_client()
    template = client.table('matriz_template').select('*').execute().data
    if not template:
        return {'erro': 'A matriz ainda não tem nenhum horário marcado no padrão semanal. '
                         'Marque os horários na tela antes de replicar.'}, 400

    consultorios_nome = {c['id']: c['nome'] for c in client.table('consultorios').select('id,nome').execute().data}

    # Todas as células-alvo (consultorio, data, horario) que o padrão
    # gera dentro do período pedido.
    alvo = []
    d = data_inicio
    while d <= data_fim:
        dw = _dia_semana(d)
        for t in template:
            if t['dia_semana'] == dw:
                alvo.append((t['consultorio_id'], d.isoformat(), t['horario']))
        d += timedelta(days=1)

    if not alvo:
        return {'erro': 'Nenhum dia do período escolhido cai nos dias da semana marcados na matriz.'}, 400

    # Reservas de VERDADE (médico) dentro do período -- essas geram
    # conflito e precisam de confirmação + aviso pra contatar o médico.
    reservas_reais = (
        client.table('reservas').select('consultorio_id,data,hora_inicio,medicos(nome)')
        .gte('data', data_inicio.isoformat()).lte('data', data_fim.isoformat())
        .neq('status', 'cancelada').execute().data
    )
    nome_por_chave = {}
    for r in reservas_reais:
        if not r.get('hora_inicio'):
            continue
        chave = (r['consultorio_id'], _data_str(r['data']), _hora_str(r['hora_inicio']))
        nome_por_chave[chave] = (r.get('medicos') or {}).get('nome') or 'Médico'

    conflitos = [
        {'consultorio_nome': consultorios_nome.get(c, '—'), 'data': dt, 'horario': h, 'medico_nome': nome_por_chave[(c, dt, h)]}
        for (c, dt, h) in alvo if (c, dt, h) in nome_por_chave
    ]

    if conflitos and not confirmar:
        return {'precisa_confirmar': True, 'conflitos': conflitos, 'total_alvo': len(alvo)}

    # Já existentes no período -- pra não tentar inserir duplicado (a
    # unique constraint de matriz_reservas_admin rejeitaria) e pra
    # "prevalecer sempre a última matriz aplicada" sem precisar apagar e
    # recriar tudo -- as que já existem simplesmente continuam.
    existentes = {
        (h['consultorio_id'], _data_str(h['data']), _hora_str(h['horario']))
        for h in client.table('matriz_reservas_admin').select('consultorio_id,data,horario')
        .gte('data', data_inicio.isoformat()).lte('data', data_fim.isoformat()).execute().data
    }

    novos = []
    vistos = set()
    for (c, dt, h) in alvo:
        chave = (c, dt, h)
        if chave in existentes or chave in vistos:
            continue
        vistos.add(chave)
        novos.append({'consultorio_id': c, 'data': dt, 'horario': h, 'descricao': '', 'criado_por': 'admin'})

    if novos:
        client.table('matriz_reservas_admin').insert(novos).execute()

    client.table('matriz_replicacoes').insert({
        'tipo': tipo, 'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat(),
        'aplicados': len(novos), 'conflitos': len(conflitos),
    }).execute()

    return {'aplicados': len(novos), 'conflitos': len(conflitos),
            'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat()}


@admin_bp.route('/api/matriz/replicar-periodo', methods=['POST'])
@_admin
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
@_admin
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
@_admin
def api_matriz_relatorio():
    """Botão "Relatório" -- histórico de todas as vezes que a matriz foi
    replicada, mais recente primeiro."""
    resp = (db.get_client().table('matriz_replicacoes').select('*')
            .order('criado_em', desc=True).limit(200).execute())
    return {'replicacoes': resp.data}


@admin_bp.route('/api/matriz/intervalo-criado', methods=['GET'])
@_admin
def api_matriz_intervalo_criado():
    """Usado pela tela "Visualizar agenda" (item 2, pedido do Paulo em
    24/09/2026): descobre o intervalo de datas que JÁ tem matriz
    replicada de verdade (matriz_reservas_admin -- é o que "Replicar
    matriz por período/mês" cria), pra tela buscar exatamente "todos os
    dias das agendas criadas", nem mais nem menos."""
    cliente = db.get_client()
    primeira = cliente.table('matriz_reservas_admin').select('data').order('data', desc=False).limit(1).execute().data
    ultima = cliente.table('matriz_reservas_admin').select('data').order('data', desc=True).limit(1).execute().data
    if not primeira or not ultima:
        return {'data_inicio': None, 'data_fim': None, 'dias': 0}
    data_inicio = date.fromisoformat(primeira[0]['data'])
    data_fim = date.fromisoformat(ultima[0]['data'])
    dias = (data_fim - data_inicio).days + 1
    return {'data_inicio': data_inicio.isoformat(), 'data_fim': data_fim.isoformat(), 'dias': dias}


# ---------------------------------------------------------------------
# Item 6 (pedido do Paulo em 21/09/2026): botões "Agendar para:" e
# "Cancelar agendamento", só pro admin, na Agenda Horistas. Reaproveita
# 100% da regra de saldo/conflito/reembolso já usada quando o próprio
# médico reserva ou cancela (ver reserva_service.reservar_por_hora /
# cancelar_reserva_admin) -- só passa criado_por_admin/cancelado_por_admin
# =True, pra Grade de Turnos, Minha Agenda e o extrato de horas do médico
# mostrarem que foi o administrador quem fez.
# ---------------------------------------------------------------------

@admin_bp.route('/api/agenda-horistas/medicos', methods=['GET'])
@_admin
def api_agenda_horistas_medicos():
    """Lista pro seletor de "Agendar para:" -- pedido do Paulo em
    23/09/2026 (item 6): TODOS os médicos ativos, não só os de tipo
    'avulso' -- antes essa lista ficava restrita aos avulsos (que alugam
    consultório por essa agenda por padrão), mas o admin também precisa
    poder agendar manualmente pra um médico fixo/horista em algum
    encaixe avulso, então a lista não filtra mais por tipo_vinculo."""
    todos = db.get_client().table('medicos').select('id,nome,telefone,tipo_vinculo').eq('ativo', True).execute().data
    todos.sort(key=lambda m: (m.get('nome') or '').lower())
    return {'medicos': todos}


@admin_bp.route('/api/agenda-horistas/agendar', methods=['POST'])
@_admin
def api_agenda_horistas_agendar():
    body = request.get_json(force=True)
    medico_id = body.get('medico_id')
    celulas = body.get('celulas') or []
    if not medico_id or not celulas:
        return {'erro': 'Selecione o profissional e pelo menos um horário.'}, 400

    sucesso = []
    erros = []
    for c in celulas:
        consultorio_id = c.get('consultorio_id')
        data_str = c.get('data')
        hora_inicio = c.get('hora_inicio')
        if not all([consultorio_id, data_str, hora_inicio]):
            erros.append({'consultorio_id': consultorio_id, 'data': data_str, 'hora_inicio': hora_inicio,
                          'erro': 'Célula inválida.'})
            continue
        try:
            resultado = reserva_service.reservar_por_hora(
                medico_id, consultorio_id, data_str, hora_inicio, 1, criado_por_admin=True,
            )
            # Pedido do Paulo em 23/09/2026 (item 7): deixa explícito no
            # retorno se essa hora foi DEBITADA do saldo do médico ou se
            # entrou como cortesia de tryout (as 3 primeiras reservas do
            # médico em qualquer canal são grátis por design -- ver
            # creditos_db.tryout_restante/debitar_credito_por_reserva) --
            # sem isso não dava pra distinguir, na tela do admin, se o
            # débito realmente aconteceu ou se essa reserva específica
            # era, de fato, uma cortesia.
            sucesso.append({'consultorio_id': consultorio_id, 'data': data_str, 'hora_inicio': hora_inicio,
                            'reserva_id': resultado['reserva']['id'], 'tryout': resultado.get('tryout', False),
                            'saldo_atual': resultado.get('saldo_atual')})
        except Exception as e:
            erros.append({'consultorio_id': consultorio_id, 'data': data_str, 'hora_inicio': hora_inicio,
                          'erro': str(e)})

    return {'sucesso': sucesso, 'erros': erros}


@admin_bp.route('/controle-ia')
@_admin
def controle_ia():
    """"Controle de IA" (pedido do Paulo em 21/09/2026): quanto cada
    médico gastou de IA (GPT/Luna), o custo real total pago pra OpenAI e
    o lucro da operação (o que foi cobrado dos médicos menos esse custo
    real) num mês escolhido -- mesmo filtro de mês/ano da tela "Horas".
    Também é aqui que o admin edita a margem cobrada em cima do custo
    real (ver ia_uso_service.atualizar_config_precificacao_ia)."""
    hoje = date.today()
    mes_valor = request.args.get('mes') or f"{hoje.year:04d}-{hoje.month:02d}"
    try:
        ano, mes = (int(p) for p in mes_valor.split('-', 1))
        if not (1 <= mes <= 12):
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
        mes_valor = f"{ano:04d}-{mes:02d}"

    stats = ia_uso.estatisticas_uso_ia(mes, ano)
    stats_total = ia_uso.estatisticas_uso_ia()
    por_medico = ia_uso.estatisticas_uso_ia_por_medico(mes, ano)
    config_precificacao = ia_uso.obter_config_precificacao_ia()
    return render_template(
        'admin_controle_ia.html', stats=stats, stats_total=stats_total, por_medico=por_medico,
        config=config_precificacao, mes=mes, ano=ano, mes_valor=mes_valor, mes_nome=_NOMES_MESES[mes],
    )


@admin_bp.route('/controle-ia/precificacao', methods=['POST'])
@_admin
def atualizar_precificacao_ia():
    """Salva o percentual de aumento e os preços por 1.000 tokens
    editados na tela "Controle de IA"."""
    try:
        percentual_aumento = float((request.form.get('percentual_aumento') or '0').replace(',', '.'))
        preco_entrada_usd_1k = float((request.form.get('preco_entrada_usd_1k') or '0').replace(',', '.'))
        preco_saida_usd_1k = float((request.form.get('preco_saida_usd_1k') or '0').replace(',', '.'))
        usd_para_brl = float((request.form.get('usd_para_brl') or '0').replace(',', '.'))
    except ValueError:
        flash('Valores inválidos -- confira os campos numéricos.', 'erro')
        return redirect(url_for('admin.controle_ia', mes=request.form.get('mes_valor')))

    try:
        ia_uso.atualizar_config_precificacao_ia(
            percentual_aumento, preco_entrada_usd_1k, preco_saida_usd_1k, usd_para_brl,
        )
    except ValueError as e:
        flash(str(e), 'erro')
        return redirect(url_for('admin.controle_ia', mes=request.form.get('mes_valor')))

    flash('Precificação de IA atualizada.', 'ok')
    return redirect(url_for('admin.controle_ia', mes=request.form.get('mes_valor')))


@admin_bp.route('/api/agenda-horistas/cancelar', methods=['POST'])
@_admin
def api_agenda_horistas_cancelar():
    """A tela de revisão (2º passo, com o nome de cada profissional antes
    de confirmar de vez) é montada no próprio navegador a partir dos
    dados que a grade já carregou -- não precisa de uma rota própria só
    pra isso. Essa rota já é a confirmação FINAL: recebe os ids das
    reservas escolhidas e cancela cada uma (com a mesma regra de
    reembolso de 12h de sempre)."""
    body = request.get_json(force=True)
    reserva_ids = body.get('reserva_ids') or []
    if not reserva_ids:
        return {'erro': 'Selecione pelo menos um horário ocupado para cancelar.'}, 400

    sucesso = []
    erros = []
    for reserva_id in reserva_ids:
        try:
            resultado = reserva_service.cancelar_reserva_admin(reserva_id)
            sucesso.append({'reserva_id': reserva_id, **resultado})
        except Exception as e:
            erros.append({'reserva_id': reserva_id, 'erro': str(e)})

    return {'sucesso': sucesso, 'erros': erros}
