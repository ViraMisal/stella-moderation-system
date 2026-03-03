"""Команды /probation и /unprobation."""

from __future__ import annotations

import datetime

from telebot import types

from core.models import Probation, SessionLocal
from handlers.core import bot, now_utc
from handlers.db import ensure_chat, ensure_user
from handlers.guards import require_moderator, require_reason
from handlers.helpers import (
    escape_html_text,
    format_user_ref_html,
    parse_duration_and_reason,
    resolve_target_and_args,
    safe_delete_message,
    try_enrich_user_from_chat,
)
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.probation")


@bot.message_handler(commands=["probation", "isp"])
def cmd_probation(message: types.Message):
    """Устанавливает испытательный срок — новые тайм-наказания ×2."""
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    target, rest = resolve_target_and_args(message)
    if not target:
        bot.send_message(message.chat.id, "❌ Не вижу цель. Ответь на сообщение пользователя или укажи ID/@username.")
        return

    target = try_enrich_user_from_chat(message.chat.id, target)

    minutes, reason = parse_duration_and_reason(rest)
    if minutes <= 0:
        bot.send_message(message.chat.id, "❌ Укажи срок. Пример: /probation 30d причина")
        return

    if not require_reason(message, reason, "/probation 30d повторные нарушения"):
        return

    until = now_utc() + datetime.timedelta(minutes=minutes)

    db = SessionLocal()
    try:
        ensure_user(db, target)
        ensure_chat(db, message.chat)

        pr = db.query(Probation).filter_by(chat_id=message.chat.id, user_id=target.id).first()
        if pr:
            pr.until_date = until
            pr.reason = reason
            pr.created_by_id = message.from_user.id
            pr.created_by_name = message.from_user.username or message.from_user.first_name
        else:
            pr = Probation(
                chat_id=message.chat.id,
                user_id=target.id,
                until_date=until,
                reason=reason,
                created_by_id=message.from_user.id,
                created_by_name=message.from_user.username or message.from_user.first_name,
            )
            db.add(pr)
        db.commit()

        bot.send_message(
            message.chat.id,
            f"⏳ Испытательный срок выдан {format_user_ref_html(target)} до <b>{until.strftime('%Y-%m-%d')}</b>."
            + (f"\nПричина: {escape_html_text(reason)}" if reason else ""),
        )
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["unprobation", "noisp"])
def cmd_unprobation(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    target, _ = resolve_target_and_args(message)
    if not target:
        bot.send_message(message.chat.id, "❌ Не вижу цель. Ответь на сообщение пользователя или укажи ID/@username.")
        return

    target = try_enrich_user_from_chat(message.chat.id, target)

    db = SessionLocal()
    try:
        db.query(Probation).filter_by(chat_id=message.chat.id, user_id=target.id).delete()
        db.commit()
        bot.send_message(message.chat.id, f"✅ Испытательный срок снят с {format_user_ref_html(target)}.")
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()
