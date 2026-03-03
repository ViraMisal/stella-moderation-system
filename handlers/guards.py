"""Проверки прав: can_moderate, require_moderator, kill switch."""

from __future__ import annotations

from telebot import types

from config import SUPERADMIN_IDS
from handlers.core import _set_topic_context, _tg_retry_call, bot
from handlers.db import has_internal_role, is_user_blacklisted
from handlers.helpers import notify_private, safe_delete_message, send_temp_message
from settings_service import is_kill_switch_enabled
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.guards")


def is_chat_admin(chat_id: int, user_id: int) -> bool:
    try:
        m = _tg_retry_call(bot.get_chat_member, chat_id, user_id, retries=3, base_delay=1.0)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


def can_moderate(chat_id: int, user_id: int) -> bool:
    if user_id in SUPERADMIN_IDS:
        return True
    from models import SessionLocal
    db = SessionLocal()
    try:
        if is_user_blacklisted(db, user_id):
            return False
        if has_internal_role(db, chat_id, user_id):
            return True
    finally:
        db.close()
    return is_chat_admin(chat_id, user_id)


def require_moderator(message: types.Message) -> bool:
    """Стандартная проверка для команд модерации.

    Удаляет команду из чата, проверяет kill switch и права.
    Возвращает True если можно выполнять команду.
    """
    _set_topic_context(message)

    if message.chat.type in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)

    if is_kill_switch_enabled():
        ok = notify_private(
            message.from_user.id,
            "⛔️ Киллсвитч активен: модерационные действия временно отключены.",
        )
        if not ok and message.chat.type in ("group", "supergroup"):
            send_temp_message(
                message.chat.id,
                "⛔️ Киллсвитч активен: модерация временно отключена.\n"
                "(Если ты не видишь уведомления в ЛС — открой бота и нажми /start)",
            )
        return False

    if not can_moderate(message.chat.id, message.from_user.id):
        ok = notify_private(message.from_user.id, "❌ У тебя нет прав на эту команду.")
        if not ok and message.chat.type in ("group", "supergroup"):
            send_temp_message(
                message.chat.id,
                "❌ Нет прав на эту команду.\n"
                "(Чтобы получать причины в ЛС — открой бота и нажми /start)",
            )
        return False

    return True


def require_reason(message: types.Message, reason: str, example: str) -> bool:
    """Проверяет что причина указана. Если нет — отправляет подсказку."""
    if (reason or "").strip():
        return True

    tip = f"❌ Нужно указать причину. Пример: {example}"

    ok = False
    try:
        ok = notify_private(message.from_user.id, tip)
    except Exception:
        ok = False

    if not ok and message.chat.type in ("group", "supergroup"):
        send_temp_message(message.chat.id, tip)

    return False
