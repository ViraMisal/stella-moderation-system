"""Команды модерации: /mute /mutemedia /ban /kick /unmute /unban."""

from __future__ import annotations

import datetime

from telebot import types

from core.models import SessionLocal
from handlers.core import _tg_retry_call, bot, now_utc, to_unix_ts_utc
from handlers.db import ensure_chat, ensure_chat_member, ensure_user
from handlers.demote import ask_demote_and_continue
from handlers.guards import require_moderator, require_reason
from handlers.helpers import (
    escape_html_text,
    format_user_ref_html,
    get_chat_default_permissions,
    human_duration,
    parse_duration_and_reason,
    resolve_target_and_args,
    safe_delete_message,
    try_enrich_user_from_chat,
)
from handlers.punishment import deactivate_active_punishments, probation_multiplier, save_punishment_record
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.moderation")


def _get_target_and_check_admin(message: types.Message, target: types.User, kind: str):
    """Получает актуальный объект User и проверяет, не является ли он администратором.

    Возвращает (real_user, is_admin). При ошибке Telegram API — (target, False).
    """
    try:
        m = _tg_retry_call(
            bot.get_chat_member,
            message.chat.id, target.id,
            retries=3, base_delay=1.0,
        )
        real_user = getattr(m, "user", None) or target
        return real_user, m.status in ("administrator", "creator")
    except Exception:
        return target, False


@bot.message_handler(commands=["mute"])
def cmd_mute(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    target, rest = resolve_target_and_args(message)
    if not target:
        bot.send_message(message.chat.id, "❌ Не вижу цель. Ответь на сообщение пользователя или укажи ID/@username.")
        return

    requested_minutes, reason = parse_duration_and_reason(rest)

    if not require_reason(message, reason, "/mute 30m флуд"):
        return

    target, is_admin = _get_target_and_check_admin(message, target, "mute")
    if is_admin:
        ask_demote_and_continue(message=message, target=target, kind="mute", requested_minutes=requested_minutes, reason=reason)
        return

    db = SessionLocal()
    try:
        ensure_user(db, message.from_user)
        ensure_chat(db, message.chat)
        ensure_user(db, target)
        ensure_chat_member(db, message.chat.id, target.id)

        mult, _pr = probation_multiplier(db, message.chat.id, target.id)
        applied_minutes = requested_minutes * mult if requested_minutes > 0 else 0
        until_date = now_utc() + datetime.timedelta(minutes=applied_minutes) if applied_minutes > 0 else None
        until_ts = to_unix_ts_utc(until_date)

        perms = types.ChatPermissions(can_send_messages=False)
        _tg_retry_call(
            bot.restrict_chat_member,
            message.chat.id, target.id,
            permissions=perms, until_date=until_ts,
            retries=3, base_delay=1.0,
        )

        admin_name = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        save_punishment_record(
            db,
            user_id=target.id, chat_id=message.chat.id,
            p_type="mute", reason=reason,
            admin_id=message.from_user.id, admin_name=admin_name,
            until_date=until_date,
            requested_minutes=requested_minutes, applied_minutes=applied_minutes,
        )

        mult_txt = f" (исп. срок x{mult})" if mult > 1 else ""
        reason_txt = f"\nПричина: {escape_html_text(reason)}" if reason else ""
        bot.send_message(
            message.chat.id,
            f"🔇 Пользователь {format_user_ref_html(target)} замьючен на {human_duration(applied_minutes)}{mult_txt}.{reason_txt}",
        )
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["mutemedia"])
def cmd_mutemedia(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    target, rest = resolve_target_and_args(message)
    if not target:
        bot.send_message(message.chat.id, "❌ Не вижу цель. Ответь на сообщение пользователя или укажи ID/@username.")
        return

    requested_minutes, reason = parse_duration_and_reason(rest)

    if not require_reason(message, reason, "/mutemedia 1h спам-стикеры"):
        return

    target, is_admin = _get_target_and_check_admin(message, target, "mutemedia")
    if is_admin:
        ask_demote_and_continue(message=message, target=target, kind="mutemedia", requested_minutes=requested_minutes, reason=reason)
        return

    db = SessionLocal()
    try:
        ensure_user(db, message.from_user)
        ensure_chat(db, message.chat)
        ensure_user(db, target)
        ensure_chat_member(db, message.chat.id, target.id)

        mult, _pr = probation_multiplier(db, message.chat.id, target.id)
        applied_minutes = requested_minutes * mult if requested_minutes > 0 else 0
        until_date = now_utc() + datetime.timedelta(minutes=applied_minutes) if applied_minutes > 0 else None
        until_ts = to_unix_ts_utc(until_date)

        perms = types.ChatPermissions(
            can_send_messages=True,
            can_send_audios=False, can_send_documents=False,
            can_send_photos=False, can_send_videos=False,
            can_send_video_notes=False, can_send_voice_notes=False,
            can_send_polls=False, can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
        _tg_retry_call(
            bot.restrict_chat_member,
            message.chat.id, target.id,
            permissions=perms, until_date=until_ts,
            retries=3, base_delay=1.0,
        )

        admin_name = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        save_punishment_record(
            db,
            user_id=target.id, chat_id=message.chat.id,
            p_type="mutemedia", reason=reason,
            admin_id=message.from_user.id, admin_name=admin_name,
            until_date=until_date,
            requested_minutes=requested_minutes, applied_minutes=applied_minutes,
        )

        mult_txt = f" (исп. срок x{mult})" if mult > 1 else ""
        reason_txt = f"\nПричина: {escape_html_text(reason)}" if reason else ""
        bot.send_message(
            message.chat.id,
            f"📵 Пользователь {format_user_ref_html(target)} получил медиамут на {human_duration(applied_minutes)}{mult_txt}.{reason_txt}",
        )
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["ban"])
def cmd_ban(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    target, rest = resolve_target_and_args(message)
    if not target:
        bot.send_message(message.chat.id, "❌ Не вижу цель. Ответь на сообщение пользователя или укажи ID/@username.")
        return

    requested_minutes, reason = parse_duration_and_reason(rest)

    if not require_reason(message, reason, "/ban 7d реклама"):
        return

    target, is_admin = _get_target_and_check_admin(message, target, "ban")
    if is_admin:
        bot.send_message(message.chat.id, "❌ Нельзя банить администратора напрямую. Сначала снимите админку.")
        return

    db = SessionLocal()
    try:
        ensure_user(db, message.from_user)
        ensure_chat(db, message.chat)
        ensure_user(db, target)
        ensure_chat_member(db, message.chat.id, target.id)

        mult, _pr = probation_multiplier(db, message.chat.id, target.id)
        applied_minutes = requested_minutes * mult if requested_minutes > 0 else 0
        until_date = now_utc() + datetime.timedelta(minutes=applied_minutes) if applied_minutes > 0 else None
        until_ts = to_unix_ts_utc(until_date)

        _tg_retry_call(
            bot.ban_chat_member,
            message.chat.id, target.id,
            until_date=until_ts, retries=3, base_delay=1.0,
        )

        admin_name = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        save_punishment_record(
            db,
            user_id=target.id, chat_id=message.chat.id,
            p_type="ban", reason=reason,
            admin_id=message.from_user.id, admin_name=admin_name,
            until_date=until_date,
            requested_minutes=requested_minutes, applied_minutes=applied_minutes,
        )

        mult_txt = f" (исп. срок x{mult})" if mult > 1 else ""
        reason_txt = f"\nПричина: {escape_html_text(reason)}" if reason else ""
        bot.send_message(
            message.chat.id,
            f"🚫 Пользователь {format_user_ref_html(target)} забанен на {human_duration(applied_minutes)}{mult_txt}.{reason_txt}",
        )
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["kick"])
def cmd_kick(message: types.Message):
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    target, rest = resolve_target_and_args(message)
    if not target:
        bot.send_message(message.chat.id, "❌ Не вижу цель. Ответь на сообщение пользователя или укажи ID/@username.")
        return

    _, reason = parse_duration_and_reason(rest)

    if not require_reason(message, reason, "/kick оскорбления"):
        return

    target, is_admin = _get_target_and_check_admin(message, target, "kick")
    if is_admin:
        bot.send_message(message.chat.id, "❌ Нельзя кикнуть администратора напрямую. Сначала снимите админку.")
        return

    db = SessionLocal()
    try:
        ensure_user(db, message.from_user)
        ensure_chat(db, message.chat)
        ensure_user(db, target)
        ensure_chat_member(db, message.chat.id, target.id)

        _tg_retry_call(bot.ban_chat_member, message.chat.id, target.id, retries=3, base_delay=1.0)
        _tg_retry_call(bot.unban_chat_member, message.chat.id, target.id, retries=3, base_delay=1.0)

        admin_name = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        save_punishment_record(
            db,
            user_id=target.id, chat_id=message.chat.id,
            p_type="kick", reason=reason,
            admin_id=message.from_user.id, admin_name=admin_name,
            until_date=None, requested_minutes=None, applied_minutes=None,
        )

        reason_txt = f"\nПричина: {escape_html_text(reason)}" if reason else ""
        bot.send_message(
            message.chat.id,
            f"👢 Пользователь {format_user_ref_html(target)} кикнут.{reason_txt}",
        )
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["unmute"])
def cmd_unmute(message: types.Message):
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
        perms = get_chat_default_permissions(message.chat.id)
        _tg_retry_call(
            bot.restrict_chat_member,
            message.chat.id, target.id,
            permissions=perms, until_date=0,
            retries=3, base_delay=1.0,
        )

        admin_name = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        deactivate_active_punishments(
            db,
            chat_id=message.chat.id, user_id=target.id,
            types_to_close=("mute", "mutemedia"),
            removed_by_id=message.from_user.id, removed_by_name=admin_name,
        )

        bot.send_message(message.chat.id, f"✅ Мут снят с {format_user_ref_html(target)}.")
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["unban"])
def cmd_unban(message: types.Message):
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
        _tg_retry_call(
            bot.unban_chat_member,
            message.chat.id, target.id,
            retries=3, base_delay=1.0,
        )

        admin_name = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        deactivate_active_punishments(
            db,
            chat_id=message.chat.id, user_id=target.id,
            types_to_close=("ban",),
            removed_by_id=message.from_user.id, removed_by_name=admin_name,
        )

        bot.send_message(message.chat.id, f"✅ Бан снят с {format_user_ref_html(target)}.")
    except Exception as e:
        db.rollback()
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
    finally:
        db.close()
