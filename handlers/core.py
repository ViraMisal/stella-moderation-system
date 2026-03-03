"""Ядро бота: инстанс TeleBot, ретраи, monkey-patching, глобальное состояние.

Всё остальное импортирует отсюда `bot`, `_tg_retry_call` и общий стейт.
Этот модуль не импортирует другие handlers/* — только внешние зависимости.
"""

from __future__ import annotations

import datetime
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

import telebot
from telebot import types

from core.config import (
    BOT_TOKEN,
    BOT_USERNAME,
)
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.core")

try:
    from telebot import apihelper  # type: ignore
    apihelper.RETRY_ON_ERROR = True
    apihelper.SESSION_TIME_TO_LIVE = int(os.getenv("TG_SESSION_TTL", "300"))
    apihelper.CONNECT_TIMEOUT = int(os.getenv("TG_CONNECT_TIMEOUT", "10"))
    apihelper.READ_TIMEOUT = int(os.getenv("TG_READ_TIMEOUT", "20"))
except Exception:
    pass

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан. Создайте .env из .env.example и укажите BOT_TOKEN."
    )


# ---------------------------------------------------------------------------
# Экземпляр бота
# ---------------------------------------------------------------------------

class _StellaExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        try:
            logger.error("Необработанная ошибка TeleBot: %s", exception, exc_info=True)
        except Exception:
            pass
        return True  # True = поллинг продолжается


bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML",
    skip_pending=True,
    num_threads=4,
    exception_handler=_StellaExceptionHandler(),
)

# ---------------------------------------------------------------------------
# Ретраи для Telegram API
# ---------------------------------------------------------------------------

try:
    from telebot.apihelper import ApiTelegramException  # type: ignore
except Exception:
    ApiTelegramException = Exception  # type: ignore

try:
    from requests.exceptions import RequestException  # type: ignore
except Exception:
    RequestException = Exception  # type: ignore


def _tg_retry_call(fn, *args, retries: int = 3, base_delay: float = 0.7, **kwargs):
    """Вызов Telegram API с ретраями на сетевые ошибки, 429 и 5xx."""
    last_exc = None
    for attempt in range(max(1, retries)):
        try:
            return fn(*args, **kwargs)
        except ApiTelegramException as e:
            last_exc = e
            code = int(getattr(e, "error_code", 0) or 0)
            if code == 429:
                wait = 1
                try:
                    wait = int((getattr(e, "result_json", None) or {}).get("parameters", {}).get("retry_after", 1))
                except Exception:
                    wait = 1
                time.sleep(wait)
                continue
            if code >= 500 and attempt < retries - 1:
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
        except RequestException as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_exc = e
            msg = str(e)
            if attempt < retries - 1 and (
                "RemoteDisconnected" in msg
                or "Connection aborted" in msg
                or "Connection reset" in msg
                or "Read timed out" in msg
                or "Timeout" in msg
            ):
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc


# ---------------------------------------------------------------------------
# Безопасные обёртки для «уведомляющих» методов
# ---------------------------------------------------------------------------

_ORIG_SEND_MESSAGE = bot.send_message
_ORIG_EDIT_MESSAGE_TEXT = bot.edit_message_text
_ORIG_ANSWER_CALLBACK = bot.answer_callback_query


def _send_message_safe(*args, **kwargs):
    try:
        if "message_thread_id" not in kwargs:
            chat_id = args[0] if args else kwargs.get("chat_id")
            ctx_chat = getattr(TOPIC_CTX, "chat_id", None)
            ctx_thread = getattr(TOPIC_CTX, "thread_id", None)
            if ctx_thread and ctx_chat and chat_id == ctx_chat:
                kwargs["message_thread_id"] = int(ctx_thread)
    except Exception:
        pass

    try:
        return _tg_retry_call(_ORIG_SEND_MESSAGE, *args, **kwargs)
    except ApiTelegramException as e:
        if "can't parse entities" in str(e):
            try:
                kwargs2 = dict(kwargs)
                kwargs2["parse_mode"] = None
                return _tg_retry_call(_ORIG_SEND_MESSAGE, *args, **kwargs2)
            except Exception as e2:
                logger.warning("send_message retry(no-parse) error: %s", e2)
        logger.warning("send_message error: %s", e)
        return None
    except Exception as e:
        logger.warning("send_message error: %s", e)
        return None


def _edit_message_text_safe(*args, **kwargs):
    try:
        return _tg_retry_call(_ORIG_EDIT_MESSAGE_TEXT, *args, **kwargs)
    except ApiTelegramException as e:
        if "can't parse entities" in str(e):
            try:
                kwargs2 = dict(kwargs)
                kwargs2["parse_mode"] = None
                return _tg_retry_call(_ORIG_EDIT_MESSAGE_TEXT, *args, **kwargs2)
            except Exception as e2:
                logger.warning("edit_message_text retry(no-parse) error: %s", e2)
        logger.warning("edit_message_text error: %s", e)
        return None
    except Exception as e:
        logger.warning("edit_message_text error: %s", e)
        return None


def _answer_callback_query_safe(*args, **kwargs):
    try:
        return _tg_retry_call(_ORIG_ANSWER_CALLBACK, *args, **kwargs)
    except Exception as e:
        logger.debug("answer_callback_query error: %s", e)
        return None


bot.send_message = _send_message_safe  # type: ignore
bot.edit_message_text = _edit_message_text_safe  # type: ignore
bot.answer_callback_query = _answer_callback_query_safe  # type: ignore

# ---------------------------------------------------------------------------
# Глобальное состояние
# ---------------------------------------------------------------------------

BOT_ID: Optional[int] = None
BOT_USERNAME_EFFECTIVE: Optional[str] = BOT_USERNAME or None

# Ожидающие действия (снять админку + наказать)
PENDING_DEMOTE: Dict[str, Dict[str, Any]] = {}
PENDING_LOCK = threading.Lock()
PENDING_TTL_SECONDS = 10 * 60

# Rate limit для ИИ: (chat_id, user_id) -> timestamp последнего ответа
AI_LAST_TS: Dict[Tuple[int, int], float] = {}

# Троттлинг обновления БД при входящих сообщениях
SEEN_CHATS: set[int] = set()
SEEN_MEMBERS: set[Tuple[int, int]] = set()
TOUCH_CHAT_TS: Dict[int, float] = {}
TOUCH_MEMBER_TS: Dict[Tuple[int, int], float] = {}
TOUCH_CHAT_INTERVAL = 20   # сек
TOUCH_MEMBER_INTERVAL = 30  # сек

SEEN_TOPICS: set[Tuple[int, int]] = set()
TOUCH_TOPIC_TS: Dict[Tuple[int, int], float] = {}
TOUCH_TOPIC_INTERVAL = 60  # сек

TOUCH_LOCK = threading.Lock()

# Троттлинг логов для просроченных наказаний
EXPIRE_FAIL_LOG_TS: Dict[Tuple[int, int, str], float] = {}
EXPIRE_FAIL_LOG_INTERVAL = 5 * 60  # сек

# ---------------------------------------------------------------------------
# Форум-топики: thread-local контекст для send_message
# ---------------------------------------------------------------------------

TOPIC_CTX = threading.local()


def _set_topic_context(message: types.Message) -> None:
    """Запоминает текущий message_thread_id, чтобы bot.send_message отвечал в нужный топик."""
    try:
        TOPIC_CTX.chat_id = message.chat.id
        tid = getattr(message, "message_thread_id", None)
        if tid is None:
            reply = getattr(message, "reply_to_message", None)
            if reply is not None:
                tid = getattr(reply, "message_thread_id", None)
        TOPIC_CTX.thread_id = tid
    except Exception:
        TOPIC_CTX.chat_id = None
        TOPIC_CTX.thread_id = None

# ---------------------------------------------------------------------------
# Утилиты времени
# ---------------------------------------------------------------------------

def now_utc() -> datetime.datetime:
    return datetime.datetime.utcnow()


def to_unix_ts_utc(dt: Optional[datetime.datetime]) -> Optional[int]:
    """naive UTC → unix timestamp. На Windows .timestamp() даёт LOCAL time, поэтому явно ставим tzinfo."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return int(dt.timestamp())
