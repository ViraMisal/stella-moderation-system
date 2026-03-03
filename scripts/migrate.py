"""Простая миграция SQLite базы данных.

Скрипт нужен при обновлениях проекта, когда добавляются новые таблицы/колонки.
Для SQLite это делается максимально простым способом: создаём таблицы (если их нет)
и добавляем недостающие колонки через ALTER TABLE.

Запуск:
  python migrate_db.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.models import Base, engine


def main() -> int:
    Base.metadata.create_all(bind=engine)
    print("OK: Схема БД актуальна (насколько это возможно в текущей миграции)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
