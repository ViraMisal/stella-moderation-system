"""Служебные эндпоинты: /health, /metrics, /logs, /api/stats."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import desc, func, text

from core.models import AdminLog, Chat, Punishment, SessionLocal, User
from web.decorators import login_required

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    finally:
        db.close()
    status = "ok" if db_ok else "degraded"
    return jsonify({"status": status, "db": db_ok}), (200 if db_ok else 503)


@health_bp.get("/metrics")
def metrics():
    db = SessionLocal()
    try:
        return jsonify({
            "users": db.query(func.count(User.id)).scalar(),
            "chats": db.query(func.count(Chat.id)).scalar(),
            "punishments": db.query(func.count(Punishment.id)).scalar(),
            "active_punishments": db.query(func.count(Punishment.id))
                .filter(Punishment.active == True).scalar(),
        }), 200
    finally:
        db.close()


@health_bp.get("/api/stats")
@login_required
def api_stats():
    db = SessionLocal()
    try:
        return jsonify({
            "total_users": db.query(func.count(User.id)).scalar(),
            "total_chats": db.query(func.count(Chat.id)).scalar(),
            "total_punishments": db.query(func.count(Punishment.id)).scalar(),
            "active_punishments": db.query(func.count(Punishment.id))
                .filter(Punishment.active == True).scalar(),
            "blacklisted_users": db.query(func.count(User.id))
                .filter(User.is_blacklisted == True).scalar(),
        })
    finally:
        db.close()


@health_bp.get("/logs")
@login_required
def logs():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50

    db = SessionLocal()
    try:
        total = db.query(func.count(AdminLog.id)).scalar()
        items = (
            db.query(AdminLog)
            .order_by(desc(AdminLog.created_at))
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        total_pages = (total + per_page - 1) // per_page
    finally:
        db.close()

    return render_template("logs.html", logs=items, page=page, total_pages=total_pages)
