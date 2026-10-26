"""
Camada de acesso ao Supabase para o sistema de créditos: senha dos
médicos, saldo, histórico de transações, preços configuráveis e
pagamentos PIX (Asaas).

Schema (criado por sql/migration_creditos.sql):
  medicos.senha_hash, medicos.saldo_creditos, medicos.alerta_saldo_baixo_enviado
  precos (preco_hora, preco_turno)
  creditos_transacoes (medico_id, tipo, valor, saldo_apos, descricao, ...)
  pagamentos_pix (medico_id, asaas_payment_id, valor, status, ...)
"""
import os
from app.services.supabase_client import get_client, agora_iso


# ---------- Senha / autenticação ----------

def definir_senha_medico(medico_id: str, senha_hash: str):
    get_client().table("medicos").update({"senha_hash": senha_hash}).eq("id", medico_id).execute()


def medico_tem_senha(medico: dict) -> bool:
    return bool(medico.get("senha_hash"))


# ---------- Preços ----------

def obter_precos() -> dict:
    """Só o que ainda está em uso daqui: `horas_minimas` (mínimo de horas
    por reserva). Os campos de preço escalonado (preco_hora_1/2/3,
    preco_turno) continuam existindo na tabela por compatibilidade, mas o
    código não lê mais eles -- desde 10/09/2026 o preço de venda de horas
    vem todo de `pacotes_horas_avulsas` (ver
    listar_pacotes_horas/preco_hora_avulsa abaixo)."""
    resp = get_client().table("precos").select("*").limit(1).execute()
    if resp.data:
        return resp.data[0]
    return {"horas_minimas": 1}


def obter_endereco_padrao() -> dict:
    """Endereço padrão da Lifemax (colunas `endereco_padrao_*` de
    `precos`, ver migration_endereco_padrao_lifemax.sql) -- usado desde
    11/09/2026 no e-mail de confirmação de consulta pro paciente
    (reserva_service.enviar_confirmacao_consulta). Editável em
    Admin > Horas."""
    precos = obter_precos()
    return {
        "rua": precos.get("endereco_padrao_rua") or "",
        "numero": precos.get("endereco_padrao_numero") or "",
        "complemento": precos.get("endereco_padrao_complemento") or "",
        "bairro": precos.get("endereco_padrao_bairro") or "",
        "cidade": precos.get("endereco_padrao_cidade") or "",
        "estado": precos.get("endereco_padrao_estado") or "",
        "cep": precos.get("endereco_padrao_cep") or "",
    }


def endereco_padrao_formatado() -> str:
    """Mesmo endereço de obter_endereco_padrao(), já formatado numa
    linha só pra usar direto no corpo do e-mail."""
    e = obter_endereco_padrao()
    partes = []
    if e["rua"]:
        linha = e["rua"]
        if e["numero"]:
            linha += f", {e['numero']}"
        if e["complemento"]:
            linha += f" ({e['complemento']})"
        partes.append(linha)
    if e["bairro"]:
        partes.append(e["bairro"])
    cidade_estado = " - ".join(p for p in [e["cidade"], e["estado"]] if p)
    if cidade_estado:
        partes.append(cidade_estado)
    return ", ".join(partes) or "Endereço não configurado"


def atualizar_endereco_padrao(rua: str, numero: str, complemento: str, bairro: str,
                               cidade: str, estado: str, cep: str) -> dict:
    """Salva o endereço padrão da Lifemax -- tela Admin > Horas."""
    client = get_client()
    atual = client.table("precos").select("id").limit(1).execute().data
    payload = {
        "endereco_padrao_rua": rua, "endereco_padrao_numero": numero,
        "endereco_padrao_complemento": complemento, "endereco_padrao_bairro": bairro,
        "endereco_padrao_cidade": cidade, "endereco_padrao_estado": estado,
        "endereco_padrao_cep": cep,
    }
    if atual:
        resp = client.table("precos").update(payload).eq("id", atual[0]["id"]).execute()
    else:
        resp = client.table("precos").insert(payload).execute()
    return resp.data[0]


def atualizar_precos(preco_hora_1: float, preco_hora_2: float, preco_hora_3: float,
                      preco_turno: float, horas_minimas: int) -> dict:
    """Mantida só por compatibilidade (nada mais chama essa função hoje --
    não havia nenhuma tela admin usando ela). Preço de venda de horas
    agora se edita em `pacotes_horas_avulsas`, não aqui."""
    client = get_client()
    atual = client.table("precos").select("id").limit(1).execute().data
    payload = {
        "preco_hora_1": preco_hora_1, "preco_hora_2": preco_hora_2, "preco_hora_3": preco_hora_3,
        "preco_turno": preco_turno, "horas_minimas": horas_minimas, "atualizado_em": agora_iso(),
    }
    if atual:
        resp = client.table("precos").update(payload).eq("id", atual[0]["id"]).execute()
    else:
        resp = client.table("precos").insert(payload).execute()
    return resp.data[0]


# ---------- Pacotes de horas (venda de horas avulsas) ----------
#
# Substituem, desde 10/09/2026 (pedido do Paulo), o preço escalonado
# antigo (1ª/2ª/3ª hora + turno de 4h). Agora o médico compra um pacote
# fechado (6h/12h/24h/48h, cada um com seu preço por hora e opção de
# parcelamento no cartão) em vez de um valor livre em R$ -- ver
# migration_pacotes_horas_avulsas.sql. Guardados na tabela
# `pacotes_horas_avulsas` -- NÃO confundir com a tabela `pacotes_horas`
# (essa já existia, é só a lista de quantidades usada pra CREDITAR horas
# manualmente ao médico horista, sem preço nem cobrança).

def listar_pacotes_horas() -> list[dict]:
    """Os 4 pacotes ativos, do menor pro maior -- é o que alimenta tanto a
    tela de compra do médico (painel_medico.html) quanto o cálculo do
    preço da hora avulsa (preco_hora_avulsa, abaixo)."""
    resp = get_client().table("pacotes_horas_avulsas").select("*").eq("ativo", True).order("horas").execute()
    return resp.data


def validar_novos_valores_pacotes(pacotes: list[dict], novos: dict) -> tuple[dict, str | None]:
    """Valida os valores/hora digitados pelo admin em "Alterar valores".
    `novos` = {horas(int): valor_hora(float)}. Devolve ({horas: valor_hora
    arredondado}, erro_ou_None). Regras: todo pacote precisa de um valor
    maior que zero (máx. R$ 10.000/h) e, como a tela do médico promete
    "quanto mais horas, menor o preço por hora", um pacote maior nunca
    pode ter valor/hora MAIOR que o de um pacote menor."""
    resultado = {}
    for p in pacotes:
        h = int(p["horas"])
        if h not in novos:
            return {}, f"Informe o valor do pacote de {h}h."
        v = novos[h]
        if v is None or v <= 0 or v > 10000:
            return {}, f"Valor inválido no pacote de {h}h: informe um valor maior que zero."
        resultado[h] = round(float(v), 2)
    ordem = sorted(resultado)
    for menor, maior in zip(ordem, ordem[1:]):
        if resultado[maior] > resultado[menor]:
            return {}, (f"O pacote de {maior}h não pode ter valor por hora maior que o de {menor}h "
                        f"(quanto mais horas, menor o preço por hora).")
    return resultado, None


def atualizar_valores_pacotes(novos: dict) -> None:
    """Grava (já validados) os novos valores/hora dos pacotes. O total de
    cada pacote é sempre horas x valor/hora. Pagamentos JÁ criados mantêm o
    valor com que foram cobrados (guardado em pagamentos_pix)."""
    from app.services.supabase_client import agora_iso
    client = get_client()
    for horas, valor_hora in novos.items():
        client.table("pacotes_horas_avulsas").update({
            "valor_hora": valor_hora,
            "valor_total": round(horas * valor_hora, 2),
            "atualizado_em": agora_iso(),
        }).eq("horas", horas).eq("ativo", True).execute()


def obter_pacote_por_horas(horas: int) -> dict | None:
    resp = (
        get_client().table("pacotes_horas_avulsas").select("*")
        .eq("horas", horas).eq("ativo", True).limit(1).execute()
    )
    return resp.data[0] if resp.data else None


def preco_hora_avulsa(pacotes: list[dict] | None = None) -> float:
    """Preço de 1 hora avulsa (usado para debitar reservas feitas por
    hora, e o turno de 4h da Grade de Turnos): é o valor/hora do MENOR
    pacote cadastrado (hoje, o de 6h) -- comprar em bloco maior sai mais
    barato, comprar avulso/reservar direto do saldo sai no preço cheio."""
    if pacotes is None:
        pacotes = listar_pacotes_horas()
    if not pacotes:
        return 0.0
    return float(pacotes[0]["valor_hora"])


def calcular_preco_horas(n_horas: int, precos=None) -> float:
    """Preço para debitar N horas do saldo (reserva por hora ou turno):
    hora avulsa, valor fixo por hora (ver preco_hora_avulsa). `precos` é
    aceito só por compatibilidade com quem ainda chama passando o dict
    antigo de obter_precos() -- não é mais usado aqui."""
    if n_horas <= 0:
        raise ValueError("A quantidade de horas precisa ser maior que zero.")
    return round(n_horas * preco_hora_avulsa(), 2)


def estimar_horas_compraveis(saldo: float, pacotes: list[dict] | None = None, limite: int = 60) -> int:
    """Quantas horas o saldo atual consegue pagar, no preço da hora
    avulsa (flat). Passe `pacotes` (de listar_pacotes_horas()) quando for
    chamar isso muitas vezes seguidas (ex: um médico por vez num loop),
    pra não buscar a lista de pacotes de novo a cada chamada."""
    preco = preco_hora_avulsa(pacotes)
    if preco <= 0:
        return 0
    return min(int(saldo // preco), limite)


# ---------- Créditos ----------

def obter_saldo(medico_id: str) -> float:
    resp = get_client().table("medicos").select("saldo_creditos").eq("id", medico_id).execute()
    return float(resp.data[0]["saldo_creditos"]) if resp.data else 0.0


TRYOUT_TOTAL = 0  # DESATIVADO -- ver tryout_restante() abaixo.


def tryout_restante(medico_id: str) -> int:
    """DESATIVADO -- pedido do Paulo em 24/09/2026: não existe mais
    cortesia/teste grátis nenhuma, TODA reserva tem que debitar do saldo
    do médico, sem exceção. Antes (pedido do Paulo em 21/09/2026) as 3
    primeiras reservas de consultório do médico eram de graça; sempre
    devolver 0 aqui é o único ponto que precisa mudar pra desligar isso
    em todo o sistema -- reservar_turno/reservar_por_hora (ver
    reserva_service.py) calculam `usa_tryout = tryout_restante(...) > 0`,
    então com 0 aqui essa conta dá sempre False e o fluxo normal de
    checagem de saldo + débito roda para 100% das reservas, em qualquer
    canal (site ou assistente Dora) e também quando é o admin quem
    agenda pela Agenda Horistas."""
    return 0


def registrar_transacao(medico_id: str, tipo: str, valor: float, descricao: str,
                         reserva_id: str | None = None, pagamento_id: str | None = None,
                         quantidade_horas: int | None = None, categoria: str = "horas",
                         carteira: str = "salas") -> dict:
    """
    Registra uma transação e atualiza o saldo do médico de forma
    consistente. tipo: 'compra' | 'consumo' | 'ajuste'.
    valor: positivo para compra/ajuste-crédito, negativo para consumo.
    quantidade_horas: quantas horas essa reserva ocupou (só faz sentido
    para tipo='consumo' — usado nos relatórios do dashboard por hora).
    categoria: 'horas' (reserva de consultório) — usado nos relatórios.

    `carteira`: só existe a 'salas' (saldo_creditos). A carteira de IA
    foi removida do sistema a pedido do Paulo em 19/10/2026.
    """
    if carteira != "salas":
        raise ValueError(f"Carteira inválida: {carteira}")

    campo_saldo = "saldo_creditos"
    campo_alerta = "alerta_saldo_baixo_enviado"

    client = get_client()
    saldo_atual = obter_saldo(medico_id)
    novo_saldo = round(saldo_atual + valor, 2)

    update_medico = {campo_saldo: novo_saldo}
    if valor > 0:
        # sempre que o saldo sobe (compra ou ajuste positivo), destrava o
        # alerta de saldo baixo, pra poder ser enviado de
        # novo no futuro se o saldo cair de novo
        update_medico[campo_alerta] = False
    client.table("medicos").update(update_medico).eq("id", medico_id).execute()

    transacao = (
        client.table("creditos_transacoes")
        .insert({
            "medico_id": medico_id,
            "tipo": tipo,
            "valor": valor,
            "saldo_apos": novo_saldo,
            "descricao": descricao,
            "reserva_id": reserva_id,
            "pagamento_id": pagamento_id,
            "quantidade_horas": quantidade_horas,
            "categoria": categoria,
            "carteira": carteira,
        })
        .execute()
    )
    return {"saldo_novo": novo_saldo, "transacao": transacao.data[0]}


def debitar_credito_por_reserva(medico_id: str, valor_turno: float, reserva_id: str,
                                 quantidade_horas: int, criado_por_admin: bool = False,
                                 tryout: bool = False) -> dict:
    """Debita o valor de uma reserva. Levanta ValueError se saldo insuficiente.

    `criado_por_admin` -- pedido do Paulo em 21/09/2026 (botão "Agendar
    para:" da Agenda Horistas): só muda a descrição da transação no
    extrato do médico, pra ficar claro que foi o admin quem agendou --
    o débito em si é idêntico ao de uma reserva feita pelo próprio
    médico.

    `tryout` -- pedido do Paulo em 21/09/2026: uma das 3 primeiras
    reservas grátis do médico (ver tryout_restante) -- não debita nada,
    só registra a transação (valor 0) pra aparecer no extrato normal."""
    if tryout:
        descricao = "Reserva de teste grátis (cortesia de boas-vindas)" + (
            " (agendada pelo administrador da Lifemax)" if criado_por_admin else ""
        )
        return registrar_transacao(
            medico_id, tipo="consumo", valor=0.0,
            descricao=descricao, reserva_id=reserva_id,
            quantidade_horas=quantidade_horas,
        )

    saldo_atual = obter_saldo(medico_id)
    if saldo_atual < valor_turno:
        raise ValueError(
            f"Saldo insuficiente: você tem R$ {saldo_atual:.2f} e essa reserva custa R$ {valor_turno:.2f}."
        )
    descricao = "Reserva de consultório" + (
        " (agendada pelo administrador da Lifemax)" if criado_por_admin else ""
    )
    return registrar_transacao(
        medico_id, tipo="consumo", valor=-valor_turno,
        descricao=descricao, reserva_id=reserva_id,
        quantidade_horas=quantidade_horas,
    )


def listar_transacoes_medico(medico_id: str, limite: int = 50) -> list[dict]:
    resp = (
        get_client()
        .table("creditos_transacoes")
        .select("*")
        .eq("medico_id", medico_id)
        .eq("carteira", "salas")  # IA foi removida do sistema (19/10/2026) -- movimentos antigos dessa carteira não aparecem mais
        .order("criado_em", desc=True)
        .limit(limite)
        .execute()
    )
    return enriquecer_transacoes_com_horas(resp.data)


def enriquecer_transacoes_com_horas(transacoes: list[dict]) -> list[dict]:
    """Acrescenta `horas_exibicao` e `saldo_apos_horas` em cada transação
    da carteira 'salas' -- pedido do Paulo em 10/09/2026: a carteira de
    Salas/Horas é medida em HORAS em qualquer lugar do sistema, nunca em
    R$ (ao contrário da carteira de IA, que continua em R$). Prioriza o
    `quantidade_horas` já gravado na transação (exato, vem de reserva ou
    compra de pacote); quando não tem (transações antigas, ou algum
    lançamento que não grava isso), estima a partir do valor em R$ pelo
    preço atual da hora avulsa -- mesma lógica de `saldo_em_horas_medico`.
    """
    preco_h = preco_hora_avulsa()
    for t in transacoes:
        if (t.get("carteira") or "salas") != "salas":
            continue
        if t.get("quantidade_horas") is not None:
            horas = t["quantidade_horas"]
        elif preco_h > 0:
            horas = round(abs(t["valor"]) / preco_h, 1)
        else:
            horas = 0
        sinal = -1 if t["valor"] < 0 else 1
        t["horas_exibicao"] = sinal * horas
        t["saldo_apos_horas"] = int(t["saldo_apos"] // preco_h) if preco_h > 0 else 0
    return transacoes


def total_consumido_medico(medico_id: str) -> float:
    """Soma de tudo que o médico já gastou (valor absoluto), para calcular horas usadas."""
    resp = (
        get_client()
        .table("creditos_transacoes")
        .select("valor")
        .eq("medico_id", medico_id)
        .eq("tipo", "consumo")
        .execute()
    )
    return abs(sum(float(t["valor"]) for t in resp.data))


def _filtrar_por_mes_ano(transacoes: list[dict], mes: int | None, ano: int | None) -> list[dict]:
    if mes is None and ano is None:
        return transacoes
    filtradas = []
    for t in transacoes:
        data_str = t.get("criado_em", "")
        if not data_str:
            continue
        ano_t, mes_t = int(data_str[0:4]), int(data_str[5:7])
        if (mes is None or mes_t == mes) and (ano is None or ano_t == ano):
            filtradas.append(t)
    return filtradas


def horas_consumidas_medico(medico_id: str, mes: int | None = None, ano: int | None = None) -> int:
    """Soma EXATA de horas usadas (vem gravado em cada transação de consumo — não é estimativa)."""
    resp = (
        get_client()
        .table("creditos_transacoes")
        .select("quantidade_horas, criado_em")
        .eq("medico_id", medico_id)
        .eq("tipo", "consumo")
        .execute()
    )
    filtradas = _filtrar_por_mes_ano(resp.data, mes, ano)
    return sum(int(t["quantidade_horas"] or 0) for t in filtradas)


def valor_gasto_medico(medico_id: str, mes: int | None = None, ano: int | None = None) -> float:
    """Soma em R$ do que o médico comprou de créditos (não é o que ele gastou usando salas)."""
    resp = (
        get_client()
        .table("creditos_transacoes")
        .select("valor, criado_em")
        .eq("medico_id", medico_id)
        .eq("tipo", "compra")
        .execute()
    )
    filtradas = _filtrar_por_mes_ano(resp.data, mes, ano)
    return round(sum(float(t["valor"]) for t in filtradas), 2)


def horas_compradas_medico(medico_id: str, mes: int | None = None, ano: int | None = None) -> int:
    """
    Converte o total comprado em R$ para uma estimativa de horas, usando
    os preços ATUAIS (se os preços mudaram desde a compra, isso é uma
    aproximação — não dá pra saber exatamente quantas horas "valiam" o
    valor pago numa tabela de preços antiga).
    """
    valor = valor_gasto_medico(medico_id, mes, ano)
    return estimar_horas_compraveis(valor)


def saldo_em_horas_medico(medico_id: str) -> int:
    """Saldo atual do médico convertido em horas, usando os preços atuais."""
    return estimar_horas_compraveis(obter_saldo(medico_id))


# ---------- Pagamentos PIX ----------

def criar_registro_pagamento(medico_id: str, asaas_payment_id: str, asaas_customer_id: str,
                              valor: float, qr_code_base64: str, copia_e_cola: str,
                              valor_salas: float | None = None,
                              horas_pacote: int | None = None) -> dict:
    """`valor_salas`: quanto do total vira crédito de horas quando o
    Asaas confirmar o pagamento (ver webhooks_asaas.py). Se não for
    informado, assume que é o valor todo.

    `horas_pacote`: se a compra foi de um pacote fechado (ver
    listar_pacotes_horas), guarda quantas horas ele vale -- é o que
    permite creditar a quantidade EXATA de horas no webhook, em vez de
    estimar a partir do valor pago."""
    if valor_salas is None:
        valor_salas = valor
    resp = (
        get_client()
        .table("pagamentos_pix")
        .insert({
            "medico_id": medico_id,
            "asaas_payment_id": asaas_payment_id,
            "asaas_customer_id": asaas_customer_id,
            "valor": valor,
            "valor_salas": valor_salas,
            "status": "pendente",
            "forma_pagamento": "pix",
            "qr_code_base64": qr_code_base64,
            "copia_e_cola": copia_e_cola,
            "horas_pacote": horas_pacote,
        })
        .execute()
    )
    return resp.data[0]


def criar_registro_pagamento_cartao(medico_id: str, asaas_payment_id: str, asaas_customer_id: str,
                                     valor: float, invoice_url: str,
                                     valor_salas: float | None = None,
                                     horas_pacote: int | None = None, parcelas: int = 1) -> dict:
    if valor_salas is None:
        valor_salas = valor
    resp = (
        get_client()
        .table("pagamentos_pix")
        .insert({
            "medico_id": medico_id,
            "asaas_payment_id": asaas_payment_id,
            "asaas_customer_id": asaas_customer_id,
            "valor": valor,
            "valor_salas": valor_salas,
            "status": "pendente",
            "forma_pagamento": "cartao",
            "invoice_url": invoice_url,
            "horas_pacote": horas_pacote,
            "parcelas": parcelas,
        })
        .execute()
    )
    return resp.data[0]


def obter_pagamento_por_asaas_id(asaas_payment_id: str) -> dict | None:
    resp = (
        get_client()
        .table("pagamentos_pix")
        .select("*")
        .eq("asaas_payment_id", asaas_payment_id)
        .execute()
    )
    return resp.data[0] if resp.data else None


def obter_pagamento_por_id(pagamento_id: str) -> dict | None:
    resp = get_client().table("pagamentos_pix").select("*").eq("id", pagamento_id).execute()
    return resp.data[0] if resp.data else None


def marcar_pagamento_pago(pagamento_id: str) -> dict:
    resp = (
        get_client()
        .table("pagamentos_pix")
        .update({"status": "pago", "pago_em": agora_iso()})
        .eq("id", pagamento_id)
        .execute()
    )
    return resp.data[0]


def listar_pagamentos_pagos(limite: int = 100) -> list[dict]:
    """Para o dashboard admin: todos os pagamentos confirmados, com o nome do médico."""
    resp = (
        get_client()
        .table("pagamentos_pix")
        .select("*, medicos(nome, telefone, email)")
        .eq("status", "pago")
        .order("pago_em", desc=True)
        .limit(limite)
        .execute()
    )
    return resp.data


def listar_pagamentos_com_nota_medico(medico_id: str) -> list[dict]:
    """Para o painel do médico: só os pagamentos que já têm nota fiscal emitida/enviada."""
    resp = (
        get_client()
        .table("pagamentos_pix")
        .select("*")
        .eq("medico_id", medico_id)
        .neq("nota_fiscal_status", "nao_emitida")
        .order("nota_fiscal_emitida_em", desc=True)
        .execute()
    )
    return resp.data


def marcar_nota_fiscal_emitida(pagamento_id: str, numero: str, url: str) -> dict:
    resp = (
        get_client()
        .table("pagamentos_pix")
        .update({
            "nota_fiscal_status": "emitida",
            "nota_fiscal_numero": numero,
            "nota_fiscal_url": url,
            "nota_fiscal_emitida_em": agora_iso(),
        })
        .eq("id", pagamento_id)
        .execute()
    )
    return resp.data[0]


def marcar_nota_fiscal_enviada(pagamento_id: str) -> dict:
    resp = (
        get_client()
        .table("pagamentos_pix")
        .update({"nota_fiscal_status": "enviada", "nota_fiscal_enviada_em": agora_iso()})
        .eq("id", pagamento_id)
        .execute()
    )
    return resp.data[0]


# ---------- Consultas para o dashboard admin ----------

def listar_medicos_com_saldo(mes: int | None = None, ano: int | None = None) -> list[dict]:
    """Quadro de clientes do Dashboard Admin -- TODOS os médicos, cada um
    aparecendo aqui sozinho assim que se cadastra, sem nenhum passo
    manual. Cada linha já vem com os módulos que aquele médico usa
    marcados (m['google_calendar_conectado'], m['assistente_ativo']).

    IMPORTANTE (motivo do Dashboard ficar lento, resolvido em
    08/09/2026): antes, cada médico não-horista custava 5 idas separadas
    ao banco (uma consulta de rede por vez, esperando cada uma
    terminar pra começar a próxima) -- com 70+ médicos, isso virava
    300+ consultas sequenciais só pra montar essa tabela. Agora busca
    tudo de uma vez (3 consultas no TOTAL, não importa quantos médicos
    existam) e faz as contas por médico aqui em Python, sem bater no
    banco de novo pra cada um."""
    client = get_client()
    resp = (
        client
        .table("medicos")
        .select("id, nome, telefone, especialidade, saldo_creditos, ativo, assistente_ativo, "
                "tipo_vinculo, google_calendar_conectado, saldo_horas")
        .order("nome")
        .execute()
    )
    medicos = resp.data
    pacotes_atuais = listar_pacotes_horas()  # busca uma vez só (era buscado de novo a cada médico, mesmo problema)

    ids_medicos = [m["id"] for m in medicos]

    compras_por_medico: dict[str, list] = {}
    consumos_por_medico: dict[str, list] = {}
    medicos_com_pagamento: set = set()

    if ids_medicos:
        compras = (
            client.table("creditos_transacoes").select("medico_id, valor, quantidade_horas, criado_em")
            .in_("medico_id", ids_medicos).eq("tipo", "compra").execute().data
        )
        for c in compras:
            compras_por_medico.setdefault(c["medico_id"], []).append(c)

        consumos = (
            client.table("creditos_transacoes").select("medico_id, quantidade_horas, criado_em")
            .in_("medico_id", ids_medicos).eq("tipo", "consumo").execute().data
        )
        for c in consumos:
            consumos_por_medico.setdefault(c["medico_id"], []).append(c)

        pagos = (
            client.table("pagamentos_pix").select("medico_id")
            .in_("medico_id", ids_medicos).eq("status", "pago").execute().data
        )
        medicos_com_pagamento = {p["medico_id"] for p in pagos}

    for m in medicos:
        compras_filtradas = _filtrar_por_mes_ano(compras_por_medico.get(m["id"], []), mes, ano)
        consumos_filtrados = _filtrar_por_mes_ano(consumos_por_medico.get(m["id"], []), mes, ano)
        valor_gasto = round(sum(float(t["valor"]) for t in compras_filtradas), 2)

        # Desde 10/09/2026, compra de pacote fechado (ver
        # listar_pacotes_horas) grava a quantidade EXATA de horas na
        # própria transação -- soma essas direto (sem estimativa) e só
        # estima (pelo preço da hora avulsa) o que sobrar de compras
        # antigas/livres que não têm quantidade_horas gravada.
        horas_exatas = sum(int(t["quantidade_horas"]) for t in compras_filtradas if t.get("quantidade_horas"))
        valor_sem_horas_exatas = round(
            sum(float(t["valor"]) for t in compras_filtradas if not t.get("quantidade_horas")), 2
        )
        m["valor_gasto"] = valor_gasto
        m["horas_compradas"] = horas_exatas + estimar_horas_compraveis(valor_sem_horas_exatas, pacotes_atuais)
        m["horas_gastas"] = sum(int(t["quantidade_horas"] or 0) for t in consumos_filtrados)
        m["saldo_horas"] = estimar_horas_compraveis(float(m.get("saldo_creditos") or 0), pacotes_atuais)
        m["tem_pagamento"] = m["id"] in medicos_com_pagamento

    return medicos


def estatisticas_gerais(mes: int | None = None, ano: int | None = None) -> dict:
    client = get_client()

    compras = client.table("creditos_transacoes").select("valor, criado_em").eq("tipo", "compra").execute().data
    consumos = (
        client.table("creditos_transacoes")
        .select("valor, quantidade_horas, criado_em")
        .eq("tipo", "consumo")
        .execute()
        .data
    )
    medicos = (
        client.table("medicos").select("id, saldo_creditos").execute().data
    )

    compras_filtradas = _filtrar_por_mes_ano(compras, mes, ano)
    consumos_filtrados = _filtrar_por_mes_ano(consumos, mes, ano)
    pacotes_atuais = listar_pacotes_horas()  # busca uma vez só, não a cada médico no loop abaixo

    total_vendido = sum(float(t["valor"]) for t in compras_filtradas)
    horas_vendidas = estimar_horas_compraveis(total_vendido, pacotes_atuais)
    horas_consumidas = sum(int(t["quantidade_horas"] or 0) for t in consumos_filtrados)
    saldo_horas_total = sum(
        estimar_horas_compraveis(float(m["saldo_creditos"]), pacotes_atuais) for m in medicos
    )

    return {
        "total_vendido": round(total_vendido, 2),
        "horas_vendidas": horas_vendidas,
        "horas_consumidas": horas_consumidas,
        "saldo_horas_total": saldo_horas_total,
        "numero_medicos": len(medicos),
    }


# `estimar_horas_compraveis` tem um teto padrão de 60h (limite=60) -- faz
# sentido lá porque é usado pra mostrar "quanto EU tenho pra gastar" no
# painel de um médico só. Nas contas agregadas do admin (estatisticas_horas
# abaixo) é o oposto: é uma SOMA de todo mundo, então um teto por-médico
# corromperia o total (achado testando: com 1 médico com +900h de saldo, a
# praça inteira aparecia como 75h em vez de milhares). `limite=SEM_TETO` na
# prática remove o teto só pras contas agregadas.
SEM_TETO = 10**9


# Início da contagem de horas vendidas/utilizadas na tela Admin > Horas (uso "para valer": 22/10/2026, primeiro dia com agendamentos liberados). Pode ser mudado pela variável HORAS_INICIO_CONTAGEM (AAAA-MM-DD) no Render.
DATA_INICIO_CONTAGEM_HORAS = os.getenv("HORAS_INICIO_CONTAGEM") or "2026-10-22"


def _a_partir_do_inicio_da_contagem(transacoes: list[dict]) -> list[dict]:
    return [t for t in transacoes if (t.get("criado_em") or "")[:10] >= DATA_INICIO_CONTAGEM_HORAS]


def _somar_vendidas_e_utilizadas(compras: list[dict], consumos: list[dict], pacotes_atuais: list[dict],
                                 reembolsos: list[dict] | None = None) -> tuple[int, int]:
    """Soma horas_vendidas/horas_utilizadas para uma lista de transações já
    filtrada (ou não) por mês/ano -- extraído de estatisticas_horas pra
    poder calcular o mesmo par de números duas vezes (mês escolhido e
    acumulado geral) sem duplicar a lógica."""
    # Soma a quantidade EXATA de horas já gravada em cada compra (todo
    # pacote fechado grava isso desde 10/09/2026); só estima (pelo valor
    # em R$, no preço vigente) o que não tiver isso gravado -- compras
    # bem antigas, de antes desse campo existir.
    horas_exatas = sum(int(t["quantidade_horas"]) for t in compras if t.get("quantidade_horas"))
    valor_sem_horas_exatas = round(
        sum(float(t["valor"]) for t in compras if not t.get("quantidade_horas")), 2
    )
    horas_vendidas = horas_exatas + estimar_horas_compraveis(valor_sem_horas_exatas, pacotes_atuais, limite=SEM_TETO)
    horas_utilizadas = sum(int(t["quantidade_horas"] or 0) for t in consumos)
    # Reembolso de cancelamento (26/10/2026): as horas devolvidas ao médico
    # deixam de contar como utilizadas (descontadas no mês em que o reembolso
    # foi feito). Sem isso o cancelamento devolvia o saldo mas o "utilizadas"
    # continuava alto.
    horas_utilizadas -= sum(int(t.get("quantidade_horas") or 0) for t in (reembolsos or []))
    horas_utilizadas = max(horas_utilizadas, 0)
    return horas_vendidas, horas_utilizadas


def estatisticas_horas(mes: int | None = None, ano: int | None = None) -> dict:
    """Painel "Horas" do admin (pedido do Paulo em 10/09/2026, baseado
    numa tela parecida que já existia no sistema maior original) -- só da
    carteira de Salas/Horas (a de IA não entra aqui, ela é medida em R$ e
    tem seu próprio jeito de olhar consumo):

    - horas_vendidas / horas_utilizadas: soma de TODOS os médicos,
      filtrada pro mês/ano escolhido -- só transações tipo 'compra'
      (pacote comprado de verdade via Asaas) e 'consumo' (reserva paga
      com o saldo) entram aqui; ajuste manual do admin e transferência
      entre carteiras (ambos tipo='ajuste') ficam de fora de propósito,
      não são "venda" nem "uso" de verdade.
    - horas_vendidas_total / horas_utilizadas_total: os MESMOS dois
      números acima, mas acumulados desde sempre (sem filtro de mês) --
      pedido do Paulo em 10/09/2026, pra ver o total histórico junto do
      recorte do mês, sem precisar ficar trocando o filtro mês a mês.
    - horas_na_praca_mes: saldo LÍQUIDO gerado dentro do mês/ano filtrado
      (horas_vendidas do mês menos horas_utilizadas do mês) -- pedido do
      Paulo em 10/09/2026, pra ver se a praça de horas cresceu ou
      encolheu naquele mês especificamente.
    - horas_na_praca_total: soma do saldo ATUAL (em horas) de todos os
      médicos -- não é filtrada por mês/ano, é uma fotografia de agora
      (quanto já foi comprado e ainda não foi usado, desde sempre)."""
    client = get_client()
    compras = (
        client.table("creditos_transacoes")
        .select("valor, quantidade_horas, criado_em")
        .eq("tipo", "compra").eq("carteira", "salas")
        .execute().data
    )
    consumos = (
        client.table("creditos_transacoes")
        .select("quantidade_horas, criado_em")
        .eq("tipo", "consumo").eq("carteira", "salas")
        .execute().data
    )
    # reembolsos de cancelamento são gravados como tipo='ajuste' ligados a uma reserva
    # (ver reserva_service._cancelar...): entram aqui pra abater das horas utilizadas.
    reembolsos = (
        client.table("creditos_transacoes")
        .select("quantidade_horas, criado_em")
        .eq("tipo", "ajuste").eq("carteira", "salas")
        .ilike("descricao", "Reembolso por cancelamento%")
        .execute().data
    )
    medicos = (
        client.table("medicos").select("id, saldo_creditos")
        .execute().data
    )

    # Contagem "zerada" (pedido do Paulo em 22/10/2026): só entram vendas/uso a partir da data de início
    # do uso real do sistema; o saldo ("horas na praça") continua sendo o saldo real de hoje.
    compras = _a_partir_do_inicio_da_contagem(compras)
    consumos = _a_partir_do_inicio_da_contagem(consumos)
    reembolsos = _a_partir_do_inicio_da_contagem(reembolsos)
    compras_filtradas = _filtrar_por_mes_ano(compras, mes, ano)
    consumos_filtrados = _filtrar_por_mes_ano(consumos, mes, ano)
    reembolsos_filtrados = _filtrar_por_mes_ano(reembolsos, mes, ano)
    pacotes_atuais = listar_pacotes_horas()

    horas_vendidas, horas_utilizadas = _somar_vendidas_e_utilizadas(compras_filtradas, consumos_filtrados, pacotes_atuais, reembolsos_filtrados)
    # acumulado geral = mesma conta, mas com as listas SEM filtro de mês/ano
    horas_vendidas_total, horas_utilizadas_total = _somar_vendidas_e_utilizadas(compras, consumos, pacotes_atuais, reembolsos)

    horas_na_praca_total = sum(
        estimar_horas_compraveis(float(m.get("saldo_creditos") or 0), pacotes_atuais, limite=SEM_TETO)
        for m in medicos
    )
    horas_na_praca_mes = horas_vendidas - horas_utilizadas

    return {
        "horas_vendidas": horas_vendidas,
        "horas_utilizadas": horas_utilizadas,
        "horas_vendidas_total": horas_vendidas_total,
        "horas_utilizadas_total": horas_utilizadas_total,
        "horas_na_praca_mes": horas_na_praca_mes,
        "horas_na_praca_total": horas_na_praca_total,
    }


def horas_na_praca_por_mes(ano: int) -> list[dict]:
    """"Saldo de horas mensal" (Admin > Horas, 26/10/2026): para cada mês do
    ano, a mesma conta de "Horas na praça (total)" -- soma das horas
    compráveis com o saldo de todos os médicos -- mas como estava no FIM
    daquele mês. O saldo do fim do mês é reconstruído a partir do saldo
    de hoje, desfazendo as transações (compras, consumos, reembolsos e
    ajustes) feitas depois dele. Mês futuro devolve horas=None; o mês atual
    bate exatamente com o "Horas na praça (total)" da tela."""
    from datetime import datetime, timedelta
    agora = datetime.utcnow() - timedelta(hours=3)
    client = get_client()
    medicos = client.table("medicos").select("id, saldo_creditos").execute().data or []
    transacoes = (
        client.table("creditos_transacoes").select("medico_id, valor, criado_em")
        .eq("carteira", "salas").execute().data or []
    )
    por_medico: dict = {}
    for t in transacoes:
        ym = str(t.get("criado_em") or "")[:7]
        if len(ym) != 7:
            continue
        chave = int(ym[:4]) * 12 + int(ym[5:7]) - 1
        d = por_medico.setdefault(str(t["medico_id"]), {})
        d[chave] = d.get(chave, 0.0) + float(t.get("valor") or 0)
    pacotes = listar_pacotes_horas()
    resultado = []
    for mes in range(1, 13):
        if (ano, mes) > (agora.year, agora.month):
            resultado.append({"mes": mes, "horas": None})
            continue
        fim = ano * 12 + mes - 1
        total = 0
        for m in medicos:
            depois = sum(v for k, v in por_medico.get(str(m["id"]), {}).items() if k > fim)
            saldo_fim = float(m.get("saldo_creditos") or 0) - depois
            total += estimar_horas_compraveis(max(saldo_fim, 0.0), pacotes, limite=SEM_TETO)
        resultado.append({"mes": mes, "horas": total})
    return resultado


def marcar_alerta_saldo_baixo_enviado(medico_id: str):
    get_client().table("medicos").update({"alerta_saldo_baixo_enviado": True}).eq("id", medico_id).execute()


def medico_tem_pagamento_confirmado(medico_id: str) -> bool:
    """True se o médico já teve ao menos 1 pagamento com status 'pago' — é o
    requisito para o admin poder ligar o assistente de WhatsApp dele."""
    resp = (
        get_client()
        .table("pagamentos_pix")
        .select("id")
        .eq("medico_id", medico_id)
        .eq("status", "pago")
        .limit(1)
        .execute()
    )
    return len(resp.data) > 0


def ativar_assistente(medico_id: str) -> dict:
    """
    Ativa o assistente de WhatsApp do médico. Retorna o estado anterior
    (já estava ativo?) para quem chamar decidir se manda a mensagem de
    boas-vindas (só faz sentido na primeira ativação).
    """
    client = get_client()
    atual = client.table("medicos").select("assistente_ativo").eq("id", medico_id).execute().data
    ja_estava_ativo = bool(atual[0]["assistente_ativo"]) if atual else False

    client.table("medicos").update({"assistente_ativo": True}).eq("id", medico_id).execute()
    return {"ja_estava_ativo": ja_estava_ativo}


def atualizar_cpf_cnpj(medico_id: str, cpf_cnpj: str) -> dict:
    resp = get_client().table("medicos").update({"cpf_cnpj": cpf_cnpj}).eq("id", medico_id).execute()
    return resp.data[0]


def atualizar_crm(medico_id: str, crm: str) -> dict:
    resp = get_client().table("medicos").update({"crm": crm}).eq("id", medico_id).execute()
    return resp.data[0]


_CAMPOS_DADOS_PESSOAIS = (
    "nome", "telefone", "email", "cpf_cnpj", "crm", "especialidade",
    "data_nascimento",
    "endereco_cep", "endereco_rua", "endereco_numero", "endereco_complemento",
    "endereco_bairro", "endereco_cidade", "endereco_estado",
    "valor_consulta", "tempo_consulta", "convenios", "formas_pagamento",
    "politica_cancelamento", "retorno_particular", "retorno_convenio",
    "idade_minima", "observacoes_atendimento",
)


def atualizar_dados_pessoais(medico_id: str, dados: dict) -> dict:
    """Salva a tela "Dados Pessoais" inteira de uma vez (um único botão
    Salvar, não um por campo) -- os campos de negócio (valor da
    consulta, convênios, formas de pagamento etc.) são os mesmos que
    vêm da planilha de 74 médicos (ver
    planilha_medicos_service.sincronizar_dados_planilha_com_medicos),
    só que agora o próprio médico pode editar depois."""
    payload = {campo: dados[campo] for campo in _CAMPOS_DADOS_PESSOAIS if campo in dados}
    if not payload:
        raise ValueError("Nenhum dado pra salvar.")
    if "telefone" in payload:
        from app.services.telefone_utils import normalizar_telefone
        # a tela mostra e recebe o telefone SEM o "55" (pedido do Paulo)
        # -- aqui é onde ele volta a ganhar o "55" antes de ir pro banco,
        # senão o WhatsApp para de reconhecer esse médico
        telefone_normalizado = normalizar_telefone(payload["telefone"])
        if not telefone_normalizado or len(telefone_normalizado) not in (12, 13):
            raise ValueError("Telefone inválido -- inclua o DDD.")
        payload["telefone"] = telefone_normalizado
        # telefone é ÚNICO no banco: se já pertence a OUTRO cliente, avisa com
        # clareza em vez de estourar "erro interno" (cliente novo que digita o
        # telefone de um cadastro antigo da migração, 26/10/2026).
        outros = (get_client().table("medicos").select("id").eq("telefone", telefone_normalizado).execute().data or [])
        if any(str(o["id"]) != str(medico_id) for o in outros):
            raise ValueError("Este telefone já está cadastrado em outro acesso. Se você já era cliente da Lifemax, "
                             "entre pelo seu acesso anterior; se precisar de ajuda, fale com a Lifemax pelos canais de atendimento.")
    if "cpf_cnpj" in payload and payload["cpf_cnpj"]:
        apenas_digitos = "".join(c for c in payload["cpf_cnpj"] if c.isdigit())
        if len(apenas_digitos) not in (11, 14):
            raise ValueError("CPF deve ter 11 dígitos ou CNPJ 14 dígitos.")
    if "data_nascimento" in payload and not payload["data_nascimento"]:
        # campo <input type="date"> manda "" quando fica vazio -- a coluna
        # é do tipo date no banco, então "" precisa virar None (senão dá
        # erro de sintaxe no Postgres).
        payload["data_nascimento"] = None
    try:
        resp = get_client().table("medicos").update(payload).eq("id", medico_id).execute()
    except Exception as e:
        # erros do banco viram mensagem amigável (e ficam no log do servidor)
        print(f"[dados_pessoais] erro ao salvar médico {medico_id}: {type(e).__name__}: {e}")
        codigo = getattr(e, "pgcode", None)
        if codigo == "23505":
            raise ValueError("Algum dado informado (telefone ou e-mail) já está cadastrado em outro acesso.")
        if codigo == "23502":
            raise ValueError("Preencha todos os campos obrigatórios (nome e telefone) antes de salvar.")
        if codigo in ("22P02", "22007", "22008", "22003", "22001"):
            raise ValueError("Algum campo está com formato inválido. Confira os dados (datas, números e tamanhos) e tente de novo.")
        if codigo == "42703":
            raise ValueError("O sistema ainda não está atualizado para salvar um dos campos (falta uma atualização do banco). "
                             "Avise a Lifemax.")
        raise ValueError(f"Não foi possível salvar agora. Tente de novo; se continuar, avise a Lifemax (código {codigo or 'interno'}).")
    if not resp.data:
        raise ValueError("Cadastro não encontrado. Saia e entre novamente.")
    return resp.data[0]
