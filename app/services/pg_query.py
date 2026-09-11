"""
"Tradutor" entre o jeito de escrever consultas do cliente Python do
Supabase (aquele encadeamento .table().select().eq()...execute().data,
chamado de PostgREST) e SQL de verdade rodado direto no Postgres via
psycopg2.

Por quê isso existe: quando o sistema usava Supabase, TODO o código de
`app/services/supabase_client.py` (e mais ~15 outros arquivos) foi escrito
chamando `get_client().table("medicos").select("*").eq("id", x).execute().data`
-- são mais de 130 lugares assim espalhados pelo projeto. Na migração pra
Neon (Postgres puro, sem o PostgREST do Supabase por cima), reescrever
essas 130+ chamadas uma por uma seria arriscado demais pra revisar. Em vez
disso, esse arquivo recria a MESMA interface encadeada (classe
`QueryBuilder`, com os mesmos métodos: select/eq/neq/gte/lte/gt/lt/ilike/
in_/is_/not_/order/limit/insert/update/upsert/delete/execute), só que por
baixo dos panos ela monta e roda SQL real com psycopg2. Assim o resto do
código nem percebe a troca.

Suporta também a sintaxe de "join automático" do PostgREST usada no
projeto, tipo `.select("*, medicos(nome)")` -- isso vira duas consultas
(a principal + uma busca dos relacionados pelos ids encontrados), porque
não dá pra fazer JOIN de verdade sem reescrever a query inteira à mão, e
isso é rápido o suficiente pro volume de dados desse sistema.

IMPORTANTE: essa classe cobre só os métodos/padrões que o projeto REALMENTE
usa hoje (conferido com grep em todo o app/ antes de escrever isso). Se um
código novo usar um método do Supabase que não está aqui, ele vai receber
um AttributeError na hora -- de propósito, pra não silenciosamente devolver
dado errado.
"""
import datetime
import re
import threading
from decimal import Decimal
import psycopg2
import psycopg2.extras
import psycopg2.pool

_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from app.config import Config
                if not Config.DATABASE_URL:
                    raise RuntimeError(
                        "DATABASE_URL não configurada -- veja .env.example. "
                        "É a connection string do seu banco Neon."
                    )
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=10, dsn=Config.DATABASE_URL,
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
    return _pool


class _ConnCtx:
    """Empresta uma conexão do pool e devolve no fim (with _ConnCtx() as conn:).

    O Neon é "serverless": o compute pode ser suspenso depois de um tempo
    sem uso, e isso derruba qualquer conexão que estivesse esperando
    ociosa dentro do nosso pool -- na próxima vez que essa conexão for
    emprestada, ela já está morta. Por isso: (1) se pegarmos do pool uma
    conexão que já está marcada como fechada, descarta e pega outra na
    hora, sem nem tentar usar; (2) se um erro de conexão acontecer
    DURANTE o uso (ver comentário em `execute()`), a conexão suspeita é
    descartada (`close=True`) em vez de devolvida pro pool pra não
    envenenar o próximo empréstimo."""
    def __enter__(self):
        pool = _get_pool()
        self._conn = pool.getconn()
        if self._conn.closed:
            pool.putconn(self._conn, close=True)
            self._conn = pool.getconn()
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        pool = _get_pool()
        conexao_suspeita = exc_type is not None and issubclass(exc_type, psycopg2.OperationalError)
        if exc_type is not None and not conexao_suspeita:
            try:
                self._conn.rollback()
            except Exception:
                pass
        pool.putconn(self._conn, close=conexao_suspeita)


# Singular "ingênuo" de um nome de tabela em português -- funciona pros
# relacionamentos usados hoje no projeto (medicos, consultorios, empresas
# -- todos plurais regulares). Se um dia aparecer uma tabela com plural
# irregular num select embutido, ajuste esse dicionário em vez de mexer
# na lógica.
_SINGULAR_IRREGULAR = {
    # "nome_da_tabela": "prefixo_da_coluna_fk"
}


def _fk_coluna_para(nome_tabela_relacionada: str) -> str:
    if nome_tabela_relacionada in _SINGULAR_IRREGULAR:
        return _SINGULAR_IRREGULAR[nome_tabela_relacionada] + "_id"
    if nome_tabela_relacionada.endswith("s"):
        return nome_tabela_relacionada[:-1] + "_id"
    return nome_tabela_relacionada + "_id"


def _split_top_level_commas(s: str) -> list[str]:
    """Divide uma string tipo 'a, b(c, d), e' nas vírgulas de fora dos
    parênteses -- devolve ['a', 'b(c, d)', 'e']."""
    partes = []
    atual = []
    profundidade = 0
    for ch in s:
        if ch == "(":
            profundidade += 1
            atual.append(ch)
        elif ch == ")":
            profundidade -= 1
            atual.append(ch)
        elif ch == "," and profundidade == 0:
            partes.append("".join(atual).strip())
            atual = []
        else:
            atual.append(ch)
    if atual:
        partes.append("".join(atual).strip())
    return [p for p in partes if p]


_EMBED_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)$")


class _Response:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


def _normalize_value(v):
    """O Supabase (via PostgREST) sempre devolvia dado já convertido pra
    JSON: data/timestamp como string ISO, numeric como número comum
    (float), etc. O psycopg2 devolve os tipos "nativos" do Python
    (datetime.date, datetime.datetime, decimal.Decimal, e até um objeto
    de range pra coluna gerada tipo intervalo_ocupado) -- se não converter
    aqui, o resto do código quebra de duas formas: (1) qualquer código que
    espera string e chama .split("-") num campo de data (tem pelo menos
    um caso assim, resumo_financeiro_medico) recebe AttributeError porque
    datetime.date não tem .split(); (2) jsonify() do Flask não sabe
    serializar Decimal nem os tipos exóticos do psycopg2, e quebra a
    resposta de qualquer rota de API que devolva a linha direto."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _normalize_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_normalize_value(item) for item in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    # Tipo que não reconhecemos (ex: Range do psycopg2 pra colunas geradas
    # como intervalo_ocupado) -- nenhum código do projeto lê essas colunas
    # diretamente (conferido via grep), mas por segurança vira string em
    # vez de quebrar a serialização JSON.
    return str(v)


def _normalize_row(row: dict) -> dict:
    return {k: _normalize_value(v) for k, v in row.items()}


class QueryBuilder:
    def __init__(self, table: str):
        self._table = table
        self._select_cols: list[str] = ["*"]
        self._embeds: list[tuple[str, str, list[str]]] = []  # (relacao, fk_col, cols)
        self._filters: list[tuple[str, str, object]] = []  # (coluna, operador_sql, valor)
        self._order: list[tuple[str, bool]] = []
        self._limit_n: int | None = None
        self._op: str | None = None
        self._payload = None
        self._on_conflict: str | None = None
        self._negate_next = False

    # ---------------------------------------------------------------
    # Seleção de colunas / relacionamentos embutidos
    # ---------------------------------------------------------------
    def select(self, cols: str = "*"):
        if self._op is None:
            self._op = "select"
        partes = _split_top_level_commas(cols)
        base_cols = []
        embeds = []
        for parte in partes:
            m = _EMBED_RE.match(parte)
            if m:
                relacao = m.group(1)
                sub_cols_raw = [c.strip() for c in m.group(2).split(",") if c.strip()]
                if "id" not in sub_cols_raw:
                    sub_cols_raw = ["id"] + sub_cols_raw
                fk_col = _fk_coluna_para(relacao)
                embeds.append((relacao, fk_col, sub_cols_raw))
            else:
                base_cols.append(parte)
        self._select_cols = base_cols or ["*"]
        self._embeds = embeds
        return self

    # ---------------------------------------------------------------
    # Filtros
    # ---------------------------------------------------------------
    def _add_filter(self, col, op, val):
        if self._negate_next:
            self._negate_next = False
            if op == "IS":
                op = "IS NOT"
            else:
                # Só ".not_.is_(...)" é usado no projeto hoje (conferido
                # via grep) -- se algum código novo tentar negar outro
                # tipo de filtro, falha alto e claro em vez de montar um
                # SQL inválido ou silenciosamente errado.
                raise NotImplementedError(
                    f'.not_ ainda não tem suporte combinado com esse filtro (op="{op}") -- '
                    "adicione o caso em pg_query.py."
                )
        self._filters.append((col, op, val))
        return self

    def eq(self, col, val):
        return self._add_filter(col, "=", val)

    def neq(self, col, val):
        return self._add_filter(col, "!=", val)

    def gt(self, col, val):
        return self._add_filter(col, ">", val)

    def gte(self, col, val):
        return self._add_filter(col, ">=", val)

    def lt(self, col, val):
        return self._add_filter(col, "<", val)

    def lte(self, col, val):
        return self._add_filter(col, "<=", val)

    def ilike(self, col, pattern):
        return self._add_filter(col, "ILIKE", pattern)

    def like(self, col, pattern):
        return self._add_filter(col, "LIKE", pattern)

    def in_(self, col, values):
        return self._add_filter(col, "IN", tuple(values) if values else tuple())

    def is_(self, col, val):
        real_val = None if val in (None, "null") else val
        return self._add_filter(col, "IS", real_val)

    def contains(self, col, val):
        return self._add_filter(col, "@>", val)

    @property
    def not_(self):
        self._negate_next = True
        return self

    def order(self, col, desc: bool = False):
        self._order.append((col, desc))
        return self

    def limit(self, n: int):
        self._limit_n = n
        return self

    # ---------------------------------------------------------------
    # Operações de escrita
    # ---------------------------------------------------------------
    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def upsert(self, payload, on_conflict: str | None = None):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    # ---------------------------------------------------------------
    # Montagem de SQL
    # ---------------------------------------------------------------
    def _where_clause(self):
        if not self._filters:
            return "", []
        pedacos = []
        params = []
        for col, op, val in self._filters:
            if op == "IN":
                if not val:
                    # IN () é inválido em SQL -- uma lista vazia nunca bate
                    # com nada, então força a condição a nunca casar.
                    pedacos.append("1=0")
                    continue
                pedacos.append(f'"{col}" IN %s')
                params.append(val)
            elif op in ("IS", "IS NOT"):
                pedacos.append(f'"{col}" {op} NULL' if val is None else f'"{col}" {op} %s')
                if val is not None:
                    params.append(val)
            else:
                pedacos.append(f'"{col}" {op} %s')
                params.append(val)
        return " WHERE " + " AND ".join(pedacos), params

    def _order_limit_clause(self):
        sql = ""
        if self._order:
            partes = [f'"{col}" {"DESC" if desc else "ASC"}' for col, desc in self._order]
            sql += " ORDER BY " + ", ".join(partes)
        if self._limit_n is not None:
            sql += f" LIMIT {int(self._limit_n)}"
        return sql

    def _build_select(self):
        cols_sql = ", ".join(self._select_cols) if self._select_cols != ["*"] else "*"
        where_sql, params = self._where_clause()
        sql = f'SELECT {cols_sql} FROM "{self._table}"{where_sql}{self._order_limit_clause()}'
        return sql, params

    def _build_insert(self):
        rows = self._payload if isinstance(self._payload, list) else [self._payload]
        cols = list(rows[0].keys())
        valores_sql = []
        params = []
        for row in rows:
            valores_sql.append("(" + ", ".join(["%s"] * len(cols)) + ")")
            params.extend(row.get(c) for c in cols)
        cols_sql = ", ".join(f'"{c}"' for c in cols)
        sql = f'INSERT INTO "{self._table}" ({cols_sql}) VALUES {", ".join(valores_sql)} RETURNING *'
        return sql, params

    def _build_update(self):
        cols = list(self._payload.keys())
        set_sql = ", ".join(f'"{c}" = %s' for c in cols)
        params = [self._payload[c] for c in cols]
        where_sql, where_params = self._where_clause()
        sql = f'UPDATE "{self._table}" SET {set_sql}{where_sql} RETURNING *'
        return sql, params + where_params

    def _build_delete(self):
        where_sql, params = self._where_clause()
        sql = f'DELETE FROM "{self._table}"{where_sql} RETURNING *'
        return sql, params

    def _build_upsert(self):
        rows = self._payload if isinstance(self._payload, list) else [self._payload]
        cols = list(rows[0].keys())
        valores_sql = []
        params = []
        for row in rows:
            valores_sql.append("(" + ", ".join(["%s"] * len(cols)) + ")")
            params.extend(row.get(c) for c in cols)
        cols_sql = ", ".join(f'"{c}"' for c in cols)
        conflict_cols_str = self._on_conflict or "id"
        conflict_cols_set = {c.strip() for c in conflict_cols_str.split(",")}
        conflict_sql = ", ".join(f'"{c}"' for c in conflict_cols_set)
        update_sql = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in conflict_cols_set)
        sql = (
            f'INSERT INTO "{self._table}" ({cols_sql}) VALUES {", ".join(valores_sql)} '
            f'ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql} RETURNING *'
        )
        return sql, params

    # ---------------------------------------------------------------
    # Execução
    # ---------------------------------------------------------------
    def _attach_embeds(self, rows, cur):
        for relacao, fk_col, sub_cols in self._embeds:
            ids = {r.get(fk_col) for r in rows if r.get(fk_col) is not None}
            mapa = {}
            if ids:
                cols_sql = ", ".join(f'"{c}"' for c in sub_cols)
                cur.execute(
                    f'SELECT {cols_sql} FROM "{relacao}" WHERE "id" IN %s',
                    (tuple(ids),),
                )
                for rel_row in cur.fetchall():
                    mapa[rel_row["id"]] = dict(rel_row)
            for r in rows:
                r[relacao] = mapa.get(r.get(fk_col))

    def execute(self):
        op = self._op or "select"
        if op == "select":
            sql, params = self._build_select()
        elif op == "insert":
            sql, params = self._build_insert()
        elif op == "update":
            sql, params = self._build_update()
        elif op == "delete":
            sql, params = self._build_delete()
        elif op == "upsert":
            sql, params = self._build_upsert()
        else:
            raise RuntimeError(f"Operação desconhecida: {op}")

        # O Neon pode suspender o compute por inatividade e derrubar
        # conexões que ficaram esperando no pool -- a próxima tentativa de
        # usar uma delas dá "SSL connection has been closed unexpectedly"
        # (aconteceu de verdade em produção, 10/09/2026, abrindo o painel
        # admin depois do servidor ficar um tempo parado). Em vez de
        # quebrar a requisição do usuário por causa disso, tenta de novo
        # automaticamente UMA vez com uma conexão nova -- cobre exatamente
        # esse caso sem mascarar um erro de banco de verdade (se falhar de
        # novo na segunda tentativa, aí sim propaga o erro).
        ultima_excecao = None
        for _tentativa in range(2):
            try:
                with _ConnCtx() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        if cur.description is not None:
                            rows = [dict(r) for r in cur.fetchall()]
                        else:
                            rows = []
                        if op == "select" and self._embeds and rows:
                            self._attach_embeds(rows, cur)
                    conn.commit()
                rows = [_normalize_row(r) for r in rows]
                return _Response(rows)
            except psycopg2.OperationalError as e:
                ultima_excecao = e
                continue
        raise ultima_excecao


class PgClient:
    """Substitui o `supabase.Client` -- só o suficiente pra cobrir o que o
    projeto usa: `.table(nome)` pra consultas, e `.storage` fica de fora
    de propósito (o Supabase Storage foi trocado pelo Neon Object Storage,
    veja app/services/neon_storage.py -- se algum código ainda chamar
    `.storage` a partir daqui, é sinal de uma chamada que não foi migrada,
    por isso NÃO existe esse atributo aqui, pra dar erro alto e claro)."""

    def table(self, nome: str) -> QueryBuilder:
        return QueryBuilder(nome)
