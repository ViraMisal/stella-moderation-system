#!/usr/bin/env python3
"""Ежедневный отчёт — шлёт статистику суперадмину в ТГ.

Запуск через cron: 0 10 * * * cd /root/stella-prod && .venv/bin/python scripts/daily_report.py
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.models import Punishment, SessionLocal, User  # noqa: E402

# Кулдаун для daily_report — 12 часов (чтобы не задублировалось)
from src_utils.alerts import (  # noqa: E402
    _last_sent,
    _lock,
    send_alert,  # noqa: E402
)

with _lock:
    _last_sent.pop("daily_report", None)  # сбрасываем кулдаун


def main():
    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        day_ago = now - datetime.timedelta(hours=24)

        total_users = db.query(User).count()
        new_users = db.query(User).filter(User.created_at >= day_ago).count()

        total_punishments = db.query(Punishment).filter(Punishment.active == True).count()
        new_punishments = db.query(Punishment).filter(Punishment.date >= day_ago).count()

        lines = [
            f"Юзеров: {total_users} (+{new_users} за 24ч)",
            f"Активных наказаний: {total_punishments}",
            f"Новых наказаний: {new_punishments} за 24ч",
        ]

        send_alert("daily_report", "\n".join(lines))
    finally:
        db.close()


if __name__ == "__main__":
    main()
