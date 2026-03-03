"""Главная страница и дашборд."""
from __future__ import annotations

import datetime

from flask import Blueprint, flash, redirect, render_template, url_for
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload

from core.models import Chat, Punishment, SessionLocal, User
from web.context import get_accessible_chats
from web.decorators import login_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@login_required
def index():
    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.get("/dashboard")
@login_required
def dashboard():
    db = SessionLocal()
    try:
        accessible = get_accessible_chats()
        base_filters = []
        if accessible is not None:
            base_filters.append(Punishment.chat_id.in_(accessible) if accessible else False)

        total_users = db.query(func.count(User.id)).scalar() or 0
        total_chats = (
            len(accessible) if accessible is not None
            else db.query(func.count(Chat.id)).scalar() or 0
        )
        total_punishments = db.query(func.count(Punishment.id)).filter(*base_filters).scalar() or 0
        active_punishments = db.query(func.count(Punishment.id)).filter(
            Punishment.active == True, Punishment.type != "ban", *base_filters
        ).scalar() or 0

        q = db.query(Punishment).options(joinedload(Punishment.user), joinedload(Punishment.chat))
        if accessible is not None and accessible:
            q = q.filter(Punishment.chat_id.in_(accessible))
        recent_punishments = q.order_by(desc(Punishment.date)).limit(10).all()

        try:
            top_offenders = (
                db.query(User, func.count(Punishment.id).label("count"))
                .join(Punishment).group_by(User.id)
                .order_by(desc("count")).limit(10).all()
            )
        except Exception:
            top_offenders = []

        today = datetime.datetime.utcnow().date()
        activity_data = []
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            start = datetime.datetime.combine(d, datetime.time.min)
            end = datetime.datetime.combine(d, datetime.time.max)
            cnt = db.query(func.count(Punishment.id)).filter(
                Punishment.date >= start, Punishment.date <= end, *base_filters
            ).scalar() or 0
            activity_data.append({"date": d.strftime("%d.%m"), "count": cnt})

        stats = {
            "total_users": total_users, "total_chats": total_chats,
            "total_punishments": total_punishments, "active_punishments": active_punishments,
            "active_nonban": active_punishments,
            "recent_punishments": recent_punishments,
            "top_offenders": top_offenders, "activity_data": activity_data,
        }
    except Exception as e:
        from flask import current_app
        current_app.logger.error("Dashboard error: %s", e, exc_info=True)
        stats = {
            "total_users": 0, "total_chats": 0, "total_punishments": 0,
            "active_punishments": 0, "active_nonban": 0,
            "recent_punishments": [], "top_offenders": [], "activity_data": [],
        }
        flash(f"Ошибка загрузки дашборда: {e}", "error")
    finally:
        db.close()

    return render_template("dashboard.html", stats=stats)
