"""
Semana Padrão (template): define quais HORÁRIOS individuais ficam
DISPONÍVEIS para reserva, por dia da semana + consultório, repetindo-se
toda semana indefinidamente — no mesmo formato de grade por hora que o
Lifemax já usa (não mais por turno inteiro).

Grade de horários fixos usada em todo o sistema (11 horários por dia,
com intervalo de almoço entre 12h e 13h, e uma pausa para limpeza entre
17h e 17h30 -- pedido do Paulo em 21/09/2026):
  Manhã: 08:00, 09:00, 10:00, 11:00
  Tarde: 13:00, 14:00, 15:00, 16:00
  (pausa para limpeza: 17:00–17:30)
  Noite: 17:30, 18:30, 19:30 (a última vai até 20:30, horário de encerramento)

Por padrão, tudo está disponível — só guardamos os BLOQUEIOS (o que o
admin desmarcou).

Convenção de dia_semana: 0=domingo, 1=segunda, ..., 6=sábado (mesma
convenção do JavaScript Date.getDay()).
"""
import time
from datetime import date
from app.services.supabase_client import get_client

HORARIOS_DO_DIA = ["08:00", "09:00", "10:00", "11:00",
                    "13:00", "14:00", "15:00", "16:00",
                    "17:30", "18:30", "19:30"]

HORARIOS_POR_PERIODO = {
    "manha": ["08:00", "09:00", "10:00", "11:00"],
    "tarde": ["13:00", "14:00", "15:00", "16:00"],
    "noite": ["17:30", "18:30", "19:30"],
}


def dia_semana_de(data_iso: str) -> int:
    """Converte 'YYYY-MM-DD' para dia_semana no padrão 0=domingo...6=sábado."""
    d = date.fromisoformat(data_iso)
    return (d.weekday() + 1) % 7


def horas_da_reserva_por_hora(hora_inicio: str, quantidade_horas: int) -> list[str]:
    """Lista de horários de início (ex: ['09:00','10:00']) que uma reserva de N horas ocupa."""
    partes = hora_inicio.split(":")
    inicio_min = int(partes[0]) * 60 + int(partes[1])
    return [f"{(inicio_min + i * 60) // 60:02d}:{(inicio_min + i * 60) % 60:02d}" for i in range(quantidade_horas)]


def listar_bloqueios() -> list[dict]:
    resp = get_client().table("template_semanal_bloqueios").select("*").execute()
    return resp.data + _bloqueios_fixos_fim_de_semana()


# Regra fixa -- pedido do Paulo em 15/09/2026 (sábado e domingo, a partir
# de 12h) e AJUSTADA em 24/09/2026 (item 1): domingo passou a ficar
# bloqueado o DIA INTEIRO (manhã também, não só tarde/noite) -- sábado
# continua igual, só tarde/noite. Ficam SEMPRE bloqueados para reserva,
# em TODOS os consultórios, sem precisar de nenhuma configuração manual
# na Semana Padrão. Isso entra automaticamente em qualquer lugar que já
# use listar_bloqueios(): a Grade de Turnos do médico, a Agenda Horistas
# do admin (fica cinza, igual aos outros bloqueios) e a própria checagem
# de disponibilidade em verificar_disponibilidade (então o horário fica
# de fato indisponível pra reservar, não só visualmente cinza) -- e a
# Matriz de Agendamento também passa a refletir isso automaticamente (ver
# app/routes/admin.py api_matriz_template, que agora busca os bloqueios
# daqui em vez de ler a tabela direto).
_DIA_DOMINGO = 0
_DIA_SABADO = 6
_HORARIOS_BLOQUEADOS_DOMINGO = HORARIOS_DO_DIA  # dia inteiro
_HORARIOS_BLOQUEADOS_SABADO = HORARIOS_POR_PERIODO["tarde"] + HORARIOS_POR_PERIODO["noite"]


_CACHE_CONSULTORIO_IDS: dict = {"ids": None, "expira_em": 0.0}
_CACHE_TTL_SEGUNDOS = 60  # consultórios praticamente nunca mudam -- pedido do
# Paulo em 23/09/2026 (item 8, acelerar a reserva): essa lista era buscada
# no banco de novo a cada única checagem de disponibilidade (ou seja, a
# cada clique de reserva), só pra aplicar a regra fixa de fim de semana.
# Com o cache, só busca de novo depois de expirar 60s -- se o admin criar
# um consultório novo, o pior caso é ele demorar até 1 minuto pra entrar
# na regra de bloqueio de fim de semana, o que é aceitável.


def _bloqueios_fixos_fim_de_semana() -> list[dict]:
    agora = time.monotonic()
    if _CACHE_CONSULTORIO_IDS["ids"] is None or agora >= _CACHE_CONSULTORIO_IDS["expira_em"]:
        _CACHE_CONSULTORIO_IDS["ids"] = [c["id"] for c in get_client().table("consultorios").select("id").execute().data]
        _CACHE_CONSULTORIO_IDS["expira_em"] = agora + _CACHE_TTL_SEGUNDOS
    consultorio_ids = _CACHE_CONSULTORIO_IDS["ids"]
    return [
        {"consultorio_id": cid, "dia_semana": dia, "hora_inicio": hora}
        for cid in consultorio_ids
        for dia, horarios in ((_DIA_DOMINGO, _HORARIOS_BLOQUEADOS_DOMINGO), (_DIA_SABADO, _HORARIOS_BLOQUEADOS_SABADO))
        for hora in horarios
    ]


def esta_bloqueado(bloqueios: list[dict], consultorio_id: str, dia_semana: int, hora_inicio: str) -> bool:
    return any(
        b["consultorio_id"] == consultorio_id and b["dia_semana"] == dia_semana and b["hora_inicio"] == hora_inicio
        for b in bloqueios
    )


def verificar_disponibilidade(consultorio_id: str, data_iso: str, horarios: list[str]) -> bool:
    """True se TODOS os horários da lista estiverem liberados na semana padrão."""
    dia = dia_semana_de(data_iso)
    bloqueios = listar_bloqueios()
    return all(not esta_bloqueado(bloqueios, consultorio_id, dia, h) for h in horarios)


def data_tem_matriz_gerada(data_iso: str) -> bool:
    """True se essa data cai dentro do período de alguma "Replicar matriz
    por período/mês" que o admin já rodou (ver matriz_replicacoes,
    api_matriz_replicar_periodo/api_matriz_replicar_mes em admin.py) --
    pedido do Paulo em 23/09/2026: antes, uma data sem NENHUMA
    replicação ainda assim aparecia com todos os horários "livres" pro
    médico (a Matriz só bloqueia o que foi explicitamente marcado, não
    "abre" o que não foi tocado) -- deixava o médico reservar datas que
    o admin nunca preparou de verdade. Agora, reservar_por_hora/
    reservar_turno chamam isso ANTES de deixar passar, pra médico não
    conseguir mais reservar num período "no escuro"."""
    q = (
        get_client().table("matriz_replicacoes")
        .select("id").lte("data_inicio", data_iso).gte("data_fim", data_iso)
    )
    try:
        # Replicações desfeitas ("Desfazer a matriz") não contam mais.
        return bool(q.is_("desfeita_em", None).limit(1).execute().data)
    except Exception:
        # Coluna ainda não criada (migração pendente): comportamento antigo.
        return bool(
            get_client().table("matriz_replicacoes").select("id")
            .lte("data_inicio", data_iso).gte("data_fim", data_iso).limit(1).execute().data
        )


def dias_sem_matriz(data_inicio: str, data_fim: str) -> list[str]:
    """Datas do intervalo que NÃO estão cobertas por nenhuma matriz gerada
    (e não desfeita). Mesma regra de data_tem_matriz_gerada, mas numa
    consulta só: a grade do médico usa isso pra avisar que o período ainda
    não tem agenda, em vez de mostrar tudo "livre" e falhar só ao reservar."""
    cli = get_client()
    try:
        q = (cli.table("matriz_replicacoes").select("data_inicio,data_fim")
             .lte("data_inicio", data_fim).gte("data_fim", data_inicio))
        try:
            linhas = q.is_("desfeita_em", None).execute().data
        except Exception:
            linhas = (cli.table("matriz_replicacoes").select("data_inicio,data_fim")
                      .lte("data_inicio", data_fim).gte("data_fim", data_inicio).execute().data)
    except Exception as e:
        print(f"[template_service] dias_sem_matriz indisponível: {e}")
        return []
    cobertos = [(str(l["data_inicio"])[:10], str(l["data_fim"])[:10]) for l in linhas]
    d = date.fromisoformat(data_inicio); fim = date.fromisoformat(data_fim)
    out = []
    while d <= fim:
        iso = d.isoformat()
        if not any(a <= iso <= b for a, b in cobertos):
            out.append(iso)
        d = date.fromordinal(d.toordinal() + 1)
    return out


def alternar_bloqueio(consultorio_id: str, dia_semana: int, hora_inicio: str) -> bool:
    """
    Alterna o estado (disponível <-> bloqueado) de uma célula da Semana
    Padrão. Retorna True se ficou BLOQUEADO, False se ficou DISPONÍVEL.
    """
    client = get_client()
    existentes = (
        client.table("template_semanal_bloqueios")
        .select("id")
        .eq("consultorio_id", consultorio_id)
        .eq("dia_semana", dia_semana)
        .eq("hora_inicio", hora_inicio)
        .execute()
        .data
    )
    if existentes:
        client.table("template_semanal_bloqueios").delete().eq("id", existentes[0]["id"]).execute()
        return False

    client.table("template_semanal_bloqueios").insert({
        "consultorio_id": consultorio_id, "dia_semana": dia_semana, "hora_inicio": hora_inicio,
    }).execute()
    return True


# ---------- Dias ocultos (pedido do Paulo em 21/10/2026) ----------
#
# O admin pode "ocultar" um dia inteiro em Visualizar agenda: esse dia some
# da grade dos médicos (todas as salas) como se não existisse, e também não
# aceita reserva nova (site ou Dora). Reservas que o médico JÁ tinha nesse
# dia continuam existindo e aparecendo em "Minha agenda". Tabela
# `dias_ocultos` (ver sql/migration_matriz_desfazer_e_ocultar_dias.sql).

def listar_dias_ocultos(data_inicio: str | None = None, data_fim: str | None = None) -> list[str]:
    try:
        q = get_client().table("dias_ocultos").select("data")
        if data_inicio:
            q = q.gte("data", data_inicio)
        if data_fim:
            q = q.lte("data", data_fim)
        return sorted(str(r["data"])[:10] for r in q.execute().data)
    except Exception as e:  # tabela ainda não criada (migração pendente)
        print(f"[template_service] dias_ocultos indisponível: {e}")
        return []


def dia_esta_oculto(data_iso: str) -> bool:
    try:
        resp = get_client().table("dias_ocultos").select("data").eq("data", data_iso).limit(1).execute()
        return bool(resp.data)
    except Exception as e:
        print(f"[template_service] dias_ocultos indisponível: {e}")
        return False
