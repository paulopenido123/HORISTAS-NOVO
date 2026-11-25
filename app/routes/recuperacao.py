"""
Página de RECUPERAÇÃO (v128): /recuperar -- funciona SEM login de admin e mesmo se o resto do sistema estiver com problema
(só depende do banco). Pede a senha master (ADMIN_MASTER_PASSWORD), lista o histórico, baixa e restaura.
Também: /versao.json (aviso de versão nova, a cada 3 min o navegador confere).
"""
import secrets
import time
from datetime import timezone, timedelta
from flask import Blueprint, Response, jsonify, redirect, render_template_string, request, session, url_for
from app.config import Config
from app.extensions import limiter

recuperacao_bp = Blueprint("recuperacao", __name__)
_FUSO = timezone(timedelta(hours=-3))
_MIN = 15

_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Recuperação — Lifemax</title>
<style>body{margin:0;background:#F5F8FA;font-family:Arial,sans-serif;color:#102A43}.w{max-width:860px;margin:auto;padding:20px 16px}.c{background:#fff;border:1px solid #e3ebef;border-radius:14px;padding:18px;margin-bottom:14px}
input{padding:10px;border:1px solid #d8e3e7;border-radius:8px;font-size:15px}button{padding:8px 14px;border:0;border-radius:8px;background:#0EA5A0;color:#fff;font-weight:700;cursor:pointer}button.p{background:#c95050}
.e{background:#FBEAE6;color:#B33;padding:10px;border-radius:8px;margin-bottom:12px}.o{background:#E3F7EE;color:#0B7B45;padding:10px;border-radius:8px;margin-bottom:12px}.m{color:#62788A;font-size:13px;line-height:1.5}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:6px;text-align:left;border-top:1px solid #e3ebef}</style></head><body><div class="w">
<h2>Recuperação de dados — Lifemax</h2>
{% if msg %}<div class="{{ 'o' if ok else 'e' }}">{{ msg }}</div>{% endif %}
{% if not liberado %}
<div class="c"><p class="m">Página de emergência: não precisa de login do sistema. Digite a senha master (a mesma de Admin &gt; Usuários/Backup).</p>
<form method="post"><input type="hidden" name="acao" value="entrar"><input type="password" name="master" placeholder="Senha master" autocomplete="off"> <button>Entrar</button></form></div>
{% else %}
<div class="c"><p class="m">Cópias automáticas (a cada hora, últimas 48 h). Restaurar <strong>mescla</strong> os dados da versão escolhida (nada é apagado) e guarda antes uma cópia do que está no ar.</p>
{% if erro %}<div class="e">{{ erro }}</div>{% endif %}
<table><tr><th>Data / hora</th><th>Origem</th><th>Linhas</th><th>KB</th><th></th></tr>
{% for h in historico %}<tr><td>{{ h.criado_em.astimezone(fuso).strftime('%d/%m/%Y %H:%M') }}</td><td>{{ h.origem }}</td><td>{{ h.total_linhas }}</td><td>{{ (h.tamanho_bytes/1024)|round|int }}</td>
<td>{% if h.origem != 'bloqueado' %}<a href="{{ url_for('recuperacao.baixar', versao_id=h.id) }}">Baixar</a>
<form method="post" style="display:inline" onsubmit="var r=prompt('Digite RESTAURAR para confirmar:');if(!r||r.trim().toUpperCase()!=='RESTAURAR')return false;this.confirmacao.value=r;"><input type="hidden" name="acao" value="restaurar"><input type="hidden" name="id" value="{{ h.id }}"><input type="hidden" name="confirmacao"><button class="p">Restaurar</button></form>{% endif %}</td></tr>
{% else %}<tr><td colspan="5" class="m">Nenhuma cópia.</td></tr>{% endfor %}</table></div>
{% endif %}</div></body></html>"""


def _liberado():
    return session.get("recuperar_ate", 0) > time.time()


@recuperacao_bp.route("/recuperar", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def recuperar():
    from app.services import historico_service
    msg, ok = None, False
    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "entrar":
            senha = request.form.get("master", "")
            if senha and Config.ADMIN_MASTER_PASSWORD and secrets.compare_digest(senha, Config.ADMIN_MASTER_PASSWORD):
                session["recuperar_ate"] = time.time() + _MIN * 60
                return redirect(url_for("recuperacao.recuperar"))
            msg = "Senha master incorreta."
        elif acao == "restaurar" and _liberado():
            if (request.form.get("confirmacao") or "").strip().upper() != "RESTAURAR":
                msg = "Digite RESTAURAR para confirmar."
            else:
                try:
                    r = historico_service.restaurar_versao(int(request.form.get("id", "0")))
                    msg, ok = f"Restaurado: {sum(r['gravadas'].values())} registros. A versão anterior foi guardada (#{r['copia_de_seguranca_id']}).", True
                except Exception as e:
                    msg = f"Não restaurou (nada foi alterado): {e}"
    historico, erro = [], None
    if _liberado():
        try:
            if historico_service.tabela_ok():
                historico = historico_service.listar()
            else:
                erro = "A tabela de histórico ainda não existe (rode sql/migration_historico_dados.sql no Neon)."
        except Exception as e:
            erro = f"Problema de conexão com o banco: {e}"
    return render_template_string(_HTML, msg=msg, ok=ok, liberado=_liberado(), historico=historico, erro=erro, fuso=_FUSO)


@recuperacao_bp.route("/recuperar/baixar/<int:versao_id>")
def baixar(versao_id):
    from app.services import historico_service
    if not _liberado():
        return redirect(url_for("recuperacao.recuperar"))
    achado = historico_service.obter_arquivo(versao_id)
    if not achado:
        return "Versão não encontrada.", 404
    arq, meta = achado
    nome = f"historico_lifemax_{meta['criado_em'].astimezone(_FUSO).strftime('%Y-%m-%d_%H-%M')}.json.gz"
    return Response(arq, mimetype="application/gzip", headers={"Content-Disposition": f"attachment; filename={nome}"})


@recuperacao_bp.route("/versao.json")
def versao_json():
    r = jsonify({"versao": Config.VERSAO_SISTEMA})
    r.headers["Cache-Control"] = "no-store"
    return r
