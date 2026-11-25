"""
API SOMENTE LEITURA para o sistema financeiro (hospedado na Netlify) buscar a receita mensal da Biomax (v127).

GET /api/financeiro/receitas-mensais?de=AAAA-MM&ate=AAAA-MM   (sem parâmetros: últimos 12 meses, incluindo o atual)
Cabeçalho obrigatório: Authorization: Bearer <FINANCEIRO_API_TOKEN>

- FINANCEIRO_API_TOKEN não configurado no servidor -> 503 (rota desligada).
- Sem cabeçalho ou chave errada -> 401 {"erro": "não autorizado"} (comparação em tempo constante).
- Os totais vêm da MESMA função do relatório "Receitas" do admin (relatorios_service.listar_receitas), então batem sempre.
- Só totais por mês: nenhum dado de cliente. Não grava nada no banco. Sem CORS (quem chama é um servidor).
"""
import hmac
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from app.config import Config
from app.extensions import limiter
from app.services import relatorios_service

api_financeiro_bp = Blueprint("api_financeiro", __name__, url_prefix="/api/financeiro")

_FUSO_SP = timezone(timedelta(hours=-3))
_MAX_MESES = 60


def _token_valido() -> bool:
    enviado = request.headers.get("Authorization", "")
    if not enviado.startswith("Bearer "):
        return False
    chave = enviado[7:].strip().encode("utf-8")
    return hmac.compare_digest(chave, (Config.FINANCEIRO_API_TOKEN or "").encode("utf-8"))


def _ultimos_12(hoje) -> tuple[str, str]:
    a, m = hoje.year, hoje.month
    a0, m0 = (a, m - 11) if m > 11 else (a - 1, m + 1)
    return f"{a0:04d}-{m0:02d}", f"{a:04d}-{m:02d}"


@api_financeiro_bp.route("/receitas-mensais", methods=["GET"])
@limiter.limit("60 per minute")
def receitas_mensais():
    if not Config.FINANCEIRO_API_TOKEN:
        return jsonify({"erro": "API desligada: FINANCEIRO_API_TOKEN não configurado"}), 503
    if not _token_valido():
        return jsonify({"erro": "não autorizado"}), 401

    agora = datetime.now(_FUSO_SP)
    de, ate = (request.args.get("de") or "").strip(), (request.args.get("ate") or "").strip()
    if not de and not ate:
        de, ate = _ultimos_12(agora.date())
    elif not de or not ate:
        padrao_de, padrao_ate = _ultimos_12(agora.date())
        de, ate = de or (ate if ate < padrao_de else padrao_de), ate or padrao_ate
    try:
        meses = relatorios_service.meses_do_periodo(de, ate)
    except ValueError as e:
        return jsonify({"erro": f"período inválido: {e}"}), 400
    if len(meses) > _MAX_MESES:
        return jsonify({"erro": f"período muito grande (máximo {_MAX_MESES} meses)"}), 400

    return jsonify({
        "empresa": "Biomax",
        "moeda": "BRL",
        "geradoEm": agora.isoformat(timespec="seconds"),
        "meses": relatorios_service.receitas_mensais(de, ate),
    })
