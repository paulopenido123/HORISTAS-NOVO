"""
HISTÓRICO AUTOMÁTICO dos dados (v128, pedido do Paulo em 25/11/2026, depois do incidente do outro sistema).

- Uma cópia completa (mesmo formato do Admin > Backup) a cada hora; guarda as últimas 48 horas.
- NÃO guarda a cópia se os dados atuais estiverem muito menores que a última boa (menos da metade das linhas): registra
  um "bloqueado" e avisa os administradores, para não espalhar um apagão pelo histórico.
- Cópia extra antes de qualquer restauração ("antes_restaurar") e sob demanda ("manual"): ficam 7 dias.
- Tabela: historico_dados (sql/migration_historico_dados.sql). Se a tabela ainda não existir, tudo aqui falha em silêncio
  (o sistema continua funcionando; a tela mostra o aviso para rodar a migração).
- A própria tabela de histórico e os documentos de identidade ficam fora das cópias (ver backup_service).
"""
import datetime
import json
import threading
import time
from app.services import backup_service
from app.services.pg_query import _ConnCtx

HORAS_GUARDAR = 48
DIAS_GUARDAR_EXTRAS = 7
INTERVALO_MINUTOS = 60
FRACAO_MINIMA = 0.5        # menos que 50% das linhas da última cópia boa = suspeito
MINIMO_PARA_COMPARAR = 20  # só compara quando a última cópia tinha pelo menos isso de linhas
TAMANHO_MAXIMO = 60 * 1024 * 1024
_LOCK_ID = 7280001


def _tabela_inexistente(e: Exception) -> bool:
    return getattr(e, "pgcode", None) == "42P01"


def tabela_ok() -> bool:
    try:
        with _ConnCtx() as conn:
            with conn.cursor() as cur:
                cur.execute("select 1 from historico_dados limit 1")
            conn.rollback()
        return True
    except Exception as e:
        if _tabela_inexistente(e):
            return False
        raise


def ultima_boa() -> dict | None:
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, criado_em, total_linhas, origem from historico_dados "
                        "where origem <> 'bloqueado' order by criado_em desc limit 1")
            r = cur.fetchone()
        conn.rollback()
    return dict(r) if r else None


def _ultimo_registro_qualquer() -> dict | None:
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, criado_em, origem from historico_dados order by criado_em desc limit 1")
            r = cur.fetchone()
        conn.rollback()
    return dict(r) if r else None


def guardar_copia(origem: str = "automatico", ignorar_trava: bool = False) -> dict:
    """Gera e guarda uma cópia. Devolve {"ok": bool, "id", "motivo", "total", "tamanho"}. Nunca apaga dados do sistema."""
    arquivo, resumo = backup_service.gerar_backup()
    total = int(sum(resumo.values()))
    if len(arquivo) > TAMANHO_MAXIMO:
        return {"ok": False, "motivo": f"cópia grande demais ({len(arquivo) // 1048576} MB)", "total": total}
    anterior = ultima_boa()
    if (not ignorar_trava and anterior and anterior["total_linhas"] >= MINIMO_PARA_COMPARAR
            and total < anterior["total_linhas"] * FRACAO_MINIMA):
        msg = (f"Cópia NÃO guardada: os dados caíram de {anterior['total_linhas']} para {total} linhas "
               f"(menos da metade). O histórico anterior foi preservado.")
        with _ConnCtx() as conn:
            with conn.cursor() as cur:
                cur.execute("insert into historico_dados (origem, total_linhas, resumo, tamanho_bytes, observacao) "
                            "values ('bloqueado', %s, %s, 0, %s)", (total, json.dumps(resumo), msg))
            conn.commit()
        try:
            from app.services import notificacoes_operacionais_service as notif
            notif.avisar_admins("🚨 ALERTA de dados: " + msg + " Entre em Admin > Backup para conferir.")
        except Exception as e:
            print(f"[historico] aviso aos admins falhou: {e}", flush=True)
        return {"ok": False, "motivo": msg, "total": total, "bloqueado": True}
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("insert into historico_dados (origem, total_linhas, resumo, tamanho_bytes, arquivo) "
                        "values (%s, %s, %s, %s, %s) returning id",
                        (origem, total, json.dumps(resumo), len(arquivo), arquivo))
            novo = cur.fetchone()["id"]
        conn.commit()
    limpar_antigas()
    return {"ok": True, "id": novo, "total": total, "tamanho": len(arquivo)}


def limpar_antigas() -> int:
    """Apaga cópias automáticas com mais de 48 h e as extras com mais de 7 dias (só da tabela de histórico)."""
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from historico_dados where origem in ('automatico','bloqueado') "
                        "and criado_em < now() - make_interval(hours => %s)", (HORAS_GUARDAR,))
            n = cur.rowcount
            cur.execute("delete from historico_dados where origem in ('manual','antes_restaurar') "
                        "and criado_em < now() - make_interval(days => %s)", (DIAS_GUARDAR_EXTRAS,))
            n += cur.rowcount
        conn.commit()
    return n


def listar(limite: int = 120) -> list[dict]:
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, criado_em, origem, total_linhas, tamanho_bytes, observacao "
                        "from historico_dados order by criado_em desc limit %s", (limite,))
            linhas = [dict(r) for r in cur.fetchall()]
        conn.rollback()
    return linhas


def obter_arquivo(id_: int) -> tuple[bytes, dict] | None:
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("select id, criado_em, origem, total_linhas, arquivo from historico_dados where id = %s", (id_,))
            r = cur.fetchone()
        conn.rollback()
    if not r or r["arquivo"] is None:
        return None
    return bytes(r["arquivo"]), dict(r)


def restaurar_versao(id_: int) -> dict:
    """Restaura uma versão do histórico. ANTES, guarda uma cópia da versão atual (origem 'antes_restaurar', sem trava).
    Restauração é "mesclar": nada é apagado (ver backup_service.restaurar_backup). Levanta ValueError se não achar."""
    achado = obter_arquivo(int(id_))
    if achado is None:
        raise ValueError("Versão não encontrada (ou é um registro de cópia bloqueada, sem arquivo).")
    arquivo, meta = achado
    pacote = backup_service.ler_arquivo(arquivo)
    seguranca = guardar_copia("antes_restaurar", ignorar_trava=True)
    if not seguranca.get("ok"):
        raise ValueError("Não consegui guardar a cópia de segurança antes de restaurar; nada foi alterado. "
                         f"Motivo: {seguranca.get('motivo')}")
    gravadas = backup_service.restaurar_backup(pacote)
    return {"gravadas": gravadas, "versao": meta, "copia_de_seguranca_id": seguranca["id"]}


# ---------------- agendador (um fio em segundo plano) ----------------
def garantir_copia_recente() -> dict | None:
    """Se a última cópia (ou tentativa bloqueada) tem mais de 1 hora, faz uma nova. Usa trava do Postgres para que só
    um processo faça a cópia (se houver mais de um servidor rodando)."""
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            cur.execute("select pg_try_advisory_lock(%s) as ok", (_LOCK_ID,))
            if not cur.fetchone()["ok"]:
                conn.rollback()
                return None
        try:
            ult = _ultimo_registro_qualquer()
            if ult and (datetime.datetime.now(datetime.timezone.utc) - ult["criado_em"]) < datetime.timedelta(minutes=INTERVALO_MINUTOS - 5):
                return None
            return guardar_copia("automatico")
        finally:
            with conn.cursor() as cur:
                cur.execute("select pg_advisory_unlock(%s)", (_LOCK_ID,))
            conn.commit()


def iniciar_agendador(atraso_inicial: int = 90, a_cada_segundos: int = 600) -> threading.Thread:
    def _loop():
        time.sleep(atraso_inicial)
        while True:
            try:
                r = garantir_copia_recente()
                if r:
                    print(f"[historico] cópia automática: {r}", flush=True)
            except Exception as e:
                if _tabela_inexistente(e):
                    print("[historico] tabela historico_dados ausente -- rode sql/migration_historico_dados.sql", flush=True)
                else:
                    print(f"[historico] erro na cópia automática: {type(e).__name__}: {e}", flush=True)
            time.sleep(a_cada_segundos)
    t = threading.Thread(target=_loop, name="historico-dados", daemon=True)
    t.start()
    return t
