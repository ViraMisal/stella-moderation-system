"""Telegram-бот модерации «Стелла».

Этот файл — точка сборки: импортирует все блоки-хендлеры и запускает поллинг.
Сама логика — в handlers/*.py.

Порядок импортов важен:
  1. system — регистрирует track_activity_handler с ContinueHandling (должен быть первым)
  2. moderation, probation, appeals, demote — командные хендлеры
  3. ai — текстовый хендлер (последним, чтобы не перехватывал команды)
"""

from __future__ import annotations

import datetime
import threading
import time

import handlers.ai  # noqa: F401 — /aiclear /tip + ai_text
import handlers.appeals  # noqa: F401 — /appeal
import handlers.demote  # noqa: F401 — cb_demote callback
import handlers.moderation  # noqa: F401 — /mute /mutemedia /ban /kick /unmute /unban
import handlers.probation  # noqa: F401 — /probation /unprobation

# Каждый импорт вешает хендлеры через @bot.message_handler
import handlers.system  # noqa: F401 — track_activity, on_my_chat_member, /start /scan /where
from core.config import BOT_ALLOWED_UPDATES
from core.models import Probation, Punishment, SessionLocal

# Импорт core создаёт bot-инстанс и глобальное состояние
from handlers.core import (
    EXPIRE_FAIL_LOG_INTERVAL,
    EXPIRE_FAIL_LOG_TS,
    _tg_retry_call,
    bot,
    now_utc,
)
from handlers.helpers import get_chat_default_permissions
from src_utils.logsetup import setup_logging

logger = setup_logging("bot")


# Фоновая очистка истёкших наказаний

def cleanup_loop():
    """Фоновый поток: снимает истёкшие наказания и чистит просроченные испытательные сроки.

    Telegram снимает временные муты сам, но мы подстраховываемся — бывают случаи
    когда ограничение «залипает» после рестарта.
    """
    def _is_nonfatal_tg_error(err: Exception) -> bool:
        msg = str(err).lower()
        nonfatal = (
            "user not participant", "user_not_participant",
            "member not found", "chat not found",
            "user_id_invalid", "not in the chat",
            "user is not a member", "user is not banned", "not banned",
        )
        return any(pat in msg for pat in nonfatal)

    while True:
        try:
            db = SessionLocal()
            try:
                now = now_utc()

                expired = (
                    db.query(Punishment)
                    .filter(
                        Punishment.active == True,
                        Punishment.until_date.isnot(None),
                        Punishment.until_date <= now,
                    )
                    .all()
                )

                # Запасной вариант: until_date не записался, но есть applied_duration_minutes
                fallback = (
                    db.query(Punishment)
                    .filter(
                        Punishment.active == True,
                        Punishment.until_date.is_(None),
                        Punishment.applied_duration_minutes.isnot(None),
                        Punishment.applied_duration_minutes > 0,
                    )
                    .all()
                )
                for p in fallback:
                    if p.date and (p.date + datetime.timedelta(minutes=p.applied_duration_minutes)) <= now:
                        expired.append(p)

                for p in expired:
                    ptype = (p.type or "").lower()
                    ok = True

                    try:
                        if ptype in ("mute", "mutemedia", "media_mute"):
                            perms = get_chat_default_permissions(p.chat_id)
                            _tg_retry_call(
                                bot.restrict_chat_member,
                                p.chat_id, p.user_id,
                                permissions=perms, until_date=0,
                                retries=3, base_delay=1.0,
                            )
                        elif ptype == "ban":
                            _tg_retry_call(
                                bot.unban_chat_member,
                                p.chat_id, p.user_id,
                                retries=3, base_delay=1.0,
                            )
                    except Exception as e:
                        if _is_nonfatal_tg_error(e):
                            ok = True
                        else:
                            ok = False
                            key = (p.chat_id, p.user_id, ptype)
                            now_ts = time.time()
                            last_ts = EXPIRE_FAIL_LOG_TS.get(key, 0)
                            if now_ts - last_ts >= EXPIRE_FAIL_LOG_INTERVAL:
                                logger.warning(
                                    "Не удалось снять истёкшее наказание (chat=%s user=%s type=%s): %s",
                                    p.chat_id, p.user_id, p.type, e,
                                )
                                EXPIRE_FAIL_LOG_TS[key] = now_ts
                            else:
                                logger.debug(
                                    "Повторная ошибка снятия наказания (chat=%s user=%s type=%s): %s",
                                    p.chat_id, p.user_id, p.type, e,
                                )

                    if ok:
                        p.active = False
                        p.removed_at = now
                        p.removed_by_name = "system"
                        db.add(p)

                # Чистим просроченные испытательные сроки
                for pr in db.query(Probation).filter(Probation.until_date <= now).all():
                    db.delete(pr)

                db.commit()

            finally:
                db.close()
        except Exception as e:
            logger.warning("cleanup loop error: %s", e)

        time.sleep(30)


# Запуск

def start_bot():
    global BOT_USERNAME_EFFECTIVE

    # Получаем ID бота (нужен для AI-обработчика) и username с ретраями
    while True:
        try:
            me = _tg_retry_call(bot.get_me, retries=5, base_delay=1.0)
            import handlers.core as _core
            _core.BOT_ID = me.id
            if not _core.BOT_USERNAME_EFFECTIVE:
                _core.BOT_USERNAME_EFFECTIVE = getattr(me, "username", None)
            break
        except Exception as e:
            logger.warning("Не удалось выполнить bot.get_me(): %s", e)
            time.sleep(3)

    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()

    logger.info("Bot started")

    while True:
        try:
            try:
                bot.infinity_polling(timeout=30, long_polling_timeout=30, allowed_updates=BOT_ALLOWED_UPDATES)
            except TypeError:
                bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except KeyboardInterrupt:
            logger.info("Bot stopped by KeyboardInterrupt")
            break
        except Exception as e:
            logger.error("Polling crashed: %s", e)
            time.sleep(3)
            continue


if __name__ == "__main__":
    start_bot()
