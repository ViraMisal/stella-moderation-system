"""Проверка проекта: импорты, конфиг, БД.

Запуск:
  python scripts/check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    print("Проверка Stella")
    print("----------------")

    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        print("[WARN] Файл .env не найден. Создайте его по примеру .env.example")

    try:
        from core import config
    except Exception as e:
        print(f"[FAIL] Не удалось импортировать core.config: {e}")
        return 1

    print(f"[OK] BASE_DIR: {config.BASE_DIR}")
    print(f"[OK] DATABASE_URL: {config.DATABASE_URL}")

    if not config.BOT_TOKEN:
        print("[WARN] BOT_TOKEN пустой (бот не запустится)")

    try:
        from core import models  # noqa
        print("[OK] core.models импортирован")
    except Exception as e:
        print(f"[FAIL] Не удалось импортировать core.models: {e}")
        return 1

    try:
        from web import create_app
        app = create_app()
        print(f"[OK] web.create_app() — {len(app.url_map._rules)} маршрутов")
    except Exception as e:
        print(f"[FAIL] Не удалось импортировать web: {e}")
        return 1

    try:
        if config.BOT_TOKEN:
            import bot  # noqa
            print("[OK] bot импортирован")
        else:
            print("[SKIP] bot не импортирован (нет BOT_TOKEN)")
    except Exception as e:
        print(f"[FAIL] Не удалось импортировать bot: {e}")
        return 1

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
