"""Конвертация таймзон (MSK по умолчанию)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src_utils.logsetup import setup_logging

logger = setup_logging(__name__)

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def get_tz(name: str | None):
    """Безопасно получить таймзону.

    Возвращает ZoneInfo(...) если возможно, иначе fixed-offset UTC+3.
    """
    if ZoneInfo and name:
        try:
            return ZoneInfo(name)
        except Exception:
            # Например ZoneInfoNotFoundError когда нет tzdata
            pass

    # Запасной вариант: Москва = UTC+3
    return timezone(timedelta(hours=3))


DEFAULT_TZ = get_tz("Europe/Moscow")


def to_msk(dt: datetime | None) -> datetime | None:
    """Переводит datetime в МСК (UTC+3).

    Если dt naive — считаем его UTC.
    """
    if not dt:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    try:
        return dt.astimezone(DEFAULT_TZ)
    except Exception:
        # На всякий случай
        return dt


def to_msk_str(dt: datetime | None) -> str:
    d = to_msk(dt)
    if not d:
        return "-"
    return d.strftime("%d.%m.%Y %H:%M")
