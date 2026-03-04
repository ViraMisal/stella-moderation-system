"""Утилиты: парсинг аргументов, форматирование, безопасные Telegram-вызовы.

Функции без бизнес-логики — только преобразования и вспомогательные операции.
"""

from __future__ import annotations

import html
import os
import re
import threading
from typing import Optional, Tuple

from telebot import types

from core.models import SessionLocal, User
from handlers.core import _tg_retry_call, bot
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.helpers")

_DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Парсинг
# ---------------------------------------------------------------------------

def get_command_args(message: types.Message) -> str:
    if not message.text:
        return ""
    parts = message.text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def parse_duration_and_reason(text: str) -> Tuple[int, str]:
    """Парсит "<длительность> <причина>", возвращает (minutes, reason).

    Форматы: 30m, 12h, 7d, 90 (минуты), 30s (→ 1 минута минимум).
    Если длительность не распознана — minutes=0, reason=text целиком.
    """
    s = (text or "").strip()
    if not s:
        return 0, ""

    first, *rest = s.split(maxsplit=1)
    rest_text = rest[0].strip() if rest else ""

    if first.isdigit():
        return int(first), rest_text

    m = _DURATION_RE.match(first)
    if not m:
        return 0, s

    val = int(m.group(1))
    unit = m.group(2).lower()

    if unit == "s":
        minutes = max(1, (val + 59) // 60)
    elif unit == "m":
        minutes = val
    elif unit == "h":
        minutes = val * 60
    elif unit == "d":
        minutes = val * 24 * 60
    else:
        minutes = 0

    return minutes, rest_text


def resolve_target_and_args(message: types.Message) -> Tuple[Optional[types.User], str]:
    """Определяет цель команды по reply / @username / числовому ID."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user, get_command_args(message)

    if not message.text:
        return None, ""

    parts = message.text.split()
    if len(parts) < 2:
        return None, ""

    token = parts[1].strip()
    rest = " ".join(parts[2:]).strip() if len(parts) > 2 else ""

    if token.isdigit():
        try:
            uid = int(token)
            return types.User(uid, first_name=str(uid), is_bot=False), rest
        except Exception:
            return None, rest

    if token.startswith("@"):
        uname = token[1:].lower()
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username.ilike(uname)).first()
            if not u:
                return None, rest
            return types.User(u.id, first_name=u.first_name or uname, is_bot=False, username=u.username), rest
        finally:
            db.close()

    return None, rest


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

def human_duration(minutes: int) -> str:
    if minutes <= 0:
        return "навсегда"
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 60 * 24:
        h = minutes // 60
        m = minutes % 60
        return f"{h}ч {m}м" if m else f"{h}ч"
    d = minutes // (60 * 24)
    rem = minutes % (60 * 24)
    if rem == 0:
        return f"{d}д"
    h = rem // 60
    return f"{d}д {h}ч" if h else f"{d}д"


def format_user_ref_html(user: types.User) -> str:
    uname = (getattr(user, "username", None) or "").strip()
    if uname:
        return f"<code>{user.id}</code> (@{html.escape(uname)})"
    return f"<code>{user.id}</code>"


def escape_html_text(text: str) -> str:
    return html.escape((text or "").strip())


# ---------------------------------------------------------------------------
# Telegram-утилиты (используют bot)
# ---------------------------------------------------------------------------

def get_chat_default_permissions(chat_id: int) -> types.ChatPermissions:
    """Возвращает дефолтные права чата для снятия ограничений."""
    try:
        ch = _tg_retry_call(bot.get_chat, chat_id, retries=3, base_delay=1.0)
        perms = getattr(ch, "permissions", None)
        if isinstance(perms, types.ChatPermissions):
            return perms
        if isinstance(perms, dict):
            return types.ChatPermissions(**perms)
    except Exception:
        pass
    return types.ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )


def safe_delete_message(chat_id: int, message_id: int) -> None:
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def notify_private(user_id: int, text: str) -> bool:
    """Пишет в ЛС, возвращает True если ушло."""
    try:
        msg = bot.send_message(user_id, text)
        return msg is not None
    except Exception:
        return False


def send_temp_message(chat_id: int, text: str, ttl_seconds: int = 6) -> None:
    """Отправляет сообщение и удаляет его через ttl_seconds секунд."""
    try:
        msg = bot.send_message(chat_id, text)
        if not msg:
            return
        threading.Timer(ttl_seconds, safe_delete_message, args=(chat_id, msg.message_id)).start()
    except Exception:
        pass


def try_enrich_user_from_chat(chat_id: int, user: types.User) -> types.User:
    """Пытается подтянуть актуальные данные пользователя через get_chat_member."""
    try:
        m = _tg_retry_call(bot.get_chat_member, chat_id, user.id, retries=2, base_delay=0.7)
        real_user = getattr(m, "user", None)
        if real_user:
            return real_user
    except Exception:
        pass
    return user


def get_appeals_chat_id() -> Optional[int]:
    """Читает ID чата для апелляций: сначала из настроек панели, потом из .env."""
    from core.settings import get_setting
    raw = (get_setting("appeals_chat_id", "") or "").strip()
    if not raw:
        raw = (os.getenv("APPEALS_CHAT_ID", "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
