"""
Aba "Relatórios" do admin -- pedido do Paulo em 10/09/2026, com print de
tela do sistema maior original (2 relatórios: "Agendamentos" e
"Transações").

Esse pacote (Reserva por Hora) não tem um cadastro de "cliente" separado
do médico nem um log de auditoria genérico com "operador" (usuário da
recepção) -- aqui quem reserva/cancela é sempre o próprio médico, direto
pela tela. Por isso, nos dois relatórios abaixo, tanto a coluna
"Operador (user)" quanto "Cliente" mostram o nome do MÉDICO envolvido --
é a aproximação mais fiel possível dos dois relatórios do sistema maior
dentro do que esse pacote reduzido realmente guarda.

- "Agendamentos": um evento por reserva feita (tipo "Agendamento", na
  hora em que ela foi criada) e mais um evento por reserva cancelada
  (tipo "Cancelamento", na hora em que foi cancelada -- ver
  reservas.cancelado_em, migration_cancelado_em.sql). É um log
  cronológico do que aconteceu, não da agenda em si.
- "Transações": direto da tabela creditos_transacoes (carteira "salas",
  que é medida em horas) -- toda compra de pacote, todo consumo por
  reserva e todo ajuste manual/reembolso aparece aqui.
"""
from app.services import supabase_client as db


OPERACOES_AGENDAMENTOS = ["Agendamento", "Cancelamento"]


def _descricao_horario(reserva: dict) -> str:
    if reserva.get("tipo_reserva") == "hora" and reserva.get("hora_inicio"):
        return f"{str(reserva['hora_inicio'])[:5]}h"
    rotulo = {"manha": "Manhã", "tarde": "Tarde", "noite": "Noite"}.get(reserva.get("periodo"), reserva.get("periodo") or "")
    return rotulo


def _data_br(data_str: str) -> str:
    if not data_str or len(data_str) < 10:
        return data_str or ""
    return f"{data_str[8:10]}/{data_str[5:7]}"


def _eventos_de_reservas() -> list[dict]:
    resp = (
        db.get_client()
        .table("reservas")
        .select("*, medicos(nome), consultorios(nome)")
        .execute()
        .data
    )
    eventos = []
    for r in resp:
        consultorio_nome = (r.get("consultorios") or {}).get("nome") or "—"
        medico_nome = (r.get("medicos") or {}).get("nome") or "—"
        horario_desc = _descricao_horario(r)
        descricao_base = f"{consultorio_nome} - {_data_br(r.get('data'))} - {horario_desc}"

        if r.get("criado_em"):
            eventos.append({
                "ocorrencia": r["criado_em"],
                "operador": medico_nome,
                "cliente": medico_nome,
                "operacao": "Agendamento",
                "consultorio": consultorio_nome,
                "descricao": descricao_base,
                "consultorio_id": r.get("consultorio_id"),
                "medico_id": r.get("medico_id"),
            })
        if r.get("status") == "cancelada" and r.get("cancelado_em"):
            eventos.append({
                "ocorrencia": r["cancelado_em"],
                "operador": medico_nome,
                "cliente": medico_nome,
                "operacao": "Cancelamento",
                "consultorio": consultorio_nome,
                "descricao": descricao_base,
                "consultorio_id": r.get("consultorio_id"),
                "medico_id": r.get("medico_id"),
            })
    return eventos


def listar_agendamentos(data_inicio: str | None = None, data_fim: str | None = None,
                         consultorio_id: str | None = None, medico_id: str | None = None,
                         cliente_busca: str = "", operacao: str | None = None,
                         ordenar: str = "desc") -> list[dict]:
    eventos = _eventos_de_reservas()
    cliente_busca = (cliente_busca or "").strip().lower()

    def _passa(e: dict) -> bool:
        ocorrencia_data = (e["ocorrencia"] or "")[:10]
        if data_inicio and ocorrencia_data < data_inicio:
            return False
        if data_fim and ocorrencia_data > data_fim:
            return False
        if consultorio_id and e.get("consultorio_id") != consultorio_id:
            return False
        if medico_id and e.get("medico_id") != medico_id:
            return False
        if operacao and e.get("operacao") != operacao:
            return False
        if cliente_busca and cliente_busca not in (e.get("cliente") or "").lower():
            return False
        return True

    filtrados = [e for e in eventos if _passa(e)]
    filtrados.sort(key=lambda e: e["ocorrencia"] or "", reverse=(ordenar != "asc"))
    return filtrados


def listar_transacoes(data_inicio: str | None = None, data_fim: str | None = None,
                       medico_id: str | None = None, cliente_busca: str = "",
                       ordenar: str = "desc") -> tuple[list[dict], float]:
    client = db.get_client()
    query = client.table("creditos_transacoes").select("*, medicos(nome)").eq("carteira", "salas")
    if medico_id:
        query = query.eq("medico_id", medico_id)
    resp = query.execute().data

    cliente_busca = (cliente_busca or "").strip().lower()
    linhas = []
    for t in resp:
        medico_nome = (t.get("medicos") or {}).get("nome") or "—"
        if cliente_busca and cliente_busca not in medico_nome.lower():
            continue
        ocorrencia = t.get("criado_em") or ""
        ocorrencia_data = ocorrencia[:10]
        if data_inicio and ocorrencia_data < data_inicio:
            continue
        if data_fim and ocorrencia_data > data_fim:
            continue
        linhas.append({
            "ocorrencia": ocorrencia,
            "operador": medico_nome,
            "cliente": medico_nome,
            "tipo": {"compra": "Compra", "consumo": "Consumo", "ajuste": "Ajuste"}.get(t.get("tipo"), t.get("tipo")),
            "qtd_horas": t.get("quantidade_horas") or 0,
            "valor": t.get("valor"),
        })

    linhas.sort(key=lambda l: l["ocorrencia"] or "", reverse=(ordenar != "asc"))
    total_horas = round(sum(abs(l["qtd_horas"] or 0) for l in linhas), 1)
    return linhas, total_horas


def listar_faturamento(faturadas: bool, data_inicio: str | None = None, data_fim: str | None = None,
                        medico_id: str | None = None, cliente_busca: str = "",
                        ordenar: str = "desc") -> tuple[list[dict], float]:
    """Relatórios "Transações ainda não faturadas" / "Transações faturadas"
    -- pedido do Paulo em 11/09/2026. Ao contrário de listar_transacoes()
    (que lê creditos_transacoes, o extrato em HORAS), este lê
    pagamentos_pix (os pagamentos em R$ de fato recebidos via Pix/cartão)
    e usa a coluna nota_fiscal_status (ver sql/migration_notas_fiscais.sql)
    pra separar o que ainda não tem Nota Fiscal emitida do que já tem.

    faturadas=False -> pagamentos confirmados (status='pago') com
      nota_fiscal_status == 'nao_emitida' (ainda faltando emitir).
    faturadas=True  -> pagamentos confirmados com nota_fiscal_status em
      ('emitida', 'enviada') (já faturados)."""
    client = db.get_client()
    query = client.table("pagamentos_pix").select("*, medicos(nome)").eq("status", "pago")
    if faturadas:
        query = query.neq("nota_fiscal_status", "nao_emitida")
    else:
        query = query.eq("nota_fiscal_status", "nao_emitida")
    if medico_id:
        query = query.eq("medico_id", medico_id)
    resp = query.execute().data

    cliente_busca = (cliente_busca or "").strip().lower()
    linhas = []
    for p in resp:
        medico_nome = (p.get("medicos") or {}).get("nome") or "—"
        if cliente_busca and cliente_busca not in medico_nome.lower():
            continue
        ocorrencia = p.get("pago_em") or p.get("criado_em") or ""
        ocorrencia_data = ocorrencia[:10]
        if data_inicio and ocorrencia_data < data_inicio:
            continue
        if data_fim and ocorrencia_data > data_fim:
            continue
        linhas.append({
            "id": p.get("id"),
            "medico_id": p.get("medico_id"),
            "ocorrencia": ocorrencia,
            "operador": medico_nome,
            "cliente": medico_nome,
            "forma_pagamento": {"pix": "Pix", "cartao": "Cartão"}.get(p.get("forma_pagamento"), p.get("forma_pagamento") or "—"),
            "valor": p.get("valor") or 0,
            "nota_fiscal_status": p.get("nota_fiscal_status"),
            "nota_fiscal_numero": p.get("nota_fiscal_numero"),
            "nota_fiscal_url": p.get("nota_fiscal_url"),
        })

    linhas.sort(key=lambda l: l["ocorrencia"] or "", reverse=(ordenar != "asc"))
    total_valor = round(sum(l["valor"] or 0 for l in linhas), 2)
    return linhas, total_valor


# ---------------------------------------------------------------------------
# Receitas (22/10/2026) -- tudo que EFETIVAMENTE entrou de dinheiro, por data.
# Fonte: pagamentos_pix com status 'pago' (Pix e cartão confirmados pelo Asaas),
# na data do pagamento (pago_em), no horário de Brasília -- independente de a
# nota fiscal já ter sido emitida ou não.
# ---------------------------------------------------------------------------
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_FUSO = ZoneInfo("America/Sao_Paulo")


def _data_local(valor) -> str:
    """'YYYY-MM-DD' no fuso de Brasília a partir de str ISO ou datetime."""
    if not valor:
        return ""
    try:
        dt = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.date().isoformat()
        return dt.astimezone(_FUSO).date().isoformat()
    except ValueError:
        return str(valor)[:10]


def _hora_local(valor) -> str:
    try:
        dt = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return (dt.astimezone(_FUSO) if dt.tzinfo else dt).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def periodo_receitas(data_inicio: str = "", data_fim: str = "", mes: str = "") -> tuple[str, str]:
    """Resolve o período pedido: `mes` ('YYYY-MM') vale mais que de/até; sem nada,
    devolve os últimos 120 dias até hoje."""
    hoje = datetime.now(_FUSO).date()
    mes = (mes or "").strip()
    if len(mes) == 7 and mes[4] == "-":
        try:
            ini = date(int(mes[:4]), int(mes[5:7]), 1)
            prox = date(ini.year + (ini.month == 12), ini.month % 12 + 1, 1)
            return ini.isoformat(), (prox - timedelta(days=1)).isoformat()
        except ValueError:
            pass
    if data_inicio or data_fim:
        return data_inicio, data_fim
    return (hoje - timedelta(days=119)).isoformat(), hoje.isoformat()


def listar_receitas(data_inicio: str, data_fim: str, medico_id: str | None = None,
                    cliente_busca: str = "") -> tuple[list[dict], list[dict], float]:
    """Devolve (linhas, resumo_por_dia, total). `linhas` em ordem cronológica
    decrescente; `resumo_por_dia` = [{data, qtd, total}] também decrescente."""
    query = db.get_client().table("pagamentos_pix").select("*, medicos(nome)").eq("status", "pago")
    if medico_id:
        query = query.eq("medico_id", medico_id)
    resp = query.execute().data or []

    cliente_busca = (cliente_busca or "").strip().lower()
    linhas = []
    for p in resp:
        medico_nome = (p.get("medicos") or {}).get("nome") or "—"
        if cliente_busca and cliente_busca not in medico_nome.lower():
            continue
        momento = p.get("pago_em") or p.get("criado_em")
        dia = _data_local(momento)
        if not dia or (data_inicio and dia < data_inicio) or (data_fim and dia > data_fim):
            continue
        horas = p.get("horas_pacote")
        parcelas = p.get("parcelas") or 1
        forma = {"pix": "Pix", "cartao": "Cartão"}.get(p.get("forma_pagamento"), p.get("forma_pagamento") or "—")
        linhas.append({
            "data": dia, "hora": _hora_local(momento), "cliente": medico_nome, "forma": forma,
            "descricao": (f"Pacote de {horas}h" if horas else "Recarga de horas")
                         + (f" · {parcelas}x" if forma == "Cartão" and parcelas > 1 else ""),
            "valor": float(p.get("valor") or 0),
            "_ordem": str(momento),
        })
    linhas.sort(key=lambda l: l["_ordem"], reverse=True)

    por_dia: dict[str, dict] = {}
    for l in linhas:
        d = por_dia.setdefault(l["data"], {"data": l["data"], "qtd": 0, "total": 0.0})
        d["qtd"] += 1
        d["total"] = round(d["total"] + l["valor"], 2)
    resumo = sorted(por_dia.values(), key=lambda d: d["data"], reverse=True)
    return linhas, resumo, round(sum(l["valor"] for l in linhas), 2)
