"""Вспомогательные функции для работы с Flask-сессией.

Вынесены отдельно, чтобы их могли импортировать все blueprint-ы
без кругового импорта через web/__init__.py.
"""
from __future__ import annotations

from flask import session


def get_current_admin_info():
    """Возвращает (admin_id, admin_name, role, admin_chats) из сессии."""
    who = session.get("who", "unknown")
    admin_id = session.get("admin_id")
    role = session.get("role", "user")
    admin_chats = session.get("admin_chats", [])
    return admin_id, who, role, admin_chats


def is_current_superadmin() -> bool:
    return session.get("role") == "superadmin"


def get_accessible_chats():
    """None = супер-админ (видит всё), список = только свои чаты."""
    return None if is_current_superadmin() else session.get("admin_chats", [])
