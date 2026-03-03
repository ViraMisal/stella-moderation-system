"""Утилиты веб-панели: логирование действий, парсинг длительности, работа с Telegram."""
from __future__ import annotations

import datetime

from flask import current_app, request

from core.models import AdminLog, SessionLocal


def log_admin_action(action: str, details=None, admin_id=None, admin_name=None):
    """Записывает действие администратора в таблицу admin_logs."""
    from web.context import get_current_admin_info
    if admin_id is None or admin_name is None:
        admin_id, admin_name, _, _ = get_current_admin_info()

    db = SessionLocal()
    try:
        db.add(AdminLog(
            admin_id=admin_id,
            admin_name=admin_name or "unknown",
            action=action,
            details=details,
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        ))
        db.commit()
    except Exception as e:
        current_app.logger.error("Ошибка логирования действия: %s", e)
    finally:
        db.close()


def parse_duration_to_minutes(duration: str) -> int:
    """Парсит длительность в минуты.

    Форматы: 10m / 10мин, 2h / 2ч, 1d / 1д, или просто число (минуты).
    Бросает ValueError при некорректном вводе.
    """
    s = (duration or "").strip().lower()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    unit = s[-1]
    num = s[:-1]
    if num.isdigit() and unit in ("m", "h", "d"):
        n = int(num)
        if unit == "m":
            return n
        if unit == "h":
            return n * 60
        if unit == "d":
            return n * 1440
    raise ValueError(f"Некорректная длительность: {duration!r}")


def to_unix_ts_utc(dt: datetime.datetime | None) -> int | None:
    """Переводит datetime в unix timestamp UTC (корректно даже на Windows)."""
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return int(dt.timestamp())


def get_tbot(token: str):
    """Создаёт TeleBot-инстанс для разовых запросов из веб-панели."""
    import telebot
    if not token or ":" not in token:
        raise ValueError("BOT_TOKEN не задан или некорректен")
    return telebot.TeleBot(token)
