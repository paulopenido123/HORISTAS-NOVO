"""
Importação única dos médicos horistas + histórico de transações extraídos
do sistema real Life Max (lifemaxconsultorios.com.br) para o banco deste
sistema reduzido.

⚠️ IMPORTANTE: rodar `sql/INSTALL_ALL.sql` (ou as migrations) só CRIA as
tabelas/colunas -- não insere nenhum médico. É ESTE script Python aqui
que efetivamente cria os registros dos médicos e o histórico de
transações no banco. Sem rodar ele, os médicos nunca vão aparecer em
"Clientes cadastrados" no admin, mesmo com o schema já atualizado.

Rodar com (usando a MESMA connection string do Neon de PRODUÇÃO -- o
mesmo DATABASE_URL configurado no .env/Render -- senão os médicos são
criados só no banco local de teste, não no banco que o site realmente usa):
    DATABASE_URL="postgresql://...neon.tech/..." FLASK_SECRET_KEY=... ADMIN_PASSWORD=... \
    python3 scripts_migracao/importar_horistas_lifemax.py

O script é seguro de rodar mais de uma vez: antes de criar um médico ele
confere se já existe alguém com aquele telefone (db.get_medico_by_telefone)
e pula quem já estiver cadastrado, em vez de duplicar.

Estratégia de saldo (ver relatório completo entregue ao Paulo em
11/09/2026): o extrato de 198 transações do sistema antigo só registra
créditos/ajustes manuais feitos pela secretária/admin -- NÃO inclui os
débitos de consumo de agendamentos de pacientes (esses ficam em outro
lugar do sistema antigo, não capturado nesta extração). Por isso a soma
das 198 transações não bate com o saldo atual (banco_de_horas_number) de
94 dos 132 médicos.

Solução: replica as transações históricas casadas (193 das 198, pelas
datas originais) para manter o extrato auditável, e fecha com UM
lançamento de conciliação por médico (quando necessário) datado de hoje,
deixando claro que ele existe só para acertar a diferença dos consumos
que não vieram nesse extrato -- o saldo final sempre bate exatamente com
o banco_de_horas_number de origem, que é o valor confiável (saldo
mostrado ao vivo no painel do sistema antigo).
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services import supabase_client as db
from app.services import creditos_service as creditos_db

# Por padrão, os 3 arquivos JSON (horistas_full.json, transacoes_full.json,
# match_info.json) ficam junto deste script, em
# scripts_migracao/dados_extracao_lifemax/ -- assim o script funciona em
# qualquer máquina/servidor onde o projeto for colocado, sem precisar de
# um caminho fixo. Se quiser usar outra pasta, defina a variável de
# ambiente DADOS_EXTRACAO_LIFEMAX_DIR antes de rodar.
DADOS_DIR = os.getenv(
    "DADOS_EXTRACAO_LIFEMAX_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_extracao_lifemax"),
)


def carregar(nome):
    with open(os.path.join(DADOS_DIR, nome), encoding="utf-8") as f:
        return json.load(f)


def ms_para_iso(ms):
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat()


def main():
    app = create_app()
    with app.app_context():
        horistas = carregar("horistas_full.json")
        transacoes = carregar("transacoes_full.json")
        match_info = carregar("match_info.json")

        preco_hora = creditos_db.preco_hora_avulsa()
        if not preco_hora:
            print("ERRO: preço da hora avulsa não configurado (tabela pacotes_horas vazia). Abortando.")
            sys.exit(1)
        print(f"Preço da hora avulsa usado na conversão: R$ {preco_hora:.2f}/h")

        criados = []
        pulados_sem_telefone = []
        falhas = []

        for h in horistas:
            telefone = h.get("telefone_e164") or ""
            if not telefone:
                pulados_sem_telefone.append(h["nome"])
                continue
            if db.get_medico_by_telefone(telefone) is not None:
                falhas.append(f"{h['nome']} ({telefone}): telefone já cadastrado no sistema, pulei.")
                continue
            try:
                medico = db.criar_medico(
                    nome=h["nome"].strip(),
                    telefone=telefone,
                    especialidade="",
                    tipo_vinculo="horista",
                    email=h.get("email") or "",
                    cpf_cnpj=h.get("cpf") or "",
                    endereco_cep=(h.get("cep") or "")[:9],
                    endereco_rua=h.get("endereco1") or "",
                    endereco_complemento=h.get("endereco2") or "",
                    endereco_bairro=h.get("bairro") or "",
                    endereco_cidade=h.get("cidade") or "",
                    endereco_estado=(h.get("estado") or "").strip()[:2].upper(),
                    autorizado=bool(h.get("autorizado")),
                )
            except Exception as e:
                falhas.append(f"{h['nome']} ({telefone}): erro ao criar -- {e}")
                continue

            # marca termo de uso como aceito -- são clientes que já usam o
            # sistema antigo há tempo, não faz sentido barrar no termo de
            # novo (mesmo padrão usado nos seeds anteriores dessa sessão)
            db.get_client().table("medicos").update({"termo_aceito": True}).eq("id", medico["id"]).execute()

            criados.append((h, medico))

        print(f"\nMédicos criados: {len(criados)}")
        if pulados_sem_telefone:
            print(f"Pulados por falta de telefone ({len(pulados_sem_telefone)}): {', '.join(pulados_sem_telefone)}")
        if falhas:
            print(f"Falhas ({len(falhas)}):")
            for f in falhas:
                print("  -", f)

        # ---------- Histórico de transações ----------
        txs_por_medico = {}
        for t in transacoes:
            info = match_info.get(t["id"])
            if not info:
                continue
            txs_por_medico.setdefault(info["medico_id"], []).append(t)

        total_tx_importadas = 0
        total_ajustes_conciliacao = 0
        medico_por_id_origem = {h["id"]: medico for h, medico in criados}

        client = db.get_client()

        for h, medico in criados:
            lista = sorted(txs_por_medico.get(h["id"], []), key=lambda t: t["criado_em"])
            saldo_horas_corrente = 0.0
            saldo_reais_corrente = 0.0

            for t in lista:
                saldo_horas_corrente += t["horas"]
                valor = round(t["horas"] * preco_hora, 2)
                saldo_reais_corrente = round(saldo_reais_corrente + valor, 2)
                data_original = ms_para_iso(t["criado_em"])
                client.table("creditos_transacoes").insert({
                    "medico_id": medico["id"],
                    "tipo": "ajuste",
                    "valor": valor,
                    "saldo_apos": saldo_reais_corrente,
                    "descricao": (
                        f"Migrado do sistema Life Max (lançamento original de "
                        f"{t['criado_em_fmt']}, operador: {t['operador']})"
                    ),
                    "quantidade_horas": t["horas"],
                    "categoria": "horas",
                    "carteira": "salas",
                    "criado_em": data_original,
                }).execute()
                total_tx_importadas += 1

            # conciliação: acerta pro saldo final CORRETO (banco_de_horas_number,
            # valor ao vivo no sistema antigo -- fonte da verdade)
            saldo_horas_alvo = h["banco_de_horas"]
            diferenca_horas = round(saldo_horas_alvo - saldo_horas_corrente, 2)
            if abs(diferenca_horas) > 0.0001:
                valor_ajuste = round(diferenca_horas * preco_hora, 2)
                saldo_reais_corrente = round(saldo_reais_corrente + valor_ajuste, 2)
                client.table("creditos_transacoes").insert({
                    "medico_id": medico["id"],
                    "tipo": "ajuste",
                    "valor": valor_ajuste,
                    "saldo_apos": saldo_reais_corrente,
                    "descricao": (
                        "Ajuste de conciliação — o extrato de transações do sistema antigo só "
                        "tinha os créditos manuais, não os consumos de agendamentos de pacientes; "
                        "este lançamento fecha o saldo exatamente no valor que estava ativo no "
                        "sistema antigo (banco de horas) no momento da migração (11/09/2026)."
                    ),
                    "quantidade_horas": diferenca_horas,
                    "categoria": "horas",
                    "carteira": "salas",
                }).execute()
                total_ajustes_conciliacao += 1

            # saldo_creditos final do médico = saldo_reais_corrente
            client.table("medicos").update({"saldo_creditos": saldo_reais_corrente}).eq("id", medico["id"]).execute()

        print(f"\nTransações históricas importadas: {total_tx_importadas} / {len(transacoes)}")
        print(f"Ajustes de conciliação aplicados: {total_ajustes_conciliacao}")

        nao_casadas = [t for t in transacoes if t["id"] not in match_info]
        if nao_casadas:
            print(f"\nTransações NÃO importadas (cliente não corresponde a nenhum médico horista atual, {len(nao_casadas)}):")
            for t in nao_casadas:
                print(f"  - {t['cliente']!r}: {t['horas']}h em {t['criado_em_fmt']} (operador: {t['operador']})")

        # ---------- conferência final ----------
        print("\n=== Conferência final (saldo no banco == banco_de_horas do sistema antigo) ===")
        divergentes = 0
        for h, medico in criados:
            saldo_horas_final = creditos_db.saldo_em_horas_medico(medico["id"])
            if saldo_horas_final != h["banco_de_horas"]:
                divergentes += 1
                print(f"  DIVERGENTE: {h['nome']} -> banco={saldo_horas_final}h, esperado={h['banco_de_horas']}h")
        if divergentes == 0:
            print("Todos os saldos batem exatamente com o sistema antigo. ✔")
        else:
            print(f"{divergentes} médico(s) com saldo divergente -- revisar.")

        print("\nImportação concluída.")


if __name__ == "__main__":
    main()
