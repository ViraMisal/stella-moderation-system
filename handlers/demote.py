"""Снять админку + наказать: pending actions и callback handler."""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any, Dict, Optional

from telebot import types

from core.config import SUPERADMIN_IDS
from core.models import RoleAssignment, SessionLocal
from core.settings import is_kill_switch_enabled
from handlers.core import (
    PENDING_DEMOTE,
    PENDING_LOCK,
    PENDING_TTL_SECONDS,
    _tg_retry_call,
    bot,
    now_utc,
    to_unix_ts_utc,
)
from handlers.db import ensure_chat, ensure_chat_member, ensure_user
from handlers.punishment import probation_multiplier, save_punishment_record
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.demote")


# ---------------------------------------------------------------------------
# Состояние pending-действий
# ---------------------------------------------------------------------------

def create_pending_demote_action(
    *,
    chat_id: int,
    target_id: int,
    admin_id: int,
    kind: str,
    requested_minutes: int,
    reason: str,
) -> str:
    action_id = uuid.uuid4().hex[:12]
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "target_id": target_id,
        "admin_id": admin_id,
        "kind": kind,
        "requested_minutes": requested_minutes,
        "reason": reason,
        "created_at": time.time(),
    }
    with PENDING_LOCK:
        PENDING_DEMOTE[action_id] = payload
    return action_id


def get_pending_demote(action_id: str) -> Optional[Dict[str, Any]]:
    with PENDING_LOCK:
        payload = PENDING_DEMOTE.get(action_id)
        if not payload:
            return None
        if time.time() - payload.get("created_at", 0) > PENDING_TTL_SECONDS:
            PENDING_DEMOTE.pop(action_id, None)
            return None
        return payload


def pop_pending_demote(action_id: str) -> Optional[Dict[str, Any]]:
    # Нельзя вызывать get_pending_demote внутри этого лока — deadlock.
    with PENDING_LOCK:
        payload = PENDING_DEMOTE.get(action_id)
        if not payload:
            return None
        if time.time() - payload.get("created_at", 0) > PENDING_TTL_SECONDS:
            PENDING_DEMOTE.pop(action_id, None)
            return None
        PENDING_DEMOTE.pop(action_id, None)
        return payload


# ---------------------------------------------------------------------------
# Проверки прав бота
# ---------------------------------------------------------------------------

def _bot_can_promote(chat_id: int) -> bool:
    try:
        me = _tg_retry_call(bot.get_me, retries=3, base_delay=1.0)
        m = _tg_retry_call(bot.get_chat_member, chat_id, me.id, retries=3, base_delay=1.0)
        return m.status in ("administrator", "creator") and bool(getattr(m, "can_promote_members", False))
    except Exception:
        return False


def _bot_can_restrict(chat_id: int) -> bool:
    try:
        me = _tg_retry_call(bot.get_me, retries=3, base_delay=1.0)
        m = _tg_retry_call(bot.get_chat_member, chat_id, me.id, retries=3, base_delay=1.0)
        return m.status in ("administrator", "creator") and bool(getattr(m, "can_restrict_members", False))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Диалог подтверждения
# ---------------------------------------------------------------------------

def ask_demote_and_continue(
    *,
    message: types.Message,
    target: types.User,
    kind: str,
    requested_minutes: int,
    reason: str,
):
    chat_id = message.chat.id

    if not _bot_can_promote(chat_id):
        bot.send_message(
            chat_id,
            "❌ Нельзя применить наказание: цель — админ, а у бота нет права 'Назначать админов' (чтобы снять админку).",
        )
        return

    action_id = create_pending_demote_action(
        chat_id=chat_id,
        target_id=target.id,
        admin_id=message.from_user.id,
        kind=kind,
        requested_minutes=requested_minutes,
        reason=reason,
    )

    action_title = "мут" if kind == "mute" else "медиамут"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        text=f"Снять админку и продолжить ({action_title})",
        callback_data=f"demote:{action_id}",
    ))
    kb.add(types.InlineKeyboardButton(text="Отмена", callback_data=f"demote_cancel:{action_id}"))

    bot.send_message(
        chat_id,
        f"⚠️ Цель — администратор. Напрямую выдать {action_title} нельзя.\n\n"
        f"Нажми кнопку ниже, чтобы <b>снять админку</b> и продолжить.",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# Callback handler
# ---------------------------------------------------------------------------

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("demote"))
def cb_demote(call: types.CallbackQuery):
    data = call.data or ""

    if data.startswith("demote_cancel:"):
        action_id = data.split(":", 1)[1]
        with PENDING_LOCK:
            PENDING_DEMOTE.pop(action_id, None)
        try:
            bot.edit_message_text(
                "Ок, отменено.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
        except Exception:
            pass
        bot.answer_callback_query(call.id)
        return

    if not data.startswith("demote:"):
        bot.answer_callback_query(call.id)
        return

    action_id = data.split(":", 1)[1]
    payload = pop_pending_demote(action_id)
    if not payload:
        bot.answer_callback_query(call.id, "Запрос устарел или уже обработан.")
        return

    if call.from_user.id != payload["admin_id"] and call.from_user.id not in SUPERADMIN_IDS:
        bot.answer_callback_query(call.id, "Это не твой запрос.")
        return

    chat_id = int(payload["chat_id"])
    target_id = int(payload["target_id"])
    kind = str(payload["kind"])
    requested_minutes = int(payload["requested_minutes"])
    reason = str(payload.get("reason") or "")

    if is_kill_switch_enabled():
        bot.answer_callback_query(call.id, "Киллсвитч активен. Операция отменена.")
        try:
            bot.edit_message_text(
                "⛔️ Киллсвитч активен: операция отменена.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
        except Exception:
            pass
        return

    if not _bot_can_promote(chat_id):
        bot.answer_callback_query(call.id, "У бота нет прав на снятие админки.")
        return
    if not _bot_can_restrict(chat_id):
        bot.answer_callback_query(call.id, "У бота нет прав на мут/ограничение.")
        return

    # Снимаем все права в Telegram
    try:
        rights_false = {
            "can_manage_chat": False,
            "can_change_info": False,
            "can_delete_messages": False,
            "can_invite_users": False,
            "can_restrict_members": False,
            "can_pin_messages": False,
            "can_promote_members": False,
            "can_manage_video_chats": False,
            "can_manage_topics": False,
            "is_anonymous": False,
        }
        _tg_retry_call(bot.promote_chat_member, chat_id, target_id, retries=3, base_delay=1.0, **rights_false)
        try:
            _tg_retry_call(bot.set_chat_administrator_custom_title, chat_id, target_id, "", retries=3, base_delay=1.0)
        except Exception:
            pass
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка снятия админки: {e}")
        return

    # Убираем внутреннюю роль
    db = SessionLocal()
    try:
        db.query(RoleAssignment).filter_by(chat_id=chat_id, user_id=target_id).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    # Применяем наказание
    applied_minutes = requested_minutes
    until_date: Optional[datetime.datetime] = None

    db = SessionLocal()
    try:
        mult, pr = probation_multiplier(db, chat_id, target_id)
        if requested_minutes > 0:
            applied_minutes = requested_minutes * mult
            until_date = now_utc() + datetime.timedelta(minutes=applied_minutes)
        else:
            applied_minutes = 0

        until_ts = to_unix_ts_utc(until_date)

        if kind == "mute":
            perms = types.ChatPermissions(can_send_messages=False)
            _tg_retry_call(
                bot.restrict_chat_member, chat_id, target_id,
                permissions=perms, until_date=until_ts, retries=3, base_delay=1.0,
            )
        elif kind == "mutemedia":
            perms = types.ChatPermissions(
                can_send_messages=True,
                can_send_audios=False, can_send_documents=False,
                can_send_photos=False, can_send_videos=False,
                can_send_video_notes=False, can_send_voice_notes=False,
                can_send_polls=False, can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
            _tg_retry_call(
                bot.restrict_chat_member, chat_id, target_id,
                permissions=perms, until_date=until_ts, retries=3, base_delay=1.0,
            )
        else:
            raise ValueError("Unsupported kind")

        ensure_user(db, call.from_user)
        ensure_chat(db, call.message.chat)
        ensure_chat_member(db, chat_id, target_id)

        admin_name = call.from_user.username or call.from_user.first_name or str(call.from_user.id)
        save_punishment_record(
            db,
            user_id=target_id,
            chat_id=chat_id,
            p_type=kind,
            reason=reason,
            admin_id=call.from_user.id,
            admin_name=admin_name,
            until_date=until_date,
            requested_minutes=requested_minutes,
            applied_minutes=applied_minutes,
        )

        mult_txt = f" (исп. срок x{mult})" if mult > 1 else ""
        bot.edit_message_text(
            f"✅ Готово: админка снята и наказание применено{mult_txt}.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
        )
    except Exception as e:
        db.rollback()
        try:
            bot.edit_message_text(
                f"❌ Ошибка: {e}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
        except Exception:
            pass
    finally:
        db.close()

    bot.answer_callback_query(call.id)
