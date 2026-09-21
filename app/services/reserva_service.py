"""
Lógica central de reserva de consultório — turno (fixo) ou hora avulsa.

Centralizado aqui porque tanto a Grade de Turnos (web) quanto o
assistente de WhatsApp precisam se comportar EXATAMENTE igual: mesma
checagem de saldo, mesmo débito de crédito, mesmo aviso de saldo baixo.
Ter essa lógica duplicada em dois lugares é como bugs de inconsistência
acontecem — por isso os dois canais chamam as mesmas funções abaixo.
"""
from datetime import datetime, timedelta
import threading

from app.services import supabase_client as db
from app.services import creditos_service as creditos_db
from app.services import email_service
from app.services import notificacao_saldo


def _rodar_em_segundo_plano(fn, *args, **kwargs):
    """Roda `fn` numa thread separada, sem travar a resposta pro médico --
    pedido do Paulo em 15/09/2026: reclamou que clicar em "Reservar" e
    depois na célula demorava muito pra responder. O gargalo real não
    era a grade (isso já foi resolvido no frontend, que agora atualiza a
    tela na hora sem recarregar tudo de novo) -- era esperar o envio dos
    e-mails de notificação (recepção + médico) e a checagem/criação de
    evento no Google Agenda ANTES de devolver a resposta HTTP. Essas
    ações continuam acontecendo normalmente, só que em background."""
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


# Janela mínima de aviso para cancelamento com reembolso -- pedido do
# Paulo em 10/09/2026: cancelar com MENOS de 12h de antecedência da
# data/hora da reserva ainda é permitido, mas não devolve as horas.
HORAS_MINIMAS_PARA_REEMBOLSO = 12


class SaldoInsuficienteError(Exception):
    """Mensagem em HORAS (não mais em R$) desde 10/09/2026, pedido do
    Paulo -- o médico compra e enxerga tudo em horas, então o aviso de
    bloqueio também precisa falar a mesma língua, com uma chamada clara
    pra ação ("compre mais horas") em vez de só reportar um valor em R$
    que ele nunca digitou."""
    def __init__(self, saldo_atual: float, preco: float, horas_disponiveis: int, horas_necessarias: int):
        self.saldo_atual = saldo_atual
        self.preco = preco
        self.horas_disponiveis = horas_disponiveis
        self.horas_necessarias = horas_necessarias
        super().__init__(
            f"Saldo insuficiente: você tem {horas_disponiveis}h disponíveis e essa reserva "
            f"precisa de {horas_necessarias}h. Compre mais horas para continuar."
        )


class ConflitoDeReservaError(Exception):
    pass


class NaoAutorizadoError(Exception):
    """Médico se cadastrou sozinho (auto-cadastro em /primeiro-acesso) mas
    o admin ainda não liberou o acesso dele -- pedido do Paulo em
    10/09/2026 (mandou print da tela do sistema maior original com o
    toggle "Usuário autorizado no sistema"). Ele consegue logar e comprar
    horas normalmente, só fica bloqueado de RESERVAR consultório até a
    liberação manual em /admin/clientes (coluna medicos.autorizado)."""
    def __init__(self):
        super().__init__(
            "Seu cadastro ainda está aguardando liberação do administrador. "
            "Você poderá reservar consultórios assim que seu acesso for autorizado."
        )


class MedicoFixoNaoPodeAlugarError(Exception):
    """Médico mensalista/turno (tipo_vinculo='fixo') já tem consultório fixo
    garantido pela grade -- não faz sentido (e não deixamos) ele também
    alugar consultório avulso por hora/turno aqui. O seletor da tela de
    turnos já filtra esses médicos fora, mas checamos de novo aqui como
    defesa em profundidade (a rota da API pode ser chamada direto).

    Também bloqueia tipo_vinculo='horista': esse é um tipo de médico
    DIFERENTE do avulso -- não paga em R$/PIX aqui, tem saldo próprio em
    HORAS (medicos.saldo_horas) creditado manualmente pela recepção, e
    agenda pacientes através da recepção (matriz_liberacao +
    agenda_consultas), num fluxo que não faz parte deste pacote. Sem essa
    checagem, um horista real que fizesse login nesta tela veria um saldo
    em R$ (saldo_creditos) que não é o dele e poderia ser levado a
    "comprar" créditos via PIX que seu fluxo real nunca usa -- o saldo de
    horas de verdade dele nunca seria tocado por essa reserva."""
    def __init__(self, tipo_vinculo: str = "fixo"):
        if tipo_vinculo == "horista":
            super().__init__(
                "Médicos horistas usam saldo de horas próprio, administrado pela recepção, "
                "e não alugam consultório avulso por essa tela."
            )
        else:
            super().__init__(
                "Médicos mensalistas/turno já têm consultório fixo e não podem "
                "alugar consultório avulso por essa tela."
            )


def _checar_data_nao_passada(data: str, hora_inicio: str | None = None):
    """Trava reserva de consultório numa data (ou horário, quando for por
    hora) que já passou -- pedido do Paulo em 11/09/2026: se o cliente
    escolher por engano uma data/horário do passado (a grade continua
    mostrando semanas anteriores pra consulta), a reserva não pode ir
    pra frente -- levanta ValueError, que a rota devolve como aviso pro
    médico em vez de criar a reserva.

    Mesmo fuso fixo de Brasília (-03:00) usado no resto deste arquivo (o
    sistema não guarda fuso por médico -- ver _para_iso_com_fuso)."""
    agora = datetime.utcnow() - timedelta(hours=3)
    try:
        limite = datetime.strptime(data, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("Data inválida.")
    if hora_inicio:
        try:
            hora_dt = datetime.strptime(hora_inicio, "%H:%M")
            limite = limite.replace(hour=hora_dt.hour, minute=hora_dt.minute)
        except ValueError:
            limite = limite.replace(hour=23, minute=59)
    else:
        limite = limite.replace(hour=23, minute=59)
    if limite < agora:
        raise ValueError("Não é possível reservar uma data/horário que já passou. Escolha um horário futuro.")


def _checar_pode_alugar_avulso(medico_id: str):
    medico = db.get_medico_by_id(medico_id)
    if medico and not medico.get("autorizado", True):
        raise NaoAutorizadoError()
    if medico and medico.get("tipo_vinculo") in ("fixo", "horista"):
        raise MedicoFixoNaoPodeAlugarError(medico.get("tipo_vinculo"))


def reservar_turno(medico_id: str, consultorio_id: str, data: str, periodo: str) -> dict:
    from app.services import template_service
    from app.services import google_calendar_service as gcal

    _checar_pode_alugar_avulso(medico_id)
    _checar_data_nao_passada(data, db.PERIODOS_HORARIOS[periodo][0])

    horarios_do_turno = template_service.HORARIOS_POR_PERIODO[periodo]
    if not template_service.verificar_disponibilidade(consultorio_id, data, horarios_do_turno):
        raise ConflitoDeReservaError(
            "Esse turno não está disponível para reserva nesse dia da semana "
            "(um ou mais horários estão bloqueados na Semana Padrão pelo administrador)."
        )

    # preço do turno = preço da hora avulsa (ver creditos_db.preco_hora_avulsa,
    # baseado em pacotes_horas) vezes a quantidade de horas que esse
    # período cobre -- desde 10/09/2026 não existe mais um preco_turno
    # fixo separado, é sempre derivado do mesmo preço-base de hora avulsa.
    preco = creditos_db.calcular_preco_horas(len(horarios_do_turno))

    saldo_atual = creditos_db.obter_saldo(medico_id)
    if saldo_atual < preco:
        raise SaldoInsuficienteError(
            saldo_atual, preco,
            horas_disponiveis=creditos_db.estimar_horas_compraveis(saldo_atual),
            horas_necessarias=len(horarios_do_turno),
        )

    hora_inicio_periodo, hora_fim_periodo = db.PERIODOS_HORARIOS[periodo]
    medico = db.get_medico_by_id(medico_id)
    _checar_conflito_google(medico, data, hora_inicio_periodo, hora_fim_periodo)

    try:
        reserva = db.criar_reserva(consultorio_id, medico_id, data, periodo)
    except Exception:
        raise ConflitoDeReservaError("Esse turno já foi reservado por outra pessoa. Atualize a página.")

    resultado = creditos_db.debitar_credito_por_reserva(
        medico_id, preco, reserva["id"], quantidade_horas=len(horarios_do_turno)
    )
    _rodar_em_segundo_plano(_finalizar_pos_reserva, medico, consultorio_id, reserva,
                             data, hora_inicio_periodo, hora_fim_periodo, medico_id)
    return {"reserva": reserva, "preco": preco, "saldo_atual": resultado["saldo_novo"],
            "saldo_horas": creditos_db.saldo_em_horas_medico(medico_id)}


def reservar_por_hora(medico_id: str, consultorio_id: str, data: str,
                       hora_inicio: str, quantidade_horas: int,
                       criado_por_admin: bool = False) -> dict:
    """
    `criado_por_admin` -- pedido do Paulo em 21/09/2026, botão "Agendar
    para:" da Agenda Horistas: o administrador reserva EM NOME do
    médico, debitando o saldo dele exatamente como se ele mesmo tivesse
    reservado (mesmas checagens de saldo/conflito/autorização abaixo),
    só marcando na reserva que foi o admin quem fez (ver
    db.criar_reserva_por_hora)."""
    from app.services import template_service

    _checar_pode_alugar_avulso(medico_id)
    _checar_data_nao_passada(data, hora_inicio)

    precos = creditos_db.obter_precos()
    horas_minimas = int(precos.get("horas_minimas", 1))
    if quantidade_horas < horas_minimas:
        raise ValueError(f"O mínimo é {horas_minimas} hora(s) por reserva.")

    horarios_ocupados = template_service.horas_da_reserva_por_hora(hora_inicio, quantidade_horas)
    if not template_service.verificar_disponibilidade(consultorio_id, data, horarios_ocupados):
        raise ConflitoDeReservaError(
            "Um ou mais desses horários está indisponível na Semana Padrão."
        )
    # Bloqueios/reservas manuais da Matriz do administrador.
    client = db.get_client()
    for h in horarios_ocupados:
        existe = (client.table("matriz_reservas_admin").select("id")
                  .eq("consultorio_id", consultorio_id).eq("data", data).eq("horario", h).execute().data)
        if existe:
            raise ConflitoDeReservaError("Um ou mais desses horários já foi reservado pelo administrador.")

    preco = creditos_db.calcular_preco_horas(quantidade_horas, precos)

    saldo_atual = creditos_db.obter_saldo(medico_id)
    if saldo_atual < preco:
        raise SaldoInsuficienteError(
            saldo_atual, preco,
            horas_disponiveis=creditos_db.estimar_horas_compraveis(saldo_atual),
            horas_necessarias=quantidade_horas,
        )

    hora_fim = db.somar_horas(hora_inicio, quantidade_horas)
    medico = db.get_medico_by_id(medico_id)
    _checar_conflito_google(medico, data, hora_inicio, hora_fim)

    try:
        reserva = db.criar_reserva_por_hora(consultorio_id, medico_id, data, hora_inicio, quantidade_horas,
                                             criado_por_admin=criado_por_admin)
    except ValueError as e:
        raise ConflitoDeReservaError(str(e))

    resultado = creditos_db.debitar_credito_por_reserva(
        medico_id, preco, reserva["id"], quantidade_horas=quantidade_horas, criado_por_admin=criado_por_admin
    )
    _rodar_em_segundo_plano(_finalizar_pos_reserva, medico, consultorio_id, reserva,
                             data, hora_inicio, hora_fim, medico_id)
    return {"reserva": reserva, "preco": preco, "saldo_atual": resultado["saldo_novo"],
            "saldo_horas": creditos_db.saldo_em_horas_medico(medico_id)}


def _para_iso_com_fuso(data: str, hora: str) -> str:
    """
    Monta um horário no formato que o Google Agenda exige (RFC3339),
    assumindo fuso de Brasília (-03:00) — o sistema hoje não guarda
    fuso horário por médico, então essa é uma simplificação. Se no
    futuro você tiver médicos em outros fusos, isso precisa mudar.
    """
    return f"{data}T{hora}:00-03:00"


def _checar_conflito_google(medico: dict | None, data: str, hora_inicio: str, hora_fim: str):
    """
    Checagem EXTRA (além da trava própria do sistema): se o médico
    conectou o Google Agenda dele, também olha lá para evitar marcar
    um turno em cima de um compromisso pessoal. Se ele não conectou,
    essa checagem é pulada silenciosamente — não é obrigatória.
    """
    if not medico:
        return
    from app.services import google_calendar_service as gcal

    try:
        inicio_iso = _para_iso_com_fuso(data, hora_inicio)
        fim_iso = _para_iso_com_fuso(data, hora_fim)
        if gcal.verificar_conflito(medico, inicio_iso, fim_iso):
            raise ConflitoDeReservaError(
                "Esse horário conflita com um compromisso na sua Google Agenda pessoal."
            )
    except ConflitoDeReservaError:
        raise
    except Exception as e:
        # se a checagem no Google falhar por qualquer motivo (token
        # vencido, API fora do ar, etc), não travamos a reserva por
        # causa disso — é uma checagem extra, não uma dependência crítica
        print(f"[reserva_service] Não consegui checar conflito no Google Agenda: {e}")


def _criar_evento_google(medico: dict | None, consultorio_id: str, reserva: dict,
                          data: str, hora_inicio: str, hora_fim: str):
    """Cria o evento correspondente na Google Agenda do médico, se ele tiver conectado."""
    if not medico or not medico.get("google_calendar_conectado"):
        return
    from app.services import google_calendar_service as gcal

    try:
        consultorio = db.get_consultorio_by_id(consultorio_id)
        inicio_iso = _para_iso_com_fuso(data, hora_inicio)
        fim_iso = _para_iso_com_fuso(data, hora_fim)
        evento_id = gcal.criar_evento(
            medico,
            titulo=f"Lifemax — {consultorio['nome'] if consultorio else 'Consultório'}",
            inicio_iso=inicio_iso,
            fim_iso=fim_iso,
            descricao="Reserva feita pelo sistema Lifemax.",
        )
        if evento_id:
            db.get_client().table("reservas").update({"google_evento_id": evento_id}).eq("id", reserva["id"]).execute()
    except Exception as e:
        print(f"[reserva_service] Não consegui criar o evento na Google Agenda: {e}")


def _hora_inicio_da_reserva(reserva: dict) -> str:
    """Hora de início real da reserva -- pra reserva por hora, vem gravado
    direto (hora_inicio); pra turno, deriva do período (PERIODOS_HORARIOS)
    porque turno só guarda 'manha'/'tarde'/'noite', sem hora explícita."""
    if reserva.get("tipo_reserva") == "hora" and reserva.get("hora_inicio"):
        return str(reserva["hora_inicio"])[:5]
    periodo = reserva.get("periodo")
    return db.PERIODOS_HORARIOS.get(periodo, ("08:00",))[0]


def _quantidade_horas_da_reserva(reserva: dict) -> int:
    """Quantas horas essa reserva ocupa -- usado só como PLANO B pra
    calcular o reembolso, caso não exista (por algum motivo) a transação
    de consumo original ligada a essa reserva."""
    if reserva.get("tipo_reserva") == "hora":
        return int(reserva.get("quantidade_horas") or 0)
    from app.services import template_service
    periodo = reserva.get("periodo")
    return len(template_service.HORARIOS_POR_PERIODO.get(periodo, []))


def cancelar_reserva(reserva_id: str, medico_id: str) -> dict:
    """Cancela uma reserva do próprio médico logado (nunca de outro --
    conferido aqui mesmo, defesa em profundidade além do que a rota já
    faz)."""
    reserva = db.get_reserva_by_id(reserva_id)
    if not reserva:
        raise ValueError("Reserva não encontrada.")
    if reserva["medico_id"] != medico_id:
        raise ValueError("Essa reserva não é sua.")
    return _efetivar_cancelamento(reserva, cancelado_por_admin=False)


def cancelar_reserva_admin(reserva_id: str) -> dict:
    """Pedido do Paulo em 21/09/2026: botão "Cancelar agendamento" da
    Agenda Horistas (admin) -- cancela a reserva de QUALQUER médico (sem
    checar dono, porque quem está cancelando aqui é o administrador),
    com a MESMA regra de reembolso (12h) e os mesmos avisos que valem
    pra um cancelamento feito pelo próprio médico."""
    reserva = db.get_reserva_by_id(reserva_id)
    if not reserva:
        raise ValueError("Reserva não encontrada.")
    return _efetivar_cancelamento(reserva, cancelado_por_admin=True)


def _efetivar_cancelamento(reserva: dict, cancelado_por_admin: bool) -> dict:
    """Lógica comum a cancelar_reserva e cancelar_reserva_admin -- extraída
    em 21/09/2026 pra não duplicar a regra de reembolso de 12h (pedido do
    Paulo em 10/09/2026) nem o e-mail de confirmação.

    Se faltar 12h ou mais para o início da reserva, devolve as horas
    gastas (reembolso, pro médico DONO da reserva, mesmo quando quem
    cancelou foi o admin); se faltar menos de 12h, o cancelamento ainda
    é permitido, mas SEM reembolso -- essa regra vale igual pros dois
    casos.

    O reembolso busca o valor EXATO da transação de consumo original
    (creditos_transacoes ligada a essa reserva) em vez de recalcular no
    preço atual -- protege contra o preço da hora ter mudado entre a
    reserva e o cancelamento."""
    reserva_id = reserva["id"]
    medico_id = reserva["medico_id"]

    if reserva["status"] == "cancelada":
        raise ValueError("Essa reserva já está cancelada.")

    hora_inicio = _hora_inicio_da_reserva(reserva)
    try:
        inicio_dt = datetime.strptime(f"{reserva['data']} {hora_inicio}", "%Y-%m-%d %H:%M")
    except Exception:
        inicio_dt = None

    # Fuso fixo de Brasília (-03:00), mesma simplificação já usada em
    # _para_iso_com_fuso pro Google Agenda (o sistema não guarda fuso
    # horário por médico).
    agora = datetime.utcnow() - timedelta(hours=3)
    dentro_de_12h = inicio_dt is not None and (inicio_dt - agora) < timedelta(hours=HORAS_MINIMAS_PARA_REEMBOLSO)

    db.marcar_reserva_cancelada(reserva_id, cancelado_por_admin=cancelado_por_admin)

    reembolsado = False
    horas_reembolsadas = 0
    saldo_atual = creditos_db.obter_saldo(medico_id)

    if not dentro_de_12h:
        transacao_original = db.obter_transacao_consumo_da_reserva(reserva_id)
        if transacao_original:
            valor_reembolso = abs(float(transacao_original["valor"]))
            horas_reembolsadas = int(transacao_original.get("quantidade_horas") or _quantidade_horas_da_reserva(reserva))
        else:
            horas_reembolsadas = _quantidade_horas_da_reserva(reserva)
            valor_reembolso = creditos_db.calcular_preco_horas(horas_reembolsadas) if horas_reembolsadas > 0 else 0.0

        if valor_reembolso > 0:
            descricao = "Reembolso por cancelamento de reserva" + (
                " (cancelada pelo administrador da Lifemax)" if cancelado_por_admin else ""
            )
            resultado = creditos_db.registrar_transacao(
                medico_id, tipo="ajuste", valor=valor_reembolso,
                descricao=descricao, reserva_id=reserva_id,
                quantidade_horas=horas_reembolsadas, carteira="salas",
            )
            saldo_atual = resultado["saldo_novo"]
            reembolsado = True

    # Item 5 (pedido do Paulo em 11/09/2026): confirma o cancelamento por
    # e-mail direto pro médico, se ele tiver e-mail cadastrado -- roda em
    # background (pedido do Paulo em 15/09/2026, mesmo motivo da reserva:
    # não travar a resposta esperando o envio do e-mail).
    _rodar_em_segundo_plano(_notificar_cancelamento_por_email, medico_id, reserva)

    return {
        "reembolsado": reembolsado,
        "horas_reembolsadas": horas_reembolsadas if reembolsado else 0,
        "saldo_atual": saldo_atual,
        "saldo_horas": creditos_db.saldo_em_horas_medico(medico_id),
        "dentro_de_12h": dentro_de_12h,
        "medico_id": medico_id,
    }


def _notificar_cancelamento_por_email(medico_id: str, reserva: dict):
    """E-mail de confirmação de cancelamento pro médico -- roda em
    background (ver _rodar_em_segundo_plano), não pode travar nem quebrar
    o cancelamento (que já foi efetivado antes de chamar isso)."""
    try:
        medico = db.get_medico_by_id(medico_id)
        if medico and medico.get("email"):
            consultorio = db.get_consultorio_by_id(reserva["consultorio_id"])
            descricao_periodo = reserva.get("periodo") or f"{reserva.get('quantidade_horas')}h avulsa " \
                                                            f"({reserva.get('hora_inicio', '')}-{reserva.get('hora_fim', '')})"
            email_service.notificar_cancelamento_medico(
                nome_medico=medico["nome"],
                consultorio_nome=consultorio["nome"] if consultorio else "Consultório",
                data=reserva["data"],
                horario=descricao_periodo,
                destinatario=medico["email"],
            )
    except Exception as e:
        print(f"[reserva_service] Erro ao mandar confirmação de cancelamento pro médico: {e}")


def associar_paciente(reserva_id: str, medico_id: str, paciente_id: str | None) -> dict:
    """Botão "Incluir/alterar paciente" na tela "Minha agenda" do médico
    -- pedido do Paulo em 11/09/2026: marca qual paciente (dos cadastrados
    por esse médico) vai ocupar o horário já reservado. Clicar de novo
    reabre a lista pra trocar por outro paciente (ou passar `paciente_id
    =None` pra limpar).

    Confere aqui, e não só na rota, que a reserva é do médico logado E
    que o paciente escolhido também foi cadastrado por ele -- sem isso um
    médico poderia colar o nome de um paciente de OUTRO médico numa
    reserva sua, só adivinhando/testando um id."""
    reserva = db.get_reserva_by_id(reserva_id)
    if not reserva:
        raise ValueError("Reserva não encontrada.")
    if reserva["medico_id"] != medico_id:
        raise ValueError("Essa reserva não é sua.")

    paciente = None
    if paciente_id:
        from app.services import pacientes_service
        paciente = pacientes_service.get_paciente_by_id(paciente_id)
        if not paciente or paciente["medico_id"] != medico_id:
            raise ValueError("Paciente não encontrado.")

    db.definir_paciente_reserva(reserva_id, paciente_id or None)

    # Mantém reserva_pacientes em sincronia -- o paciente marcado aqui já
    # entra automaticamente na lista de "Enviar e-mail" da seção nova
    # (item 5), sem o médico precisar adicionar de novo com "+ Adicionar
    # paciente". Só ADICIONA (nunca remove): trocar o paciente principal
    # aqui não tira quem já tinha sido incluído a mais na mesma reserva.
    if paciente_id:
        db.adicionar_paciente_reserva(reserva_id, paciente_id)

    return {"paciente_nome": paciente["nome_completo"] if paciente else None}


def definir_hora_confirmada(reserva_id: str, medico_id: str, hora_confirmada: str | None) -> dict:
    """Campo "confirmação da hora" -- pedido do Paulo em 11/09/2026: o
    médico confirma a hora EXATA da consulta (útil principalmente pra
    reserva de TURNO, que cobre um período inteiro em vez de um horário
    exato) antes de poder mandar o e-mail de agendamento pro paciente."""
    reserva = db.get_reserva_by_id(reserva_id)
    if not reserva:
        raise ValueError("Reserva não encontrada.")
    if reserva["medico_id"] != medico_id:
        raise ValueError("Essa reserva não é sua.")
    hora_confirmada = (hora_confirmada or "").strip() or None
    return db.definir_hora_confirmada_reserva(reserva_id, hora_confirmada)


def _checar_reserva_e_paciente_do_medico(reserva_id: str, medico_id: str, paciente_id: str):
    from app.services import pacientes_service
    reserva = db.get_reserva_by_id(reserva_id)
    if not reserva:
        raise ValueError("Reserva não encontrada.")
    if reserva["medico_id"] != medico_id:
        raise ValueError("Essa reserva não é sua.")
    paciente = pacientes_service.get_paciente_by_id(paciente_id)
    if not paciente or paciente["medico_id"] != medico_id:
        raise ValueError("Paciente não encontrado.")
    return reserva, paciente


def adicionar_paciente_agendamento(reserva_id: str, medico_id: str, paciente_id: str) -> list[dict]:
    """Botão "+ Adicionar paciente" -- pedido do Paulo em 11/09/2026:
    quando mais de um paciente está agendado pro mesmo horário/turno,
    inclui outro paciente (além do marcado em "Incluir/alterar
    paciente") na lista que recebe o e-mail de confirmação de
    agendamento. Devolve a lista atualizada de pacientes dessa reserva."""
    if not paciente_id:
        raise ValueError("Escolha um paciente.")
    _checar_reserva_e_paciente_do_medico(reserva_id, medico_id, paciente_id)
    db.adicionar_paciente_reserva(reserva_id, paciente_id)
    return db.listar_pacientes_agendados_por_reservas([reserva_id]).get(reserva_id, [])


def remover_paciente_agendamento(reserva_id: str, medico_id: str, paciente_id: str) -> list[dict]:
    """"Remover" da lista de pacientes agendados dessa reserva (não
    apaga o cadastro do paciente, só tira ele dessa reserva específica)."""
    reserva = db.get_reserva_by_id(reserva_id)
    if not reserva:
        raise ValueError("Reserva não encontrada.")
    if reserva["medico_id"] != medico_id:
        raise ValueError("Essa reserva não é sua.")
    db.remover_paciente_da_reserva(reserva_id, paciente_id)
    return db.listar_pacientes_agendados_por_reservas([reserva_id]).get(reserva_id, [])


def enviar_email_agendamento_paciente(reserva_id: str, medico_id: str, paciente_id: str) -> dict:
    """Botão "Enviar e-mail" -- pedido do Paulo em 11/09/2026: manda pro
    paciente o dia, o horário confirmado, o consultório e o endereço
    (padrão da Lifemax, ver creditos_service.endereco_padrao_formatado)
    da consulta. Exige que a "confirmação da hora" já tenha sido
    preenchida pelo médico e que o paciente tenha e-mail cadastrado --
    levanta ValueError com uma mensagem clara nos dois casos, sem
    quebrar o resto da tela."""
    reserva, paciente = _checar_reserva_e_paciente_do_medico(reserva_id, medico_id, paciente_id)
    if not reserva.get("hora_confirmada"):
        raise ValueError("Preencha a confirmação da hora antes de enviar o e-mail.")
    if not paciente.get("email"):
        raise ValueError(f'O paciente "{paciente["nome_completo"]}" não tem e-mail cadastrado.')

    medico = db.get_medico_by_id(medico_id)
    consultorio = db.get_consultorio_by_id(reserva["consultorio_id"])
    endereco = creditos_db.endereco_padrao_formatado()

    enviado = email_service.notificar_agendamento_paciente(
        nome_paciente=paciente["nome_completo"],
        nome_medico=medico["nome"] if medico else "",
        data=reserva["data"],
        hora_confirmada=reserva["hora_confirmada"],
        endereco=endereco,
        consultorio_nome=consultorio["nome"] if consultorio else "Consultório",
        destinatario=paciente["email"],
    )
    if enviado:
        db.marcar_email_agendamento_enviado(reserva_id, paciente_id)
    return {"enviado": enviado, "pacientes_agendados": db.listar_pacientes_agendados_por_reservas([reserva_id]).get(reserva_id, [])}


def _finalizar_pos_reserva(medico: dict | None, consultorio_id: str, reserva: dict,
                            data: str, hora_inicio: str, hora_fim: str, medico_id: str):
    """Agrupa as ações de pós-reserva que rodam em background (ver
    _rodar_em_segundo_plano acima): criar o evento no Google Agenda (se
    conectado) e mandar os e-mails de notificação. Nada aqui pode
    demorar a resposta que o médico já recebeu na tela."""
    _criar_evento_google(medico, consultorio_id, reserva, data, hora_inicio, hora_fim)
    _pos_reserva(medico_id, consultorio_id, reserva)


def _pos_reserva(medico_id: str, consultorio_id: str, reserva: dict):
    """Ações comuns depois de qualquer reserva bem-sucedida: avisa a
    recepção por email e checa se o médico precisa de alerta de saldo baixo.

    ⚠️ Tudo aqui roda DEPOIS que o crédito já foi debitado e a reserva já
    foi criada -- por isso cada passo tem seu próprio try/except: um erro
    ao mandar o email de aviso não pode virar um 500 pro médico que já
    pagou e já reservou o horário (achado em 10/09/2026, testando a troca
    de preços: a busca de `funcionarios` estava FORA do try/except e
    quebrava a reserva inteira sempre que essa tabela não existisse --
    ver migration_funcionarios.sql, que cria a tabela que faltava)."""
    medico = db.get_medico_by_id(medico_id)
    consultorio = db.get_consultorio_by_id(consultorio_id)

    descricao_periodo = reserva.get("periodo") or f"{reserva.get('quantidade_horas')}h avulsa " \
                                                    f"({reserva.get('hora_inicio', '')}-{reserva.get('hora_fim', '')})"
    try:
        destinatarios = [f["email"] for f in db.listar_funcionarios_ativos()]
        email_service.notificar_turno_escolhido(
            medico_nome=medico["nome"] if medico else "Médico",
            consultorio_nome=consultorio["nome"] if consultorio else "Consultório",
            data=reserva["data"],
            periodo=descricao_periodo,
            destinatarios=destinatarios,
        )
    except Exception as e:
        print(f"[reserva_service] Erro ao notificar funcionários: {e}")

    # Item 5 (pedido do Paulo em 11/09/2026): confirma o agendamento por
    # e-mail direto pro PRÓPRIO médico (diferente do aviso de
    # funcionários acima) -- só se ele tiver e-mail cadastrado.
    if medico and medico.get("email"):
        try:
            email_service.notificar_agendamento_medico(
                nome_medico=medico["nome"],
                consultorio_nome=consultorio["nome"] if consultorio else "Consultório",
                data=reserva["data"],
                horario=descricao_periodo,
                destinatario=medico["email"],
            )
        except Exception as e:
            print(f"[reserva_service] Erro ao mandar confirmação de agendamento pro médico: {e}")

    # Botão "Incluir/alterar paciente" já marcado ANTES da reserva (não é
    # o caso normal, mas por segurança) -- mantém reserva_pacientes em
    # sincronia com reservas.paciente_id (ver associar_paciente).
    if reserva.get("paciente_id"):
        try:
            db.adicionar_paciente_reserva(reserva["id"], reserva["paciente_id"])
        except Exception as e:
            print(f"[reserva_service] Erro ao sincronizar paciente da reserva: {e}")

    if medico:
        try:
            saldo_apos = creditos_db.obter_saldo(medico_id)
            notificacao_saldo.verificar_e_notificar_saldo_baixo(medico, saldo_apos)
            notificacao_saldo.verificar_e_notificar_saldo_baixo_fixo(medico, saldo_apos, carteira="salas")
        except Exception as e:
            print(f"[reserva_service] Erro ao verificar alerta de saldo baixo: {e}")
