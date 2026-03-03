"""Точка входа проекта.

Использование:
  python run.py bot   # запустить только Telegram-бота
  python run.py web   # запустить только веб-панель (Flask)
  python run.py all   # бот + веб-панель в одном процессе (в разных потоках)

Для продакшена обычно удобнее запускать бота и веб-панель как два отдельных сервиса.
"""

from __future__ import annotations

import sys
import threading

from src_utils.logsetup import force_utf8_console

# Стараемся сразу включить UTF-8 для вывода. Это снижает шанс крашей логов
# на Windows (особенно если в названиях чатов/пользователей есть эмодзи).
force_utf8_console()

from core.config import WEB_HOST, WEB_PORT


def run_web() -> None:
    from web import app
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)


def run_bot() -> None:
    from bot import start_bot
    start_bot()


def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "all").strip().lower()

    if mode == "web":
        run_web()
        return

    if mode == "bot":
        run_bot()
        return

    if mode == "all":
        t = threading.Thread(target=run_web, daemon=True)
        t.start()
        run_bot()
        return

    raise SystemExit("Неизвестный режим. Используйте: bot | web | all")


if __name__ == "__main__":
    main()
