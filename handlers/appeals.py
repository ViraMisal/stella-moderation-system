"""Команда /appeal — подача апелляции."""

from __future__ import annotations

from typing import List

from telebot import types

from core.models import Appeal, Chat, Punishment, SessionLocal
from handlers.core import bot, now_utc
from handlers.db import ensure_user, is_user_blacklisted
from handlers.helpers import (
    escape_html_text,
    get_appeals_chat_id,
    get_command_args,
    human_duration,
    safe_delete_message,
)
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.appeals")


@bot.message_handler(commands=["appeal"])
def cmd_appeal(message: types.Message):
    if message.chat.type != "private":
        safe_delete_message(message.chat.id, message.message_id)
        return

    args = get_command_args(message)
    if not args:
        bot.send_message(message.chat.id, "Напишите так: /appeal ваш текст")
        return

    db = SessionLocal()
    try:
        ensure_user(db, message.from_user)
        if is_user_blacklisted(db, message.from_user.id):
            bot.send_message(message.chat.id, "❌ Вам запрещено пользоваться ботом.")
            return

        appeals_chat_id = get_appeals_chat_id()
        if not appeals_chat_id:
            bot.reply_to(
                message,
                "Апелляции сейчас не настроены. Попросите администратора указать чат для апелляций в веб-панели.",
            )
            return

        user = message.from_user
        now = now_utc()

        active = (
            db.query(Punishment)
            .filter(Punishment.user_id == user.id, Punishment.active == True)
            .order_by(Punishment.date.desc())
            .all()
        )

        if active:
            punish_lines: List[str] = ["<b>Активные наказания:</b>"]
            for p in active[:10]:
                try:
                    chat_obj = db.get(Chat, p.chat_id)
                    chat_title = (chat_obj.title if chat_obj else None) or str(p.chat_id)
                except Exception:
                    chat_title = str(p.chat_id)

                ptype = escape_html_text(p.type or "")
                admin_name = (
                    escape_html_text(p.admin_name or "")
                    or (f"<code>{p.admin_id}</code>" if p.admin_id else "—")
                )
                reason_txt = escape_html_text(p.reason or "")
                applied_min = int(p.applied_duration_minutes or 0)
                dur = human_duration(applied_min)

                until_info = ""
                if p.until_date:
                    try:
                        rem_sec = (p.until_date - now).total_seconds()
                    except Exception:
                        rem_sec = 0
                    rem_min = max(0, int((rem_sec + 59) // 60))
                    until_str = p.until_date.strftime("%Y-%m-%d %H:%M") + " UTC"
                    until_info = f", до {until_str} (осталось {human_duration(rem_min)})"

                line = (
                    f"• <b>{escape_html_text(chat_title)}</b> (<code>{p.chat_id}</code>): "
                    f"<b>{ptype}</b>, срок {escape_html_text(dur)}{until_info}"
                    f"\n  Выдал: {admin_name}"
                )
                if reason_txt:
                    line += f"\n  Причина: {reason_txt}"
                punish_lines.append(line)

            if len(active) > 10:
                punish_lines.append(f"… и ещё {len(active) - 10} (не показано)")

            punishments_block = "\n".join(punish_lines)
        else:
            punishments_block = "<b>Активные наказания:</b> нет"

        # Заголовок
        first_name = escape_html_text(user.first_name or "")
        if user.username:
            uname = "@" + escape_html_text(user.username)
            header = (
                "📩 <b>Новая апелляция</b>\n"
                f"От: <b>{first_name}</b> ({uname})\n"
                f"ID: <code>{user.id}</code>\n\n"
            )
        else:
            header = (
                "📩 <b>Новая апелляция</b>\n"
                f"От: <b>{first_name}</b>\n"
                f"ID: <code>{user.id}</code>\n\n"
            )

        text_block = "<b>Текст апелляции:</b>\n" + escape_html_text(args)
        full_msg = header + text_block + "\n\n" + punishments_block

        sent_msg = None
        if len(full_msg) > 3800:
            sent_msg = bot.send_message(appeals_chat_id, header + text_block)
            bot.send_message(appeals_chat_id, punishments_block)
        else:
            sent_msg = bot.send_message(appeals_chat_id, full_msg)

        try:
            appeal = Appeal(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                text=args,
                created_at=now_utc(),
                appeals_chat_id=appeals_chat_id,
                forwarded_message_id=getattr(sent_msg, "message_id", None) if sent_msg else None,
                punishments_snapshot=punishments_block,
            )
            db.add(appeal)
            db.commit()
        except Exception:
            db.rollback()

        bot.send_message(message.chat.id, "✅ Апелляция отправлена.")
    finally:
        db.close()
