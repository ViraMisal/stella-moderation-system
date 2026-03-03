"""ИИ-интеграция: триггеры, история диалога, отправка ответов."""

from __future__ import annotations

import datetime
import random
import re
import threading
from typing import Any, Dict, List, Optional

from telebot import types

from ai_deepseek import deepseek_chat_with_optional_image
from config import (
    AI_DEFAULT_FALLBACK_TEXT,
    AI_DEFAULT_MAX_TOKENS,
    AI_DEFAULT_SYSTEM_PROMPT_IMAGE,
    AI_DEFAULT_SYSTEM_PROMPT_TEXT,
    AI_DEFAULT_TEMPERATURE,
    SUPERADMIN_IDS,
)
from handlers.core import AI_LAST_TS, BOT_ID, BOT_USERNAME_EFFECTIVE, _set_topic_context, bot
from handlers.db import is_user_blacklisted
from handlers.helpers import safe_delete_message, send_temp_message
from models import AIConversation, SessionLocal
from settings_service import get_bool_setting, get_int_setting, get_setting
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.ai")

# Общий контекст ИИ: user_id=0 — одна история на весь чат
AI_SHARED_CONTEXT_USER_ID = 0

_AI_CHAT_LOCKS: Dict[int, threading.Lock] = {}
_AI_CHAT_LOCKS_GUARD = threading.Lock()

_AI_BUG_KEYWORDS = (
    "баг", "ошиб", "вылет", "краш", "лага", "лаг",
    "фриз", "завис", "не работает", "сломал", "сломан",
)

_AI_TIPS = [
    "🛩️ Инструкторская подсказка: держи высоту и не входи в затяжной вираж без нужды — энергия решает бой.",
    "✈️ Подсказка Стеллы: если не уверен в решении — сначала разведай обстановку, потом действуй. Так меньше потерь.",
    "🧭 В «Братстве» важно командное взаимодействие: координация с кланом часто сильнее любого самолёта.",
    "🛠️ Если замечаешь странности или баги — лучше сразу в поддержку: @Warplane_Online_bot. Так мы быстрее найдём проблему.",
    "📍 Иногда лучший манёвр — отступить на удобную позицию. Выжить и вернуться — тоже победа.",
    "🎯 Старайся держать цель в зоне уверенного упреждения. Пара точных очередей лучше длинной «поливки».",
    "🧊 В холодную голову всё считается легче: скорость, высота, дистанция. Паника — враг пилота.",
    "👥 Новичкам нужна опора: пару спокойных подсказок в чате могут сделать их день.",
]

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _ai_lock_for_chat(chat_id: int) -> threading.Lock:
    with _AI_CHAT_LOCKS_GUARD:
        lock = _AI_CHAT_LOCKS.get(chat_id)
        if lock is None:
            lock = threading.Lock()
            _AI_CHAT_LOCKS[chat_id] = lock
        return lock


def _parse_int_list(raw: str) -> List[int]:
    out: List[int] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _is_ai_enabled_for_chat(chat_id: int) -> bool:
    if not get_bool_setting("ai_enabled", False):
        return False
    allowed = _parse_int_list(get_setting("ai_allowed_chats", ""))
    if not allowed:
        return False
    return chat_id in allowed


def _is_ai_user_allowed(user_id: int) -> bool:
    whitelist = set(_parse_int_list(get_setting("ai_user_whitelist", "")))
    blacklist = set(_parse_int_list(get_setting("ai_user_blacklist", "")))
    if user_id in blacklist:
        return False
    if whitelist and user_id not in whitelist:
        return False
    return True


def _ai_rate_limit_ok(chat_id: int, user_id: int) -> bool:
    sec = get_int_setting("ai_rate_limit_seconds", 10)
    if sec <= 0:
        return True
    key = (chat_id, user_id)
    import time
    now = time.time()
    last = AI_LAST_TS.get(key, 0)
    if now - last < sec:
        return False
    AI_LAST_TS[key] = now
    return True


def _get_triggers() -> List[str]:
    raw = (get_setting("ai_trigger", "стелла") or "стелла").strip()
    triggers = [t.strip().lower() for t in raw.replace(";", ",").split(",") if t.strip()]
    return triggers or ["стелла"]


def _ai_get_system_prompt_text() -> str:
    v = (get_setting("ai_system_prompt_text", "") or "").strip()
    return v or AI_DEFAULT_SYSTEM_PROMPT_TEXT


def _ai_get_system_prompt_image() -> str:
    v = (get_setting("ai_system_prompt_image", "") or "").strip()
    return v or AI_DEFAULT_SYSTEM_PROMPT_IMAGE


def _ai_get_temperature() -> float:
    raw = (get_setting("ai_temperature", "") or "").strip()
    if not raw:
        return AI_DEFAULT_TEMPERATURE
    try:
        val = float(raw)
    except ValueError:
        return AI_DEFAULT_TEMPERATURE
    return max(0.0, min(2.0, val))


def _ai_get_max_tokens() -> int:
    raw = (get_setting("ai_max_tokens", "") or "").strip()
    if not raw:
        return int(AI_DEFAULT_MAX_TOKENS)
    try:
        val = int(raw)
    except ValueError:
        return int(AI_DEFAULT_MAX_TOKENS)
    return max(50, min(4000, val))


def _ai_get_fallback_text() -> str:
    v = (get_setting("ai_fallback_text", "") or "").strip()
    return v or AI_DEFAULT_FALLBACK_TEXT


def _extract_prompt_from_text(text: str, triggers: List[str]) -> Optional[str]:
    low = text.strip().lower()

    if BOT_USERNAME_EFFECTIVE:
        mention = "@" + BOT_USERNAME_EFFECTIVE.lower().lstrip("@")
        if mention in low:
            cleaned = re.sub(re.escape(mention), "", text, flags=re.IGNORECASE).strip()
            return cleaned if cleaned else None

    for t in triggers:
        if low.startswith(t):
            cleaned = text[len(text[:len(t)]):].lstrip(" ,:—-\t")
            return cleaned if cleaned else None

    return None


def _ai_looks_like_bug_report(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(t) and any(k in t for k in _AI_BUG_KEYWORDS)


def _ai_support_redirect_text() -> str:
    return (
        "Спасибо за сигнал. Если это баг или техническая проблема — пожалуйста, напишите в поддержку: "
        "@Warplane_Online_bot"
    )


def _ai_random_tip() -> str:
    try:
        return random.choice(_AI_TIPS)
    except Exception:
        return "✈️ Подсказка Стеллы: сохраняй спокойствие и действуй по ситуации."


def _ai_speaker_label(user: types.User) -> str:
    uname = (getattr(user, "username", None) or "").strip()
    if uname:
        return f"@{uname} (id:{user.id})"
    name = " ".join([user.first_name or "", user.last_name or ""]).strip()
    if name:
        return f"{name} (id:{user.id})"
    return f"id:{user.id}"


def _ai_strip_formatting(text: str) -> str:
    """Убирает Markdown/HTML из ответа модели — Telegram в plain-режиме видит ** как символы."""
    if not text:
        return ""
    s = str(text)
    s = _MD_LINK_RE.sub(r"\1: \2", s)
    s = re.sub(r"```(?:\w+)?\n(.*?)```", r"\1", s, flags=re.DOTALL)
    s = s.replace("```", "").replace("`", "")
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", s)
    s = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", s)
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s?>\s?", "", s)
    s = re.sub(r"</?\s*[a-zA-Z][^>]*>", "", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _split_text_chunks(text: str, max_len: int = 3800) -> List[str]:
    if not text:
        return []
    s = text.strip()
    if len(s) <= max_len:
        return [s]
    chunks: List[str] = []
    while s:
        if len(s) <= max_len:
            chunks.append(s)
            break
        cut = s.rfind("\n", 0, max_len)
        if cut < max_len * 0.5:
            cut = max_len
        chunk = s[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        s = s[cut:].lstrip("\n").lstrip()
    return chunks


def _send_plain_text(
    chat_id: int,
    text: str,
    *,
    reply_to_message_id: Optional[int] = None,
    message_thread_id: Optional[int] = None,
) -> None:
    chunks = _split_text_chunks(text, max_len=3800)
    for i, chunk in enumerate(chunks):
        try:
            kwargs = {
                "parse_mode": None,
                "disable_web_page_preview": True,
                "reply_to_message_id": reply_to_message_id if i == 0 else None,
            }
            if message_thread_id is not None:
                kwargs["message_thread_id"] = message_thread_id
            try:
                bot.send_message(chat_id, chunk, **kwargs)
            except TypeError:
                kwargs.pop("message_thread_id", None)
                bot.send_message(chat_id, chunk, **kwargs)
        except Exception:
            pass


def _ai_send_typing(chat_id: int, message_thread_id: Optional[int] = None) -> None:
    try:
        if message_thread_id is not None:
            bot.send_chat_action(chat_id, "typing", message_thread_id=message_thread_id)
        else:
            bot.send_chat_action(chat_id, "typing")
    except TypeError:
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
    except Exception:
        pass


def _load_ai_history(db, chat_id: int) -> List[Dict[str, Any]]:
    rec = db.query(AIConversation).filter_by(chat_id=chat_id, user_id=AI_SHARED_CONTEXT_USER_ID).first()
    if not rec:
        return []
    return rec.get_context()


def _save_ai_history(db, chat_id: int, history: List[Dict[str, Any]]):
    rec = db.query(AIConversation).filter_by(chat_id=chat_id, user_id=AI_SHARED_CONTEXT_USER_ID).first()
    if not rec:
        rec = AIConversation(chat_id=chat_id, user_id=AI_SHARED_CONTEXT_USER_ID)
        db.add(rec)
    rec.set_context(history)
    rec.updated_at = datetime.datetime.utcnow()
    db.commit()


def _trim_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    max_pairs = get_int_setting("ai_max_history", 12)
    if max_pairs <= 0:
        return []
    return history[-max_pairs:]


def _ai_should_handle_text(message: types.Message) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False
    if not message.text:
        return False
    if message.text.startswith("/"):
        return False
    if not _is_ai_enabled_for_chat(message.chat.id):
        return False

    if not message.from_user:
        return False

    db = SessionLocal()
    try:
        if is_user_blacklisted(db, message.from_user.id):
            return False
    finally:
        db.close()

    if not _is_ai_user_allowed(message.from_user.id):
        return False

    if not _ai_rate_limit_ok(message.chat.id, message.from_user.id):
        return False

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and BOT_ID
        and message.reply_to_message.from_user.id == BOT_ID
    ):
        return True

    triggers = _get_triggers()
    return _extract_prompt_from_text(message.text, triggers) is not None


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["aiclear", "aireset", "resetai"])
def cmd_aiclear(message: types.Message):
    """Очищает историю ИИ для текущего чата. Только суперадмины."""
    _set_topic_context(message)

    if message.chat.type in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)

    if not message.from_user or message.from_user.id not in SUPERADMIN_IDS:
        if message.chat.type in ("group", "supergroup"):
            send_temp_message(message.chat.id, "❌ Только для суперадминов.", ttl_seconds=8)
        else:
            bot.send_message(message.chat.id, "❌ Только для суперадминов.")
        return

    chat_id = message.chat.id

    lock = _ai_lock_for_chat(chat_id)
    with lock:
        db = SessionLocal()
        try:
            conv = (
                db.query(AIConversation)
                .filter_by(chat_id=chat_id, user_id=AI_SHARED_CONTEXT_USER_ID)
                .first()
            )
            if conv:
                conv.messages_json = "[]"
                conv.updated_at = datetime.datetime.utcnow()
                db.add(conv)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    for key in list(AI_LAST_TS.keys()):
        try:
            if key[0] == chat_id:
                AI_LAST_TS.pop(key, None)
        except Exception:
            pass

    if message.chat.type in ("group", "supergroup"):
        send_temp_message(message.chat.id, "✅ Контекст Стеллы очищен.", ttl_seconds=10)
    else:
        bot.send_message(message.chat.id, "✅ Контекст Стеллы очищен.")


@bot.message_handler(commands=["stella_tip", "stella_fact", "tip", "fact"])
def cmd_stella_tip(message: types.Message):
    """Выдаёт случайную «капитанскую подсказку»."""
    _set_topic_context(message)

    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)
    if thread_id is None and getattr(message, "reply_to_message", None) is not None:
        thread_id = getattr(message.reply_to_message, "message_thread_id", None)

    reply_to_id = None
    if getattr(message, "reply_to_message", None) is not None:
        try:
            reply_to_id = message.reply_to_message.message_id
        except Exception:
            reply_to_id = None

    if message.chat.type in ("group", "supergroup"):
        safe_delete_message(chat_id, message.message_id)

    tip = _ai_random_tip()
    _send_plain_text(chat_id, tip, reply_to_message_id=reply_to_id, message_thread_id=thread_id)


# ---------------------------------------------------------------------------
# Основной AI-обработчик
# ---------------------------------------------------------------------------

@bot.message_handler(func=_ai_should_handle_text, content_types=["text"])
def ai_text(message: types.Message):
    _set_topic_context(message)

    prompt: Optional[str] = None
    try:
        if (
            getattr(message, "reply_to_message", None) is not None
            and getattr(message.reply_to_message, "from_user", None) is not None
            and BOT_ID
            and message.reply_to_message.from_user.id == BOT_ID
        ):
            prompt = (message.text or "").strip()
        else:
            prompt = _extract_prompt_from_text(message.text or "", _get_triggers())
    except Exception:
        prompt = _extract_prompt_from_text(message.text or "", _get_triggers())

    if not prompt:
        return

    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)
    if thread_id is None and getattr(message, "reply_to_message", None) is not None:
        thread_id = getattr(message.reply_to_message, "message_thread_id", None)

    # Быстрый ответ на баг-репорты без обращения к модели
    if _ai_looks_like_bug_report(prompt):
        reply_clean = _ai_support_redirect_text()
        _send_plain_text(chat_id, reply_clean, reply_to_message_id=message.message_id, message_thread_id=thread_id)
        lock = _ai_lock_for_chat(chat_id)
        with lock:
            db = SessionLocal()
            try:
                history = _load_ai_history(db, chat_id)
                speaker = _ai_speaker_label(message.from_user)
                history.append({"role": "user", "content": f"{speaker}: {prompt}"})
                history.append({"role": "assistant", "content": reply_clean})
                history = _trim_history(history)
                _save_ai_history(db, chat_id, history)
            finally:
                db.close()
        return

    _ai_send_typing(chat_id, message_thread_id=thread_id)

    lock = _ai_lock_for_chat(chat_id)
    with lock:
        db = SessionLocal()
        try:
            history = _load_ai_history(db, chat_id)
        finally:
            db.close()

        speaker = _ai_speaker_label(message.from_user)
        user_content = f"{speaker}: {prompt}"

        messages = [{"role": "system", "content": _ai_get_system_prompt_text()}]

        if message.from_user and (
            (message.from_user.username or "").lower() in {"redikin"}
            or message.from_user.id in SUPERADMIN_IDS
        ):
            messages.append({
                "role": "system",
                "content": "Особая пометка: @redikin — создатель/суперадмин. С ним можно быть чуть теплее и игривее, но оставайся в образе Стеллы.",
            })

        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_content})

        reply = deepseek_chat_with_optional_image(
            messages=messages,
            max_tokens=_ai_get_max_tokens(),
            temperature=_ai_get_temperature(),
        )
        if not reply:
            reply = _ai_get_fallback_text()

        reply_clean = _ai_strip_formatting(reply)

        _send_plain_text(
            chat_id, reply_clean,
            reply_to_message_id=message.message_id,
            message_thread_id=thread_id,
        )

        history = list(history) if history else []
        history.append({"role": "user", "content": user_content})
        history.append({"role": "assistant", "content": reply_clean})
        history = _trim_history(history)

        db = SessionLocal()
        try:
            _save_ai_history(db, chat_id, history)
        finally:
            db.close()
