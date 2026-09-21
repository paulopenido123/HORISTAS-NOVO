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
    (reserva_service.enviar_email_agendamento_paciente). Editável em
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


def obter_saldo_ia(medico_id: str) -> float:
    """Se a migração que criou a coluna saldo_ia ainda não rodou no banco
    (ex: código já foi publicado, mas a migração SQL ainda não), devolve
    0 em vez de quebrar a tela inteira do médico -- roda
    sql/migration_saldo_ia_separado.sql pra isso funcionar de verdade."""
    try:
        resp = get_client().table("medicos").select("saldo_ia").eq("id", medico_id).execute()
        return float(resp.data[0]["saldo_ia"]) if resp.data else 0.0
    except Exception as e:
        print(f"[creditos_service] saldo_ia indisponível (rode a migração?): {e}")
        return 0.0


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
    categoria: 'horas' (padrão, reserva de consultório) ou 'ia' (uso do
    assistente de IA) — usado nos relatórios.

    `carteira`: 'salas' (padrão, mexe em saldo_creditos) ou 'ia' (mexe
    em saldo_ia) -- desde a divisão pedida pelo Paulo em 08/09/2026,
    são DUAS carteiras de verdade, cada uma com seu próprio saldo e seu
    próprio alerta de saldo baixo (antes era um saldo só).
    """
    if carteira not in ("salas", "ia"):
        raise ValueError(f"Carteira inválida: {carteira}")

    campo_saldo = "saldo_creditos" if carteira == "salas" else "saldo_ia"
    campo_alerta = "alerta_saldo_baixo_enviado" if carteira == "salas" else "alerta_saldo_ia_baixo_enviado"
    obter = obter_saldo if carteira == "salas" else obter_saldo_ia

    client = get_client()
    saldo_atual = obter(medico_id)
    novo_saldo = round(saldo_atual + valor, 2)

    update_medico = {campo_saldo: novo_saldo}
    if valor > 0:
        # sempre que o saldo sobe (compra ou ajuste positivo), destrava o
        # alerta de saldo baixo DESSA carteira, pra poder ser enviado de
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
                                 quantidade_horas: int, criado_por_admin: bool = False) -> dict:
    """Debita o valor de uma reserva. Levanta ValueError se saldo insuficiente.

    `criado_por_admin` -- pedido do Paulo em 21/09/2026 (botão "Agendar
    para:" da Agenda Horistas): só muda a descrição da transação no
    extrato do médico, pra ficar claro que foi o admin quem agendou --
    o débito em si é idêntico ao de uma reserva feita pelo próprio
    médico."""
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
    Transações da carteira 'ia' não são mexidas, continuam em R$."""
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


# ---------- Transferência entre carteiras (salas <-> IA) ----------

def transferir_saldo(medico_id: str, origem: str, valor: float) -> dict:
    """Move `valor` (em R$) de uma carteira do médico pra outra --
    'salas' (saldo_creditos, só serve pra reservar consultório) <->
    'ia' (saldo_ia, só serve pros módulos de assistente de IA).
    Pedido do Paulo em 10/09/2026: o médico pode preferir mover saldo
    de uma conta pra outra em vez de pagar de novo via Asaas.

    Registrado como DUAS transações tipo='ajuste' (uma negativa na
    origem, uma positiva no destino, mesmo pagamento_id=None) -- mantém
    o extrato de cada carteira auditável, igual a qualquer outro
    movimento de saldo."""
    if origem not in ("salas", "ia"):
        raise ValueError("Carteira de origem inválida.")
    destino = "ia" if origem == "salas" else "salas"

    if valor <= 0:
        raise ValueError("O valor da transferência precisa ser maior que zero.")

    saldo_origem = obter_saldo(medico_id) if origem == "salas" else obter_saldo_ia(medico_id)
    if round(valor, 2) > round(saldo_origem, 2):
        raise ValueError(f"Saldo insuficiente na carteira de origem (você tem R$ {saldo_origem:.2f}).")

    nome_origem = "IA" if origem == "ia" else "horas/salas"
    nome_destino = "IA" if destino == "ia" else "horas/salas"

    # A perna que toca a carteira 'salas' grava quantidade_horas (mesmo
    # preço da hora avulsa usado em todo o resto do sistema) -- pedido do
    # Paulo em 10/09/2026: a carteira de Salas/Horas é medida em horas em
    # qualquer lugar, inclusive no extrato de uma transferência, nunca só
    # em R$ (ver enriquecer_transacoes_com_horas, que também cobre o caso
    # de uma transferência antiga sem isso gravado).
    preco_h = preco_hora_avulsa()
    horas_equivalentes = round(valor / preco_h, 1) if preco_h > 0 else None

    registrar_transacao(
        medico_id, tipo="ajuste", valor=-valor,
        descricao=f"Transferência de saldo para a carteira de {nome_destino}",
        carteira=origem,
        quantidade_horas=horas_equivalentes if origem == "salas" else None,
    )
    resultado = registrar_transacao(
        medico_id, tipo="ajuste", valor=valor,
        descricao=f"Transferência de saldo vinda da carteira de {nome_origem}",
        carteira=destino,
        quantidade_horas=horas_equivalentes if destino == "salas" else None,
    )
    return resultado


# ---------- Pagamentos PIX ----------

def criar_registro_pagamento(medico_id: str, asaas_payment_id: str, asaas_customer_id: str,
                              valor: float, qr_code_base64: str, copia_e_cola: str,
                              valor_salas: float | None = None, valor_ia: float = 0.0,
                              horas_pacote: int | None = None) -> dict:
    """`valor_salas`/`valor_ia`: quanto do total é pra cada carteira --
    o webhook usa isso pra saber como dividir o crédito quando o Asaas
    confirmar o pagamento (ver webhooks_asaas.py). Se `valor_salas` não
    for informado, assume que é tudo pra salas (comportamento de
    sempre, antes da divisão de carteiras).

    `horas_pacote`: se a compra foi de um pacote fechado (ver
    listar_pacotes_horas), guarda quantas horas ele vale -- é o que
    permite creditar a quantidade EXATA de horas no webhook, em vez de
    estimar a partir do valor pago."""
    if valor_salas is None:
        valor_salas = valor - valor_ia
    resp = (
        get_client()
        .table("pagamentos_pix")
        .insert({
            "medico_id": medico_id,
            "asaas_payment_id": asaas_payment_id,
            "asaas_customer_id": asaas_customer_id,
            "valor": valor,
            "valor_salas": valor_salas,
            "valor_ia": valor_ia,
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
                                     valor_salas: float | None = None, valor_ia: float = 0.0,
                                     horas_pacote: int | None = None, parcelas: int = 1) -> dict:
    if valor_salas is None:
        valor_salas = valor - valor_ia
    resp = (
        get_client()
        .table("pagamentos_pix")
        .insert({
            "medico_id": medico_id,
            "asaas_payment_id": asaas_payment_id,
            "asaas_customer_id": asaas_customer_id,
            "valor": valor,
            "valor_salas": valor_salas,
            "valor_ia": valor_ia,
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


def _modulos_ia_ativados_por_medico() -> dict:
    """P/ o quadro de clientes do Dashboard Admin: quais módulos de IA
    (secretaria/prontuario/financeiro) cada médico já ativou pelo menos
    uma vez -- existe uma linha em medico_modulos_ia = já usou de
    verdade (ver app/services/ia_uso_service.py, que é quem cria essa
    linha no primeiro uso). 1 consulta só pra todo mundo, não por
    médico, pra não multiplicar o tempo de carregamento da tela."""
    resp = get_client().table("medico_modulos_ia").select("medico_id, modulo_slug").execute()
    resultado: dict = {}
    for linha in resp.data:
        resultado.setdefault(linha["medico_id"], set()).add(linha["modulo_slug"])
    return resultado


# ---------- Consultas para o dashboard admin ----------

def listar_medicos_com_saldo(mes: int | None = None, ano: int | None = None) -> list[dict]:
    """Quadro de clientes do Dashboard Admin -- TODOS os médicos (avulso,
    fixo e horista), cada um aparecendo aqui sozinho assim que se
    cadastra, sem nenhum passo manual. Cada linha já vem com os módulos
    que aquele médico usa marcados (m['modulos_ia'], m['google_calendar_conectado'],
    m['assistente_ativo'], m['tipo_vinculo']), pra tela desenhar as colunas
    de módulo automaticamente.

    Pros horistas, pula de propósito as contas de crédito em R$/PIX
    (valor_gasto, horas_compradas, horas_gastas, tem_pagamento ficam
    None) -- eles usam saldo_horas (Módulo 1: crédito de horas), não
    créditos_transacoes/pagamentos_pix, então essas contas sempre dariam
    zero/vazio pra eles.

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
    modulos_ia_por_medico = _modulos_ia_ativados_por_medico()
    pacotes_atuais = listar_pacotes_horas()  # busca uma vez só (era buscado de novo a cada médico, mesmo problema)

    ids_nao_horistas = [m["id"] for m in medicos if m.get("tipo_vinculo") != "horista"]

    compras_por_medico: dict[str, list] = {}
    consumos_por_medico: dict[str, list] = {}
    medicos_com_pagamento: set = set()

    if ids_nao_horistas:
        compras = (
            client.table("creditos_transacoes").select("medico_id, valor, quantidade_horas, criado_em")
            .in_("medico_id", ids_nao_horistas).eq("tipo", "compra").execute().data
        )
        for c in compras:
            compras_por_medico.setdefault(c["medico_id"], []).append(c)

        consumos = (
            client.table("creditos_transacoes").select("medico_id, quantidade_horas, criado_em")
            .in_("medico_id", ids_nao_horistas).eq("tipo", "consumo").execute().data
        )
        for c in consumos:
            consumos_por_medico.setdefault(c["medico_id"], []).append(c)

        pagos = (
            client.table("pagamentos_pix").select("medico_id")
            .in_("medico_id", ids_nao_horistas).eq("status", "pago").execute().data
        )
        medicos_com_pagamento = {p["medico_id"] for p in pagos}

    for m in medicos:
        if m.get("tipo_vinculo") == "horista":
            m["valor_gasto"] = None
            m["horas_compradas"] = None
            m["horas_gastas"] = None
            m["tem_pagamento"] = False
            # m["saldo_horas"] já veio certo direto da consulta acima
            # (é o saldo de horas de verdade do horista, Módulo 1)
        else:
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
        m["modulos_ia"] = modulos_ia_por_medico.get(m["id"], set())

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
        client.table("medicos").select("id, saldo_creditos").neq("tipo_vinculo", "horista").execute().data
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


def _somar_vendidas_e_utilizadas(compras: list[dict], consumos: list[dict], pacotes_atuais: list[dict]) -> tuple[int, int]:
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
    medicos = (
        client.table("medicos").select("id, saldo_creditos, tipo_vinculo")
        .neq("tipo_vinculo", "horista")  # horista usa outro mecanismo de crédito de horas, não essa carteira
        .execute().data
    )

    compras_filtradas = _filtrar_por_mes_ano(compras, mes, ano)
    consumos_filtrados = _filtrar_por_mes_ano(consumos, mes, ano)
    pacotes_atuais = listar_pacotes_horas()

    horas_vendidas, horas_utilizadas = _somar_vendidas_e_utilizadas(compras_filtradas, consumos_filtrados, pacotes_atuais)
    # acumulado geral = mesma conta, mas com as listas SEM filtro de mês/ano
    horas_vendidas_total, horas_utilizadas_total = _somar_vendidas_e_utilizadas(compras, consumos, pacotes_atuais)

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


def marcar_alerta_saldo_baixo_enviado(medico_id: str, carteira: str = "salas"):
    campo = "alerta_saldo_baixo_enviado" if carteira == "salas" else "alerta_saldo_ia_baixo_enviado"
    get_client().table("medicos").update({campo: True}).eq("id", medico_id).execute()


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
        from app.services.agenda_fixos_service import normalizar_telefone
        # a tela mostra e recebe o telefone SEM o "55" (pedido do Paulo)
        # -- aqui é onde ele volta a ganhar o "55" antes de ir pro banco,
        # senão o WhatsApp para de reconhecer esse médico
        telefone_normalizado = normalizar_telefone(payload["telefone"])
        if not telefone_normalizado or len(telefone_normalizado) not in (12, 13):
            raise ValueError("Telefone inválido -- inclua o DDD.")
        payload["telefone"] = telefone_normalizado
    if "cpf_cnpj" in payload and payload["cpf_cnpj"]:
        apenas_digitos = "".join(c for c in payload["cpf_cnpj"] if c.isdigit())
        if len(apenas_digitos) not in (11, 14):
            raise ValueError("CPF deve ter 11 dígitos ou CNPJ 14 dígitos.")
    resp = get_client().table("medicos").update(payload).eq("id", medico_id).execute()
    return resp.data[0]
