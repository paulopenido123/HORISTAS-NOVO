"""
Sistema de grade de turnos: página web onde os médicos escolhem
consultório + data + turno (manhã/tarde/noite), e os funcionários
recebem email automático quando um turno é reservado.

Rotas:
  GET  /turnos                    -> página HTML da grade
  GET  /api/turnos/grade          -> JSON com disponibilidade (?data_inicio=&dias=)
  GET  /api/turnos/medicos        -> lista de médicos (para o seletor)
  POST /api/turnos/reservar       -> reserva um turno + dispara email
"""
from datetime import date, timedelta
from flask import Blueprint, request, jsonify, render_template
from app.services import supabase_client as db
from app.services import creditos_service as creditos_db
from app.services import reserva_service
from app.services import template_service
from app.services.auth_service import requer_login_medico, medico_logado_id

turnos_bp = Blueprint("turnos", __name__)


# ⚠️ Antes, essa tela (e as rotas de API abaixo) não exigiam login: quem
# tivesse o link escolhia QUALQUER médico num seletor e gastava o saldo
# dele. Agora a tela exige login (o mesmo telefone+senha de sempre) e,
# mais importante, as rotas de reserva NUNCA confiam no medico_id que
# vem do navegador -- usam sempre o médico da sessão logada. Isso
# resolve o problema mesmo que alguém tente forçar a chamada direto
# pela API, sem passar pela tela.
@turnos_bp.route("/turnos", methods=["GET"])
@requer_login_medico
def pagina_turnos():
    medico = db.get_medico_by_id(medico_logado_id())
    return render_template("turnos.html", medico=medico)


@turnos_bp.route("/api/turnos/medicos", methods=["GET"])
@requer_login_medico
def api_medicos():
    # Médico "fixo" (mensalista/turno) já tem consultório fixo garantido pela
    # grade_medico_fixo, e o "horista" de verdade usa saldo de horas próprio
    # administrado pela recepção (fluxo totalmente diferente, fora deste
    # pacote) -- nenhum dos dois aluga consultório avulso por hora/turno
    # aqui. Essa lista só mostra o PRÓPRIO médico logado, quando ele é
    # 'avulso' -- nunca todos os médicos.
    medico = db.get_medico_by_id(medico_logado_id())
    if medico is None or medico.get("tipo_vinculo") in ("fixo", "horista"):
        return jsonify([])
    return jsonify([medico])


@turnos_bp.route("/api/turnos/grade", methods=["GET"])
@requer_login_medico
def api_grade():
    data_inicio_str = request.args.get("data_inicio", date.today().isoformat())
    dias = int(request.args.get("dias", 7))

    data_inicio = date.fromisoformat(data_inicio_str)
    data_fim = data_inicio + timedelta(days=dias - 1)

    grade = db.grade_de_turnos(data_inicio.isoformat(), data_fim.isoformat())

    # Privacidade -- pedido do Paulo em 14/09/2026: o médico pode ver que
    # um horário está ocupado, mas NUNCA o nome de outro profissional
    # (só o dele mesmo). Quem vê todos os nomes é só o administrador, na
    # tela "Agenda Horistas" (app/routes/admin.py api_agenda_horistas_grade).
    medico_id_atual = medico_logado_id()
    for r in grade.get("reservas", []):
        if r.get("medico_id") != medico_id_atual:
            r["medicos"] = None

    grade["data_inicio"] = data_inicio.isoformat()
    grade["data_fim"] = data_fim.isoformat()
    grade["dias"] = dias
    grade["bloqueios_template"] = template_service.listar_bloqueios()
    # Reservas manuais feitas pelo administrador na Matriz: esses horários
    # aparecem em rosa e não podem ser escolhidos pelo médico.
    inicio = data_inicio.isoformat(); fim = data_fim.isoformat()
    grade["reservas_admin"] = (db.get_client().table("matriz_reservas_admin")
        .select("*").gte("data", inicio).lte("data", fim).execute().data)
    return jsonify(grade)


@turnos_bp.route("/api/turnos/reservar", methods=["POST"])
@requer_login_medico
def api_reservar():
    body = request.get_json(force=True)
    # medico_id NUNCA vem do navegador -- sempre o médico da sessão logada,
    # mesmo que o corpo da requisição tente mandar outro id.
    medico_id = medico_logado_id()
    consultorio_id = body.get("consultorio_id")
    data_reserva = body.get("data")
    periodo = body.get("periodo")

    if not all([consultorio_id, data_reserva, periodo]):
        return jsonify({"erro": "Campos obrigatórios: consultorio_id, data, periodo"}), 400

    try:
        resultado = reserva_service.reservar_turno(medico_id, consultorio_id, data_reserva, periodo)
    except reserva_service.SaldoInsuficienteError as e:
        return jsonify({"erro": str(e)}), 402
    except reserva_service.ConflitoDeReservaError as e:
        return jsonify({"erro": str(e)}), 409
    except reserva_service.NaoAutorizadoError as e:
        return jsonify({"erro": str(e)}), 403
    except reserva_service.DadosPessoaisIncompletosError as e:
        return jsonify({"erro": str(e), "campos_faltando": e.campos_faltando}), 403
    except reserva_service.MatrizNaoGeradaError as e:
        return jsonify({"erro": str(e)}), 403
    except reserva_service.MedicoFixoNaoPodeAlugarError as e:
        return jsonify({"erro": str(e)}), 403
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400

    return jsonify({
        "reserva": resultado["reserva"],
        "preco": resultado["preco"],
        "tryout": resultado.get("tryout", False),
        "saldo_atual": resultado["saldo_atual"],
        "saldo_horas": resultado["saldo_horas"],
    }), 201


@turnos_bp.route("/api/turnos/reservar-horas", methods=["POST"])
@requer_login_medico
def api_reservar_horas():
    body = request.get_json(force=True)
    # medico_id NUNCA vem do navegador -- sempre o médico da sessão logada.
    medico_id = medico_logado_id()
    consultorio_id = body.get("consultorio_id")
    data_reserva = body.get("data")
    hora_inicio = body.get("hora_inicio")
    try:
        quantidade_horas = int(body.get("quantidade_horas", 0))
    except (TypeError, ValueError):
        return jsonify({"erro": "quantidade_horas inválida."}), 400

    if not all([consultorio_id, data_reserva, hora_inicio]) or quantidade_horas <= 0:
        return jsonify({"erro": "Campos obrigatórios: consultorio_id, data, "
                                 "hora_inicio, quantidade_horas"}), 400

    try:
        resultado = reserva_service.reservar_por_hora(
            medico_id, consultorio_id, data_reserva, hora_inicio, quantidade_horas
        )
    except reserva_service.SaldoInsuficienteError as e:
        return jsonify({"erro": str(e)}), 402
    except reserva_service.ConflitoDeReservaError as e:
        return jsonify({"erro": str(e)}), 409
    except reserva_service.NaoAutorizadoError as e:
        return jsonify({"erro": str(e)}), 403
    except reserva_service.DadosPessoaisIncompletosError as e:
        return jsonify({"erro": str(e), "campos_faltando": e.campos_faltando}), 403
    except reserva_service.MatrizNaoGeradaError as e:
        return jsonify({"erro": str(e)}), 403
    except reserva_service.MedicoFixoNaoPodeAlugarError as e:
        return jsonify({"erro": str(e)}), 403
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400

    return jsonify({
        "reserva": resultado["reserva"],
        "preco": resultado["preco"],
        "tryout": resultado.get("tryout", False),
        "saldo_atual": resultado["saldo_atual"],
        "saldo_horas": resultado["saldo_horas"],
    }), 201


@turnos_bp.route("/api/turnos/cancelar", methods=["POST"])
@requer_login_medico
def api_cancelar():
    body = request.get_json(force=True)
    # medico_id NUNCA vem do navegador -- sempre o médico da sessão
    # logada (reserva_service.cancelar_reserva confere de novo que a
    # reserva é realmente dele, como defesa em profundidade).
    medico_id = medico_logado_id()
    reserva_id = body.get("reserva_id")
    if not reserva_id:
        return jsonify({"erro": "Campo obrigatório: reserva_id"}), 400

    try:
        resultado = reserva_service.cancelar_reserva(reserva_id, medico_id)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400

    return jsonify(resultado), 200


@turnos_bp.route("/api/turnos/precos", methods=["GET"])
@requer_login_medico
def api_precos():
    precos = creditos_db.obter_precos()
    return jsonify({
        "horas_minimas": precos.get("horas_minimas", 1),
        "preco_hora_avulsa": creditos_db.preco_hora_avulsa(),
    })
