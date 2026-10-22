"""
Painel pessoal do médico (autenticado): ver saldo, histórico de
transações, e comprar créditos gerando um PIX via Asaas.
"""
from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for
from app.services import supabase_client as db
from app.services import creditos_service as creditos_db
from app.services import asaas_client
from app.services import modulos_service
from app.services import pacientes_service
from app.services import reserva_service
from app.services.auth_service import requer_login_medico, medico_logado_id
from app.services.termo_service import requer_termo_aceito

medico_painel_bp = Blueprint("medico_painel", __name__)


@medico_painel_bp.route("/painel")
@requer_login_medico
@requer_termo_aceito
def painel():
    medico = db.get_medico_by_id(medico_logado_id())
    saldo = creditos_db.obter_saldo(medico["id"])
    saldo_horas = creditos_db.saldo_em_horas_medico(medico["id"])
    transacoes = creditos_db.listar_transacoes_medico(medico["id"])
    precos = creditos_db.obter_precos()
    horas_minimas = int(precos.get("horas_minimas", 1))
    preco_minimo = creditos_db.calcular_preco_horas(horas_minimas)
    pacotes_horas = creditos_db.listar_pacotes_horas()
    notas_fiscais = creditos_db.listar_pagamentos_com_nota_medico(medico["id"])
    modulos = modulos_service.listar_modulos_visiveis(medico)
    # "Minha agenda" -- pedido do Paulo em 11/09/2026: deixou de ser uma
    # tela separada (/painel/agenda, atrás de um botão) e passou a
    # aparecer direto aqui no topo do painel, logo no início, antes do
    # board de saldos. `pacientes` é a lista (só cadastro, sem senha) que
    # alimenta o botão "Paciente" do e-mail de confirmação de cada linha da
    # agenda e também o botão "Pacientes cadastrados".
    reservas = db.listar_reservas_medico(medico["id"])
    pacientes = pacientes_service.listar_pacientes_medico(medico["id"])
    # Pedido do Paulo em 23/09/2026 (item 2): avisa no painel quais dados
    # ainda faltam pra poder reservar -- mesma lista de campos que
    # reserva_service._checar_pode_alugar_avulso exige.
    campos_faltando = reserva_service._campos_pessoais_faltando(medico)
    return render_template("painel_medico.html", medico=medico, saldo=saldo, saldo_horas=saldo_horas,
                            transacoes=transacoes, precos=precos,
                            horas_minimas=horas_minimas, preco_minimo=preco_minimo,
                            pacotes_horas=pacotes_horas,
                            notas_fiscais=notas_fiscais, modulos=modulos,
                            reservas=reservas, pacientes=pacientes,
                            pacientes_json=[{"id": p["id"], "nome": p["nome_completo"], "email": p.get("email") or "", "telefone": p.get("telefone") or ""}
                                            for p in pacientes],
                            campos_faltando=campos_faltando,
                            endereco_lifemax=_endereco_lifemax())


def _endereco_lifemax() -> str:
    """Endereço exibido em "Reserva confirmada": o padrão cadastrado em Admin > Horas,
    ou Rua Gonçalves Dias, 82 enquanto ele não estiver configurado."""
    e = creditos_db.endereco_padrao_formatado()
    return "Rua Gonçalves Dias, 82" if e == "Endereço não configurado" else e


def _resolver_pacote_salas(body: dict):
    """Lê `pacote_horas` do corpo da requisição (compra de um pacote
    fechado de horas -- 6/12/24/48h, ver creditos_db.listar_pacotes_horas)
    e devolve (pacote_ou_None, valor_salas, erro_ou_None, status_http).
    Substituiu o campo livre "valor em R$" que existia antes (10/09/2026,
    pedido do Paulo) -- agora a venda de horas avulsas só acontece nesses
    4 blocos fechados, não mais em qualquer valor digitado pelo médico."""
    pacote_horas = body.get("pacote_horas")
    if not pacote_horas:
        return None, 0.0, None, None

    try:
        pacote_horas = int(pacote_horas)
    except (TypeError, ValueError):
        return None, 0.0, "Pacote de horas inválido.", 400

    pacote = creditos_db.obter_pacote_por_horas(pacote_horas)
    if not pacote:
        return None, 0.0, "Esse pacote de horas não existe (ou não está mais ativo).", 400
    return pacote, float(pacote["valor_total"]), None, None


@medico_painel_bp.route("/api/creditos/comprar", methods=["POST"])
@requer_login_medico
def comprar_creditos():
    body = request.get_json(force=True)
    medico = db.get_medico_by_id(medico_logado_id())

    pacote, valor_salas, erro, status_erro = _resolver_pacote_salas(body)
    if erro:
        return jsonify({"erro": erro}), status_erro

    valor = round(valor_salas, 2)
    if valor < 10:
        return jsonify({"erro": "O valor total mínimo para recarga é R$ 10,00."}), 400

    try:
        customer_id = asaas_client.criar_ou_obter_cliente(
            medico["nome"], medico["telefone"], medico["id"], medico.get("cpf_cnpj")
        )
        cobranca = asaas_client.criar_cobranca_pix(
            customer_id, valor, f"Créditos Lifemax — {medico['nome']}"
        )
        qrcode = asaas_client.obter_qrcode_pix(cobranca["id"])
    except asaas_client.CpfCnpjObrigatorioError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Não consegui gerar o PIX agora: {e}"}), 502

    registro = creditos_db.criar_registro_pagamento(
        medico_id=medico["id"],
        asaas_payment_id=cobranca["id"],
        asaas_customer_id=customer_id,
        valor=valor,
        qr_code_base64=qrcode.get("encodedImage", ""),
        copia_e_cola=qrcode.get("payload", ""),
        valor_salas=valor_salas,
        horas_pacote=(pacote["horas"] if pacote else None),
    )

    return jsonify({
        "pagamento_id": registro["id"],
        "qr_code_base64": registro["qr_code_base64"],
        "copia_e_cola": registro["copia_e_cola"],
        "valor": valor,
    })


@medico_painel_bp.route("/api/creditos/comprar-cartao", methods=["POST"])
@requer_login_medico
def comprar_creditos_cartao():
    body = request.get_json(force=True)
    medico = db.get_medico_by_id(medico_logado_id())

    pacote, valor_salas, erro, status_erro = _resolver_pacote_salas(body)
    if erro:
        return jsonify({"erro": erro}), status_erro

    valor = round(valor_salas, 2)
    if valor < 10:
        return jsonify({"erro": "O valor total mínimo para recarga é R$ 10,00."}), 400

    max_parcelas = pacote["max_parcelas"] if pacote else 1
    try:
        parcelas = int(body.get("parcelas", 1) or 1)
    except (TypeError, ValueError):
        return jsonify({"erro": "Número de parcelas inválido."}), 400
    if parcelas < 1 or parcelas > max_parcelas:
        return jsonify({"erro": f"Esse pacote pode ser pago em até {max_parcelas}x no cartão."}), 400

    try:
        customer_id = asaas_client.criar_ou_obter_cliente(
            medico["nome"], medico["telefone"], medico["id"], medico.get("cpf_cnpj")
        )
        cobranca = asaas_client.criar_cobranca_cartao(
            customer_id, valor, f"Créditos Lifemax — {medico['nome']}", parcelas=parcelas
        )
    except asaas_client.CpfCnpjObrigatorioError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        return jsonify({"erro": f"Não consegui gerar a cobrança agora: {e}"}), 502

    registro = creditos_db.criar_registro_pagamento_cartao(
        medico_id=medico["id"],
        asaas_payment_id=cobranca["id"],
        asaas_customer_id=customer_id,
        valor=valor,
        invoice_url=cobranca.get("invoiceUrl", ""),
        valor_salas=valor_salas,
        horas_pacote=(pacote["horas"] if pacote else None),
        parcelas=parcelas,
    )

    return jsonify({
        "pagamento_id": registro["id"],
        "invoice_url": registro["invoice_url"],
        "valor": valor,
    })



@medico_painel_bp.route("/painel/dados-pessoais")
@requer_login_medico
@requer_termo_aceito
def pagina_dados_pessoais():
    medico = db.get_medico_by_id(medico_logado_id())
    # Pedido do Paulo em 24/09/2026 (item 4): pra tela saber se o
    # cadastro JÁ estava completo antes desta visita (e não disparar a
    # tela de "Parabéns" à toa se ele só entrar aqui pra corrigir um
    # campo depois de já estar tudo liberado) -- mesma checagem de
    # reserva_service._campos_pessoais_faltando usada em todo o resto do
    # sistema.
    cadastro_completo_inicial = not reserva_service._campos_pessoais_faltando(medico)
    return render_template("painel_dados_pessoais.html", medico=medico,
                            cadastro_completo_inicial=cadastro_completo_inicial)


@medico_painel_bp.route("/api/perfil/dados-pessoais", methods=["POST"])
@requer_login_medico
def salvar_dados_pessoais():
    body = request.get_json(force=True)
    try:
        medico = creditos_db.atualizar_dados_pessoais(medico_logado_id(), body)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    # Item 4 (pedido do Paulo em 24/09/2026): devolve se o cadastro ficou
    # completo (o suficiente pra reservar) DEPOIS deste salvamento -- o
    # front usa isso pra decidir se mostra a tela de "Parabéns" (só na
    # transição de incompleto -> completo, ver painel_dados_pessoais.html).
    cadastro_completo = not reserva_service._campos_pessoais_faltando(medico)
    return jsonify({"resultado": "Dados salvos com sucesso.", "medico": medico,
                     "cadastro_completo": cadastro_completo})


@medico_painel_bp.route("/painel/agenda")
@requer_login_medico
@requer_termo_aceito
def pagina_minha_agenda():
    """"Minha agenda" deixou de ser uma tela à parte (pedido do Paulo em
    11/09/2026) -- agora ela aparece direto no topo do /painel. Mantém
    essa rota só como redirecionamento (algum favorito/link antigo pode
    apontar pra cá), em vez de simplesmente derrubar a URL com um 404."""
    return redirect(url_for("medico_painel.painel"))


@medico_painel_bp.route("/manual")
@requer_login_medico
def manual():
    """Botão "Manual" (sob o logo): manual do cliente como página. Os pacotes de horas vêm do
    banco, então a tabela de preços nunca fica desatualizada. Ao mudar o sistema, atualizar
    também templates/manual_cliente.html (e o PDF static/docs, enviado no e-mail de acesso)."""
    return render_template("manual_cliente.html", pacotes_horas=creditos_db.listar_pacotes_horas())


@medico_painel_bp.route("/painel/pacientes")
@requer_login_medico
@requer_termo_aceito
def pagina_pacientes_cadastrados():
    """Botão "Pacientes cadastrados" -- pedido do Paulo em 11/09/2026:
    lista, numa planilha, a ficha completa de cada paciente que esse
    médico cadastrou, com um botão "Editar dados" por linha."""
    medico = db.get_medico_by_id(medico_logado_id())
    pacientes = pacientes_service.listar_pacientes_medico(medico["id"])
    return render_template("painel_pacientes.html", medico=medico, pacientes=pacientes)


@medico_painel_bp.route("/api/pacientes", methods=["POST"])
@requer_login_medico
def criar_paciente():
    """Botão "Cadastre o seu paciente" do painel -- cria uma ficha nova.
    Recebe JSON com qualquer subconjunto de pacientes_service.CAMPOS_PACIENTE
    (o formulário manda todos os campos preenchidos de uma vez)."""
    body = request.get_json(force=True)
    try:
        paciente = pacientes_service.criar_paciente(medico_logado_id(), body)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    return jsonify({"resultado": "Paciente cadastrado com sucesso.", "paciente": paciente})


@medico_painel_bp.route("/api/pacientes/<paciente_id>", methods=["POST"])
@requer_login_medico
def atualizar_paciente(paciente_id):
    """Botão "Editar dados" da tela "Pacientes cadastrados"."""
    body = request.get_json(force=True)
    try:
        paciente = pacientes_service.atualizar_paciente(paciente_id, medico_logado_id(), body)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    return jsonify({"resultado": "Dados do paciente salvos com sucesso.", "paciente": paciente})


@medico_painel_bp.route("/api/reservas/<reserva_id>/confirmacao-previa", methods=["GET"])
@requer_login_medico
def confirmacao_previa(reserva_id):
    """Mensagem padrão do e-mail de confirmação (tela "Enviar e-mail de
    confirmação" da Minha agenda). `paciente_id` opcional: só personaliza a
    saudação com o nome."""
    nome = None
    paciente_id = (request.args.get("paciente_id") or "").strip()
    if paciente_id:
        p = pacientes_service.get_paciente_by_id(paciente_id)
        if p and p["medico_id"] == medico_logado_id():
            nome = p["nome_completo"]
    try:
        return jsonify(reserva_service.montar_confirmacao_consulta(reserva_id, medico_logado_id(), nome))
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400


@medico_painel_bp.route("/api/reservas/<reserva_id>/enviar-confirmacao", methods=["POST"])
@requer_login_medico
def enviar_confirmacao(reserva_id):
    body = request.get_json(force=True)
    try:
        resultado = reserva_service.enviar_confirmacao_consulta(
            reserva_id, medico_logado_id(), (body.get("paciente_id") or "").strip(),
            mensagem=body.get("mensagem"))
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    if not resultado["enviado"]:
        return jsonify({"erro": "Não consegui enviar o e-mail agora (o envio de e-mail -- SMTP_*/EMAIL_FROM -- "
                                "ainda não está configurado neste sistema)."}), 400
    return jsonify({"resultado": f"E-mail enviado para {resultado['email']}."})


@medico_painel_bp.route("/api/perfil/cpf-cnpj", methods=["POST"])
@requer_login_medico
def atualizar_cpf_cnpj():
    body = request.get_json(force=True)
    valor = (body.get("cpf_cnpj") or "").strip()

    # remove tudo que não for dígito para validar o tamanho
    apenas_digitos = "".join(c for c in valor if c.isdigit())
    if len(apenas_digitos) not in (11, 14):  # 11 = CPF, 14 = CNPJ
        return jsonify({"erro": "CPF deve ter 11 dígitos ou CNPJ 14 dígitos."}), 400

    creditos_db.atualizar_cpf_cnpj(medico_logado_id(), valor)
    return jsonify({"resultado": "CPF/CNPJ salvo com sucesso."})


@medico_painel_bp.route("/api/perfil/crm", methods=["POST"])
@requer_login_medico
def atualizar_crm():
    body = request.get_json(force=True)
    valor = (body.get("crm") or "").strip()

    if not valor:
        return jsonify({"erro": "Informe o número do CRM."}), 400

    creditos_db.atualizar_crm(medico_logado_id(), valor)
    return jsonify({"resultado": "CRM salvo com sucesso."})


@medico_painel_bp.route("/api/creditos/status/<pagamento_id>")
@requer_login_medico
def status_pagamento(pagamento_id):
    pagamento = creditos_db.obter_pagamento_por_id(pagamento_id)
    if not pagamento or pagamento["medico_id"] != medico_logado_id():
        return jsonify({"erro": "Pagamento não encontrado."}), 404

    # fallback: se por algum motivo o webhook do Asaas ainda não chegou,
    # consultamos o status direto na API (o médico pode estar com a tela
    # de QR code aberta esperando)
    if pagamento["status"] == "pendente":
        try:
            info_asaas = asaas_client.consultar_pagamento(pagamento["asaas_payment_id"])
            if info_asaas.get("status") in ("RECEIVED", "CONFIRMED"):
                from app.routes.webhooks_asaas import confirmar_pagamento_e_creditar
                confirmar_pagamento_e_creditar(pagamento["asaas_payment_id"])
                pagamento = creditos_db.obter_pagamento_por_id(pagamento_id)
        except Exception:
            pass  # não quebra a tela do médico se a consulta falhar

    saldo_atual = creditos_db.obter_saldo(medico_logado_id())
    return jsonify({"status": pagamento["status"], "saldo_atual": saldo_atual})
