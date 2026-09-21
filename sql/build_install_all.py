#!/usr/bin/env python3
"""
Gera sql/INSTALL_ALL.sql a partir dos arquivos individuais desta mesma
pasta (schema.sql + migration_*.sql), concatenados numa ordem que
respeita as dependências reais entre eles.

Rode isso sempre que adicionar/editar um migration_*.sql -- não edite
INSTALL_ALL.sql à mão, ele é gerado.

Uso:
    python3 sql/build_install_all.py

Ordem: por padrão seria a ordem alfabética dos nomes de arquivo (como
era feito manualmente antes), mas 4 migrações têm uma dependência real
numa migração que viria DEPOIS delas alfabeticamente -- confirmado
rodando o SQL contra um Postgres local de verdade em 10/09/2026 (não é
suposição, são erros reais de "relation does not exist"/"column does
not exist"):

  - migration_horarios_turno_v2.sql usa a coluna tipo_reserva (criada em
    migration_precos_horas.sql) e depende também de
    migration_protecao_conflito.sql (intervalo_ocupado/EXCLUDE).
  - migration_primeiro_acesso_admin.sql altera tokens_recuperacao_senha
    (criada em migration_recuperacao_senha.sql).
  - migration_prontuario_melhorias.sql altera prontuarios (criada em
    migration_prontuarios.sql).
  - migration_recuperacao_senha.sql altera secretarias (criada em
    migration_secretarias.sql).

EXTRA_DEPS abaixo captura só essas 4 exceções; tudo mais segue a ordem
alfabética normal (igual sempre foi).
"""
import pathlib
import sys
from collections import defaultdict
import heapq

SQL_DIR = pathlib.Path(__file__).parent
OUT_FILE = SQL_DIR / "INSTALL_ALL.sql"

# (antes, depois) -- "antes" tem que aparecer no arquivo final antes de "depois"
EXTRA_DEPS = [
    ("migration_precos_horas.sql", "migration_protecao_conflito.sql"),
    ("migration_precos_horas.sql", "migration_horarios_turno_v2.sql"),
    ("migration_protecao_conflito.sql", "migration_horarios_turno_v2.sql"),
    ("migration_secretarias.sql", "migration_recuperacao_senha.sql"),
    ("migration_recuperacao_senha.sql", "migration_primeiro_acesso_admin.sql"),
    ("migration_prontuarios.sql", "migration_prontuario_melhorias.sql"),
    # migration_ia_percentual_200.sql faz "update precos set
    # ia_percentual_aumento = 200" -- essa coluna só existe depois que
    # migration_ia_precos.sql roda (ela que cria a coluna com "alter
    # table ... add column"). Sem essa dependência explícita, a ordem
    # alfabética colocaria "ia_percentual_200" ANTES de "ia_precos"
    # (por causa do "e" < "r"), o que quebraria o UPDATE.
    ("migration_ia_precos.sql", "migration_ia_percentual_200.sql"),
]

DELIM = "-- " + "=" * 60


def main():
    arquivos = sorted(p.name for p in SQL_DIR.glob("*.sql") if p.name != "INSTALL_ALL.sql")
    if "schema.sql" not in arquivos:
        print("ERRO: schema.sql não encontrado em sql/", file=sys.stderr)
        sys.exit(1)
    arquivos.remove("schema.sql")
    # migration_matriz_admin_reservas.sql sempre foi colocado por último de
    # propósito (era assim no INSTALL_ALL.sql original, e o próprio arquivo
    # confirma isso: ele altera/depende de tabelas de vários outros módulos
    # -- é a migração "de cima de tudo"). Alfabeticamente ele cairia no meio
    # (começa com "m"), então tira ele da lista alfabética e recoloca por
    # último manualmente, em vez de confiar só em EXTRA_DEPS pra isso.
    ULTIMO = "migration_matriz_admin_reservas.sql"
    if ULTIMO in arquivos:
        arquivos.remove(ULTIMO)
        ordem_alfabetica = ["schema.sql"] + arquivos + [ULTIMO]
    else:
        ordem_alfabetica = ["schema.sql"] + arquivos
    pos_alfabetica = {nome: i for i, nome in enumerate(ordem_alfabetica)}

    for a, b in EXTRA_DEPS:
        if a not in pos_alfabetica or b not in pos_alfabetica:
            print(f"ERRO: dependência extra referencia arquivo inexistente: {a} / {b}", file=sys.stderr)
            sys.exit(1)

    # Kahn com desempate pela ordem alfabética -- só sai da ordem
    # alfabética onde uma dependência de EXTRA_DEPS obriga.
    adj = defaultdict(set)
    indeg = {nome: 0 for nome in ordem_alfabetica}
    for a, b in EXTRA_DEPS:
        if b not in adj[a]:
            adj[a].add(b)
            indeg[b] += 1

    heap = [(pos_alfabetica[n], n) for n in ordem_alfabetica if indeg[n] == 0]
    heapq.heapify(heap)
    ordem_final = []
    while heap:
        _, nome = heapq.heappop(heap)
        ordem_final.append(nome)
        for nxt in adj[nome]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, (pos_alfabetica[nxt], nxt))

    if len(ordem_final) != len(ordem_alfabetica):
        faltando = set(ordem_alfabetica) - set(ordem_final)
        print(f"ERRO: ciclo de dependências, sobraram: {faltando}", file=sys.stderr)
        sys.exit(1)

    # valida as dependências na saída
    pos_final = {nome: i for i, nome in enumerate(ordem_final)}
    for a, b in EXTRA_DEPS:
        assert pos_final[a] < pos_final[b], f"{a} deveria vir antes de {b}"

    partes = [
        "-- ============================================================\n"
        "-- INSTALL_ALL.sql -- GERADO AUTOMATICAMENTE por build_install_all.py\n"
        "-- NÃO EDITE ESTE ARQUIVO À MÃO -- edite o migration_*.sql\n"
        "-- correspondente e rode `python3 sql/build_install_all.py` de novo.\n"
        "--\n"
        "-- schema.sql primeiro; migrations depois, na ordem que respeita\n"
        "-- as dependências entre elas (ver EXTRA_DEPS em build_install_all.py).\n"
        "-- ============================================================\n"
    ]
    for nome in ordem_final:
        conteudo = (SQL_DIR / nome).read_text(encoding="utf-8")
        partes.append(f"\n{DELIM}\n-- {nome}\n{DELIM}\n\n{conteudo}\n")

    OUT_FILE.write_text("".join(partes), encoding="utf-8")
    print(f"OK: {OUT_FILE} gerado com {len(ordem_final)} seções.")
    mudou = [n for n in ordem_alfabetica if pos_alfabetica[n] != pos_final[n]]
    if mudou:
        print("Arquivos fora da ordem alfabética (por causa de EXTRA_DEPS):")
        for n in mudou:
            print(f"  {n}: alfabética={pos_alfabetica[n]} -> final={pos_final[n]}")


if __name__ == "__main__":
    main()
