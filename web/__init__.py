"""Веб-панель Stella (Flask application factory)."""
from __future__ import annotations

import json
import logging
import os

from flask import Flask, render_template, session
from werkzeug.middleware.proxy_fix import ProxyFix

from core.config import FLASK_SECRET
from core.tz import to_msk_str


def create_app() -> Flask:
    """Создаёт и возвращает настроенный экземпляр Flask."""

    # Шаблоны и статика лежат в корне проекта (рядом с web/)
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    app.secret_key = FLASK_SECRET
    app.logger.setLevel(logging.INFO)

    # Reverse-proxy
    if os.getenv("ENV", "development").lower() == "production" \
            or os.getenv("TRUST_PROXY_HEADERS", "0") in ("1", "true", "yes"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["PREFERRED_URL_SCHEME"] = os.getenv("PREFERRED_URL_SCHEME", "https")

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    if os.getenv("ENV", "development").lower() == "production":
        app.config["SESSION_COOKIE_SECURE"] = (
            os.getenv("SESSION_COOKIE_SECURE", "1") not in ("0", "false", "no")
        )

    @app.template_filter("loads")
    def jinja_loads(value):
        if value is None:
            return {}
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return {}

    @app.template_filter("dumps")
    def jinja_dumps(value):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return ""

    @app.template_filter("get")
    def jinja_get(obj, key, default=None):
        try:
            return obj.get(key, default)
        except Exception:
            try:
                return getattr(obj, key)
            except Exception:
                return default

    @app.context_processor
    def inject_theme():
        return {"PANEL_THEME": os.getenv("PANEL_THEME", "").strip()}

    @app.context_processor
    def utility_processor():
        import datetime

        from web.context import is_current_superadmin

        RU_RIGHTS = {
            "can_manage_chat": "Управление чатом",
            "can_delete_messages": "Удалять сообщения",
            "can_restrict_members": "Ограничивать участников",
            "can_promote_members": "Назначать админов",
            "can_change_info": "Менять информацию",
            "can_invite_users": "Приглашать пользователей",
            "can_pin_messages": "Закреплять сообщения",
            "can_manage_topics": "Управлять темами",
            "is_anonymous": "Анонимный администратор",
        }

        def format_datetime(dt):
            if not dt:
                return "-"
            try:
                return to_msk_str(dt)
            except Exception:
                try:
                    return dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    return str(dt)

        return dict(
            format_datetime=format_datetime,
            RU_RIGHTS=RU_RIGHTS,
            current_year=datetime.datetime.now().year,
            admin_name=session.get("who", "Admin"),
            current_role=session.get("role", "user"),
            is_superadmin=is_current_superadmin(),
            accessible_chat_count=(
                len(session.get("admin_chats", []))
                if session.get("admin_chats") else "все"
            ),
        )

    @app.errorhandler(404)
    def not_found(e):
        try:
            return render_template("error.html", error_code=404,
                                   error_message="Страница не найдена"), 404
        except Exception:
            return "<h1>404 - Страница не найдена</h1>", 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error("500 Error: %s", e)
        try:
            return render_template("error.html", error_code=500,
                                   error_message="Внутренняя ошибка сервера"), 500
        except Exception:
            return f"<h1>500</h1><p>{e}</p>", 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error("Unhandled exception: %s", e, exc_info=True)
        try:
            return render_template("error.html", error_code=500,
                                   error_message=f"Ошибка: {e}"), 500
        except Exception:
            return f"<h1>Ошибка</h1><p>{e}</p>", 500

    from web.routes.admins import admin_tools_bp
    from web.routes.appeals import appeals_bp
    from web.routes.auth import auth_bp
    from web.routes.bot_sender import bot_sender_bp
    from web.routes.chats import chats_bp
    from web.routes.dashboard import dashboard_bp
    from web.routes.health import health_bp
    from web.routes.settings_routes import settings_bp
    from web.routes.users import users_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(chats_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(bot_sender_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(admin_tools_bp)

    return app


app = create_app()
