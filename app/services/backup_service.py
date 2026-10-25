"""
Backup e restauração de TODOS os dados do banco (pedido do Paulo em
25/10/2026): médicos, reservas, pagamentos, consultórios, usuários admin,
fotos guardadas no banco -- tudo que está no schema "public".

Formato: JSON compactado (.json.gz) com metadados + linhas de cada tabela.
Os tipos que o JSON não tem (data/hora, decimal, bytea, uuid) são gravados
como texto (bytea em base64, marcado) e voltam ao tipo certo na restauração,
usando o tipo da coluna lido do próprio banco.

Restauração = "mesclar": cada linha do backup é inserida e, se o id já
existir, é SOBRESCRITA pelo valor do backup (upsert pela chave primária).
NADA é apagado -- registros criados depois do backup continuam lá. Tudo
numa única transação: se algo falhar, nada é alterado.
"""
import base64
import datetime
import decimal
import gzip
import io
import json
import uuid
import psycopg2.extras
from app.services.pg_query import _ConnCtx

VERSAO_FORMATO = 1
_MARCA_B64 = "__b64__"


def _tabelas(cur) -> list[str]:
    cur.execute("""select table_name from information_schema.tables
                   where table_schema='public' and table_type='BASE TABLE' order by table_name""")
    return [r["table_name"] for r in cur.fetchall()]


def _colunas(cur, tabela: str) -> dict:
    cur.execute("""select column_name, data_type, udt_name from information_schema.columns
                   where table_schema='public' and table_name=%s order by ordinal_position""", (tabela,))
    return {r["column_name"]: (r["data_type"], r["udt_name"]) for r in cur.fetchall()}


def _chave_primaria(cur, tabela: str) -> list[str]:
    cur.execute("""select a.attname from pg_index i
                   join pg_attribute a on a.attrelid=i.indrelid and a.attnum = any(i.indkey)
                   where i.indrelid = %s::regclass and i.indisprimary""", (f'public."{tabela}"',))
    return [r["attname"] for r in cur.fetchall()]


def _ordem_por_dependencia(cur, tabelas: list[str]) -> list[str]:
    """Ordena para que tabelas "pai" sejam gravadas antes das que apontam
    pra elas (chaves estrangeiras). Ciclos (raros) vão para o fim."""
    cur.execute("""select tc.table_name as filho, ccu.table_name as pai
                   from information_schema.table_constraints tc
                   join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name
                   where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public'""")
    deps = {t: set() for t in tabelas}
    for r in cur.fetchall():
        if r["filho"] in deps and r["pai"] in deps and r["filho"] != r["pai"]:
            deps[r["filho"]].add(r["pai"])
    ordem, restantes = [], dict(deps)
    while restantes:
        prontas = sorted(t for t, d in restantes.items() if not (d - set(ordem)))
        if not prontas:
            ordem.extend(sorted(restantes)); break
        ordem.extend(prontas)
        for t in prontas:
            restantes.pop(t)
    return ordem


def _para_json(v):
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (decimal.Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {_MARCA_B64: base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, datetime.timedelta):
        return str(v)
    # Colunas de intervalo (tstzrange/daterange/int4range... -- ex.: exclusão
    # de reservas sobrepostas): vira o literal de texto do Postgres, que ele
    # mesmo aceita de volta na restauração (ex.: '["2026-11-01T08:00:00+00:00","2026-11-01T09:00:00+00:00")').
    if hasattr(v, "lower") and hasattr(v, "upper") and hasattr(v, "isempty") and not isinstance(v, str):
        if v.isempty:
            return "empty"
        lim = lambda x: "" if x is None else '"' + (x.isoformat() if hasattr(x, "isoformat") else str(x)) + '"'
        return f"{v._bounds[0]}{lim(v.lower)},{lim(v.upper)}{v._bounds[1]}"
    if isinstance(v, (set, frozenset)):
        return sorted(_para_json(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_para_json(x) for x in v]
    if isinstance(v, dict):
        return {k: _para_json(x) for k, x in v.items()}
    return v


def gerar_backup() -> tuple[bytes, dict]:
    """Devolve (arquivo .json.gz em bytes, resumo {tabela: nº de linhas})."""
    dados, resumo = {}, {}
    with _ConnCtx() as conn:
        with conn.cursor() as cur:
            for t in _tabelas(cur):
                cur.execute(f'select * from public."{t}"')
                linhas = [{k: _para_json(v) for k, v in r.items()} for r in cur.fetchall()]
                dados[t] = linhas
                resumo[t] = len(linhas)
        conn.rollback()
    pacote = {
        "sistema": "lifemax", "versao_formato": VERSAO_FORMATO,
        "gerado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "resumo": resumo, "tabelas": dados,
    }
    bruto = json.dumps(pacote, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    saida = io.BytesIO()
    with gzip.GzipFile(fileobj=saida, mode="wb", compresslevel=6) as gz:
        gz.write(bruto)
    return saida.getvalue(), resumo


def ler_arquivo(conteudo: bytes) -> dict:
    """Lê e valida um arquivo de backup (.json.gz ou .json). Levanta ValueError."""
    try:
        if conteudo[:2] == b"\x1f\x8b":
            conteudo = gzip.decompress(conteudo)
        pacote = json.loads(conteudo.decode("utf-8"))
    except Exception:
        raise ValueError("Arquivo inválido: não é um backup do Lifemax.")
    if not isinstance(pacote, dict) or pacote.get("sistema") != "lifemax" or not isinstance(pacote.get("tabelas"), dict):
        raise ValueError("Arquivo inválido: não é um backup do Lifemax.")
    if pacote.get("versao_formato") != VERSAO_FORMATO:
        raise ValueError("Versão do arquivo de backup não é compatível com este sistema.")
    return pacote


def _valor_para_banco(v, tipo, udt):
    if v is None:
        return None
    if isinstance(v, dict) and _MARCA_B64 in v:
        return psycopg2.Binary(base64.b64decode(v[_MARCA_B64]))
    if tipo in ("json", "jsonb"):
        return psycopg2.extras.Json(v)
    return v


def restaurar_backup(pacote: dict) -> dict:
    """Mescla o backup no banco (upsert por chave primária), numa transação
    só. Devolve {tabela: nº de linhas gravadas}. Levanta ValueError em caso
    de problema (e nada é alterado)."""
    gravadas = {}
    with _ConnCtx() as conn:
        try:
            with conn.cursor() as cur:
                existentes = _tabelas(cur)
                no_arquivo = [t for t in pacote["tabelas"] if t in existentes]
                for t in _ordem_por_dependencia(cur, no_arquivo):
                    linhas = pacote["tabelas"][t]
                    if not linhas:
                        gravadas[t] = 0; continue
                    cols_banco = _colunas(cur, t)
                    pk = _chave_primaria(cur, t)
                    cols = [c for c in linhas[0].keys() if c in cols_banco]
                    if not cols:
                        continue
                    lista = ", ".join(f'"{c}"' for c in cols)
                    marcas = ", ".join(["%s"] * len(cols))
                    if pk and all(c in cols for c in pk):
                        atualizar = [c for c in cols if c not in pk]
                        conflito = (", ".join(f'"{c}"' for c in pk))
                        acao = ("do update set " + ", ".join(f'"{c}"=excluded."{c}"' for c in atualizar)) if atualizar else "do nothing"
                        sql = f'insert into public."{t}" ({lista}) values ({marcas}) on conflict ({conflito}) {acao}'
                    else:
                        sql = f'insert into public."{t}" ({lista}) values ({marcas}) on conflict do nothing'
                    n = 0
                    for r in linhas:
                        cur.execute(sql, [_valor_para_banco(r.get(c), *cols_banco[c]) for c in cols])
                        n += 1
                    gravadas[t] = n
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise ValueError(f"Falha ao restaurar (nada foi alterado): {e}")
    return gravadas
