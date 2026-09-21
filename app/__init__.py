import os
import traceback
from datetime import timedelta
from flask import Flask, session, request, jsonify
from werkzeug.exceptions import HTTPException
from app.config import Config
from app.extensions import socketio, limiter, csrf
from app.routes.turnos import turnos_bp
from app.routes.auth import auth_bp
from app.routes.medico_painel import medico_painel_bp
from app.routes.webhooks_asaas import webhooks_asaas_bp
from app.routes.admin import admin_bp
from app.routes.termos import termos_bp
from app.routes.api_dora import api_dora_bp


def create_app():
    Config.validate()

    app = Flask(__name__)
    app.secret_key = Config.FLASK_SECRET_KEY

    from app.services.agenda_fixos_service import telefone_sem_ddi
    app.jinja_env.filters["telefone_sem_ddi"] = telefone_sem_ddi

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = Config.FORCE_HTTPS_COOKIES
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["WTF_CSRF_TIME_LIMIT"] = 8 * 60 * 60

    @app.errorhandler(Exception)
    def _tratar_erro_nao_previsto(e):
        if isinstance(e, HTTPException):
            return e
        traceback.print_exc()
        if request.path.startswith("/api/"):
            return jsonify({
                "erro": "Ocorreu um erro interno no servidor. Tente de novo em instantes; "
                        "se continuar acontecendo, avise o suporte técnico.",
            }), 500
        raise e

    @app.before_request
    def _tornar_sessao_permanente():
        session.permanent = True

    app.register_blueprint(turnos_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(medico_painel_bp)
    app.register_blueprint(webhooks_asaas_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(termos_bp)
    app.register_blueprint(api_dora_bp)

    socketio.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    csrf.exempt(webhooks_asaas_bp)
    # A Dora (assistente de WhatsApp, projeto separado) chama esses
    # endpoints como servidor pra servidor, sem sessão de navegador --
    # quem autentica é a API key (X-API-Key), não o token CSRF (ver
    # app/routes/api_dora.py _exigir_api_key).
    csrf.exempt(api_dora_bp)

    from flask import render_template

    @app.route("/")
    def home():
        return render_template("home_reserva_horas.html")

    @app.route("/consultorios")
    def consultorios_publicos():
        from app.services import supabase_client as db
        # A página deixou de mostrar um card por consultório (com nome/
        # número e descrição) -- pedido do Paulo em 11/09/2026: agora é um
        # carrossel só, com as fotos de TODOS os consultórios ativos
        # juntas, uma bem grande por vez, passando sozinho. `fotos` é essa
        # lista já achatada (cada consultório pode ter várias fotos).
        try:
            consultorios = db.listar_todos_consultorios()
        except Exception:
            consultorios = []
        fotos = [foto for c in consultorios for foto in (c.get("fotos") or [])]
        return render_template("consultorios_publicos.html", fotos=fotos)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app
