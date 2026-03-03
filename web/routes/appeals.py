"""Маршруты апелляций: /appeals, /appeals/<id>/reply."""
from __future__ import annotations

import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from core.config import BOT_TOKEN
from core.models import AdminLog, Appeal, SessionLocal
from web.decorators import superadmin_required

appeals_bp = Blueprint("appeals", __name__)


@appeals_bp.get("/appeals")
@superadmin_required
def appeals_list():
    db = SessionLocal()
    try:
        appeals = (
            db.query(Appeal)
            .order_by(Appeal.created_at.desc())
            .limit(200)
            .all()
        )
        return render_template("appeals.html", appeals=appeals)
    finally:
        db.close()


@appeals_bp.post("/appeals/<int:appeal_id>/reply")
@superadmin_required
def appeal_reply(appeal_id: int):
    reply_text = (request.form.get("reply_text") or "").strip()
    copy_to_chat = bool(request.form.get("copy_to_appeals_chat"))
    mark_resolved = bool(request.form.get("mark_resolved"))

    if not reply_text and not mark_resolved:
        flash("Введите текст ответа или отметьте апелляцию как решённую.", "warning")
        return redirect(url_for("appeals.appeals_list"))

    db = SessionLocal()
    try:
        appeal = db.get(Appeal, appeal_id)
        if not appeal:
            flash("Апелляция не найдена.", "error")
            return redirect(url_for("appeals.appeals_list"))

        admin_id = session.get("tg_id")
        admin_name = session.get("username") or session.get("first_name") or str(admin_id or "admin")

        if mark_resolved and not reply_text:
            appeal.answered_at = datetime.datetime.utcnow()
            appeal.answered_by_id = admin_id
            appeal.answered_by_name = admin_name
            appeal.answer_text = appeal.answer_text or ""
            db.add(appeal)
            db.commit()
            try:
                db.add(AdminLog(admin_id=admin_id, admin_name=admin_name,
                                action="appeal_resolved",
                                details=f"appeal_id={appeal_id} user_id={appeal.user_id}",
                                ip_address=request.remote_addr))
                db.commit()
            except Exception:
                db.rollback()
            flash("Апелляция отмечена как решённая.", "success")
            return redirect(url_for("appeals.appeals_list"))

        # Отправляем ответ пользователю в ЛС
        dm_ok, dm_err = False, None
        try:
            import telebot
            tbot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
            tbot.send_message(int(appeal.user_id), reply_text)
            dm_ok = True
        except Exception as e:
            dm_err = str(e)

        # Копия в чат апелляций
        if copy_to_chat and appeal.appeals_chat_id:
            try:
                import telebot
                tbot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
                header = "↩️ Ответ для "
                header += f"@{appeal.username}" if appeal.username else f"id:{appeal.user_id}"
                header += f"\nОт: {admin_name}\n\n"
                tbot.send_message(
                    int(appeal.appeals_chat_id), header + reply_text,
                    reply_to_message_id=int(appeal.forwarded_message_id) if appeal.forwarded_message_id else None,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass

        appeal.answered_at = datetime.datetime.utcnow()
        appeal.answered_by_id = admin_id
        appeal.answered_by_name = admin_name
        appeal.answer_text = reply_text
        db.add(appeal)
        db.commit()

        try:
            db.add(AdminLog(admin_id=admin_id, admin_name=admin_name,
                            action="appeal_reply",
                            details=f"appeal_id={appeal_id} user_id={appeal.user_id} dm_ok={dm_ok}",
                            ip_address=request.remote_addr))
            db.commit()
        except Exception:
            db.rollback()

        if dm_ok:
            flash("Ответ отправлен пользователю.", "success")
        else:
            flash(
                "Не удалось отправить сообщение пользователю"
                + (f": {dm_err}" if dm_err else "."),
                "warning",
            )
        return redirect(url_for("appeals.appeals_list"))
    finally:
        db.close()
