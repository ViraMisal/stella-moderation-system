"""Настройки из БД (таблица settings) с кэшем."""

from __future__ import annotations

import time
from typing import Optional

from core.models import SessionLocal, Settings


class SettingsCache:
    def __init__(self, ttl_seconds: int = 5):
        self.ttl = max(1, ttl_seconds)
        self._cache: dict[str, tuple[Optional[str], float]] = {}

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        now = time.time()
        if key in self._cache:
            val, ts = self._cache[key]
            if now - ts < self.ttl:
                return val if val is not None else default

        db = SessionLocal()
        try:
            val = Settings.get(db, key, default)
        finally:
            db.close()

        self._cache[key] = (val, now)
        return val

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key, None)
        if val is None:
            return default
        return str(val).strip().lower() in {"1", "true", "yes", "on"}

    def get_int(self, key: str, default: int = 0) -> int:
        val = self.get(key, None)
        if val is None:
            return default
        try:
            return int(str(val).strip())
        except ValueError:
            return default

    def set(self, key: str, value: Optional[str], updated_by: Optional[str] = None, description: Optional[str] = None):
        db = SessionLocal()
        try:
            Settings.set(db, key, value, description=description, updated_by=updated_by)
        finally:
            db.close()
        # Сбрасываем кэш для этого ключа
        self._cache.pop(key, None)

    def invalidate_all(self):
        self._cache.clear()


settings_cache = SettingsCache(ttl_seconds=5)


# Удобные геттеры

def is_kill_switch_enabled() -> bool:
    return settings_cache.get_bool("kill_switch", default=False)


def get_appeals_chat_id(default: Optional[int] = None) -> Optional[int]:
    raw = settings_cache.get("appeals_chat_id", None)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def get_ai_trigger() -> str:
    return (settings_cache.get("ai_trigger", "стелла") or "стелла").strip()


def is_ai_enabled() -> bool:
    return settings_cache.get_bool("ai_enabled", default=False)


def get_ai_allowed_chats() -> set[int]:
    raw = (settings_cache.get("ai_allowed_chats", "") or "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def get_ai_user_whitelist() -> set[int]:
    raw = (settings_cache.get("ai_user_whitelist", "") or "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def get_ai_user_blacklist() -> set[int]:
    raw = (settings_cache.get("ai_user_blacklist", "") or "").strip()
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def get_ai_rate_limit_seconds() -> int:
    return max(0, settings_cache.get_int("ai_rate_limit_seconds", default=10))


def get_ai_max_history() -> int:
    return max(0, settings_cache.get_int("ai_max_history", default=10))


def get_setting(key: str, default=None):
    return settings_cache.get(key, default)

def get_bool_setting(key: str, default: bool = False) -> bool:
    return settings_cache.get_bool(key, default)

def get_int_setting(key: str, default: int = 0) -> int:
    return settings_cache.get_int(key, default)


