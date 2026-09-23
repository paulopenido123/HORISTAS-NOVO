"""
API pro assistente de WhatsApp "Dora" (pedido do Paulo em 21/09/2026).

A Dora roda num projeto Flask SEPARADO deste (o do Lifemax/Lifedoctor,
com `app/routes/webhook.py` e `app/services/recepcao_agent.py`) e usa
esses endpoints daqui pra atender médicos avulsos deste sistema de
horistas: identificar se quem está falando no WhatsApp é um médico
cadastrado aqui (por telefone), consultar saldo/cortesia de tryout,
listar consultórios e fotos, checar disponibilidade e reservar horário
em nome do médico -- tudo reaproveitando 100% a mesma lógica de negócio
que a Grade de Turnos usa (reserva_service), então o resultado é
idêntico ao de uma reserva feita pelo próprio médico direto no site:
mesmo débito de saldo (ou cortesia de tryout), mesma checagem de
conflito, mesmas notificações por e-mail/Google Agenda em segundo
plano.

Autenticação: toda chamada precisa do header "X-API-Key" batendo com
Config.DORA_API_KEY. Sem isso configurado no Render, TODAS as chamadas
são recusadas (nunca aceita um valor vazio nos dois lados). Esse
blueprint fica isento de CSRF (ver app/__init__.py, csrf.exempt) porque
quem chama é um servidor (a Dora), não um navegador com sessão -- é a
API key que garante que só a Dora consegue chamar.
"""
from functools import wraps
from datetime import date
from flask import Blueprint, request, jsonify
from app.config import Config
from app.services import supabase_client as db
from app.services import creditos_service as creditos_db
from app.services import reserva_service
from app.services import template_service
from app.services import agenda_fixos_service

api_dora_bp = Blueprint("api_dora", __name__, url_prefix="/api/dora")


def _exigir_api_key(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        chave_esperada = Config.DORA_API_KEY
        chave_recebida = request.headers.get("X-API-Key", "")
        if not chave_esperada or chave_recebida != chave_esperada:
            return jsonify({"erro": "API key ausente ou inválida."}), 401
        return view(*args, **kwargs)
    return wrapper


def _medico_para_json(medico: dict) -> dict:
    saldo_horas = creditos_db.saldo_em_horas_medico(medico["id"])
    tryout_restante = creditos_db.tryout_restante(medico["id"])
    # "avulso" é o único tipo que aluga consultório por essa agenda (ver
    # reserva_service._checar_pode_alugar_avulso) -- 'fixo' e 'horista'
    # têm agendas próprias, fora deste fluxo. A Dora usa esse campo pra
    # saber se pode oferecer "reservar consultório" pra esse médico.
    pode_reservar_avulso = (medico.get("tipo_vinculo") or "avulso") == "avulso" and medico.get("autorizado", True)
    return {
        "id": medico["id"],
        "nome": medico["nome"],
        "telefone": medico["telefone"],
        "tipo_vinculo": medico.get("tipo_vinculo") or "avulso",
        "autorizado": medico.get("autorizado", True),
        "pode_reservar_avulso": pode_reservar_avulso,
        "saldo_horas": saldo_horas,
        "tryout_restante": tryout_restante,
    }


@api_dora_bp.route("/medico", methods=["GET"])
@_exigir_api_key
def api_dora_medico():
    """Primeiro passo do fluxo da Dora: identificar se quem está
    escrevendo é um médico cadastrado aqui (por telefone) ou não --
    "encontrado": false significa que é paciente (ou não-cadastrado),
    e a Dora segue com o fluxo normal dela de paciente."""
    telefone = agenda_fixos_service.normalizar_telefone(request.args.get("telefone", ""))
    if not telefone:
        return jsonify({"erro": "telefone é obrigatório."}), 400
    medico = db.get_medico_by_telefone(telefone)
    if medico is None:
        return jsonify({"encontrado": False})
    return jsonify({"encontrado": True, "medico": _medico_para_json(medico)})


@api_dora_bp.route("/consultorios", methods=["GET"])
@_exigir_api_key
def api_dora_consultorios():
    """Lista de consultórios (com fotos) pra Dora oferecer/enviar quando
    o médico pedir foto de um consultório específico."""
    consultorios = db.ordenar_consultorios(
        db.get_client().table("consultorios").select("id,nome,fotos,andar").eq("ativo", True).execute().data
    )
    return jsonify({"consultorios": consultorios})


@api_dora_bp.route("/disponibilidade", methods=["GET"])
@_exigir_api_key
def api_dora_disponibilidade():
    """Quais horários (dos 11 fixos do dia) estão livres num consultório
    numa data -- pra Dora saber o que oferecer ANTES de tentar reservar
    (evita ficar tentando às cegas e esbarrando em conflito)."""
    consultorio_id = request.args.get("consultorio_id")
    data_str = request.args.get("data")
    if not consultorio_id or not data_str:
        return jsonify({"erro": "consultorio_id e data são obrigatórios (data no formato YYYY-MM-DD)."}), 400
    try:
        date.fromisoformat(data_str)
    except ValueError:
        return jsonify({"erro": "data inválida, use o formato YYYY-MM-DD."}), 400

    client = db.get_client()
    dia_semana = template_service.dia_semana_de(data_str)
    bloqueios = template_service.listar_bloqueios()
    reservas = (
        client.table("reservas").select("hora_inicio,quantidade_horas,periodo,tipo_reserva")
        .eq("consultorio_id", consultorio_id).eq("data", data_str).neq("status", "cancelada").execute().data
    )
    holds = (
        client.table("matriz_reservas_admin").select("horario")
        .eq("consultorio_id", consultorio_id).eq("data", data_str).execute().data
    )

    ocupados = set()
    for r in reservas:
        if r.get("tipo_reserva") == "hora" and r.get("hora_inicio"):
            horarios = template_service.horas_da_reserva_por_hora(
                str(r["hora_inicio"])[:5], r.get("quantidade_horas") or 1
            )
            ocupados.update(horarios)
        elif r.get("periodo"):
            ocupados.update(template_service.HORARIOS_POR_PERIODO.get(r["periodo"], []))
    for h in holds:
        ocupados.add(str(h["horario"])[:5])

    livres = [
        h for h in template_service.HORARIOS_DO_DIA
        if h not in ocupados and not template_service.esta_bloqueado(bloqueios, consultorio_id, dia_semana, h)
    ]
    return jsonify({"data": data_str, "consultorio_id": consultorio_id, "horarios_livres": livres})


@api_dora_bp.route("/reservar", methods=["POST"])
@_exigir_api_key
def api_dora_reservar():
    """Reserva um horário de consultório EM NOME do médico identificado
    pelo telefone -- mesma lógica de reserva_service usada pelo site
    (débito de saldo ou cortesia de tryout, checagem de conflito,
    notificações em segundo plano)."""
    body = request.get_json(force=True)
    telefone = agenda_fixos_service.normalizar_telefone(body.get("telefone", ""))
    consultorio_id = body.get("consultorio_id")
    data_reserva = body.get("data")
    hora_inicio = body.get("hora_inicio")
    try:
        quantidade_horas = int(body.get("quantidade_horas", 1))
    except (TypeError, ValueError):
        return jsonify({"erro": "quantidade_horas inválida."}), 400

    if not all([telefone, consultorio_id, data_reserva, hora_inicio]) or quantidade_horas <= 0:
        return jsonify({"erro": "Campos obrigatórios: telefone, consultorio_id, data, "
                                 "hora_inicio, quantidade_horas."}), 400

    medico = db.get_medico_by_telefone(telefone)
    if medico is None:
        return jsonify({"erro": "Nenhum médico cadastrado com esse telefone no sistema de horistas."}), 404

    try:
        resultado = reserva_service.reservar_por_hora(
            medico["id"], consultorio_id, data_reserva, hora_inicio, quantidade_horas
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
        "tryout": resultado.get("tryout", False),
        "preco": resultado["preco"],
        "saldo_horas": resultado["saldo_horas"],
        "medico_nome": medico["nome"],
    }), 201
