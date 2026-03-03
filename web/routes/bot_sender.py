"""Ручная отправка сообщений от имени бота: /bot/send."""
from __future__ import annotations

import io

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from core.config import BOT_TOKEN
from core.models import Chat, ChatTopic, SessionLocal
from src_utils.logsetup import setup_logging
from web.context import get_current_admin_info
from web.decorators import superadmin_required
from web.utils import log_admin_action

bot_sender_bp = Blueprint("bot_sender", __name__)
logger = setup_logging("web.bot_sender")


@bot_sender_bp.route("/bot/send", methods=["GET", "POST"])
@superadmin_required
def bot_send():
    db = SessionLocal()
    try:
        chats = db.query(Chat).order_by(Chat.title.asc()).all()
    finally:
        db.close()

    selected_chat_raw = (
        request.values.get("chat_id") or request.values.get("chat_select") or ""
    ).strip()
    try:
        selected_chat_id = int(selected_chat_raw) if selected_chat_raw else None
    except ValueError:
        selected_chat_id = None

    topics = []
    if selected_chat_id:
        db = SessionLocal()
        try:
            topics = (
                db.query(ChatTopic)
                .filter(ChatTopic.chat_id == selected_chat_id)
                .order_by(ChatTopic.last_activity.desc(), ChatTopic.thread_id.desc())
                .all()
            )
        except Exception:
            topics = []
        finally:
            db.close()

    if request.method == "POST":
        if not selected_chat_id:
            flash("Некорректный chat_id.", "error")
            return render_template("bot_sender.html", chats=chats,
                                   selected_chat_id=selected_chat_id, topics=topics)

        def _opt_int(name: str):
            raw = (request.form.get(name) or "").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except ValueError:
                return "invalid"

        thread_id = _opt_int("thread_id")
        reply_to = _opt_int("reply_to_message_id")

        if thread_id == "invalid":
            flash("Некорректный topic id (thread_id).", "error")
            thread_id = None
        if reply_to == "invalid":
            flash("Некорректный id сообщения для ответа.", "error")
            reply_to = None

        text = (request.form.get("text") or "").rstrip()
        silent = bool(request.form.get("disable_notification"))
        upload = request.files.get("file")
        has_file = bool(upload and getattr(upload, "filename", ""))

        if not text and not has_file:
            flash("Нужно указать текст и/или прикрепить файл.", "error")
        else:
            kwargs = {}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            if reply_to:
                kwargs["reply_to_message_id"] = reply_to
            if silent:
                kwargs["disable_notification"] = True

            import telebot
            tbot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

            try:
                if has_file:
                    filename = secure_filename(upload.filename) or "file"
                    data = upload.read() or b""
                    if len(data) > 50 * 1024 * 1024:
                        raise ValueError("Файл слишком большой (лимит 50MB).")
                    bio = io.BytesIO(data)
                    bio.name = filename
                    caption = text or None
                    ctype = (getattr(upload, "mimetype", "") or "").lower()
                    low = filename.lower()

                    if ctype.startswith("image/") and not low.endswith(".gif"):
                        tbot.send_photo(selected_chat_id, bio, caption=caption, **kwargs)
                    elif ctype.startswith("video/"):
                        tbot.send_video(selected_chat_id, bio, caption=caption, **kwargs)
                    elif low.endswith(".gif") or ctype == "image/gif":
                        tbot.send_animation(selected_chat_id, bio, caption=caption, **kwargs)
                    else:
                        tbot.send_document(selected_chat_id, bio, caption=caption, **kwargs)
                else:
                    tbot.send_message(selected_chat_id, text, **kwargs)

                admin_id, who, _, _ = get_current_admin_info()
                details = f"chat_id={selected_chat_id}"
                if thread_id:
                    details += f" thread_id={thread_id}"
                if has_file:
                    details += f" file={getattr(upload, 'filename', '')}"
                if text:
                    details += f" text='{text[:200].replace(chr(10), ' ')}'"
                log_admin_action("bot_send", details=details, admin_id=admin_id, admin_name=who)
                logger.info("BOT_SEND: %s", details)

                flash("✅ Отправлено от имени бота.", "success")
                return redirect(url_for("bot_sender.bot_send", chat_id=str(selected_chat_id)))
            except Exception as e:
                flash(f"❌ Не удалось отправить: {e}", "error")

    return render_template("bot_sender.html", chats=chats,
                           selected_chat_id=selected_chat_id, topics=topics)
