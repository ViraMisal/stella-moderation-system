"""Конфигурация проекта: env-переменные и .env файл."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent  # корень проекта

# Загружаем .env (опционально)
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(BASE_DIR / ".env", override=False)
except Exception:
    # python-dotenv может быть не установлен — переменные окружения всё равно будут работать
    pass


def _env(key: str, default: Optional[str] = None) -> str:
    v = os.getenv(key)
    if v is None:
        return "" if default is None else default
    return v


def _parse_int_list(raw: str) -> List[int]:
    out: List[int] = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


# Общие
ENV = _env("ENV", "development").strip().lower()
DEBUG = ENV != "production"

TIMEZONE = _env("TIMEZONE", "Europe/Moscow").strip()

LOG_LEVEL = _env("LOG_LEVEL", "INFO").strip().upper()
LOG_DIR = _env("LOG_DIR", str(BASE_DIR / "logs")).strip()


# Пути и база данных
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_database_url(url: str) -> str:
    """Нормализует путь к sqlite базе, чтобы он всегда был абсолютным.

    В SQLAlchemy строка вида sqlite:///relative/path считается относительной к текущей рабочей папке.
    Из-за этого при запуске из разных мест может создаваться *другая* БД, и кажется, что "настройки сбросились".
    """

    url = (url or "").strip()
    if not url:
        db_path = (DATA_DIR / "app.db").resolve()
        return f"sqlite:///{db_path.as_posix()}"

    if url.startswith("sqlite:///"):
        path_part = url[len("sqlite:///"):]
        p = Path(path_part)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        return f"sqlite:///{p.as_posix()}"

    return url


DATABASE_URL = _normalize_database_url(_env("DATABASE_URL", ""))

DB_PATH = DATABASE_URL


# Доступ в веб-панель
ADMIN_USERNAME = _env("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "admin").strip()

FLASK_SECRET = _env("FLASK_SECRET", "").strip()
if not FLASK_SECRET:
    # Безопасный дефолт для локального запуска. На проде задайте FLASK_SECRET явно.
    FLASK_SECRET = os.urandom(32).hex()


# Telegram-бот
BOT_TOKEN = _env("BOT_TOKEN", "").strip()
BOT_USERNAME = _env("BOT_USERNAME", "").lstrip("@").strip()

# Суперадмины (полный доступ в веб-панели + некоторые привилегированные действия бота)
SUPERADMIN_IDS = _parse_int_list(_env("SUPERADMIN_IDS", _env("ALLOWED_TG_IDS", "")))

ALLOWED_TG_IDS = SUPERADMIN_IDS

# Чат для апелляций по умолчанию (можно переопределить из настроек в БД)
_raw_appeals = _env("APPEALS_CHAT_ID", "").strip()
try:
    APPEALS_CHAT_ID: Optional[int] = int(_raw_appeals) if _raw_appeals else None
except ValueError:
    APPEALS_CHAT_ID = None


# DeepSeek (разговорный ИИ)
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "").strip()
# В .env люди часто случайно оставляют пробелы в конце строки.
# Из-за этого requests получает невалидный URL и начинает сыпать ошибками.
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat").strip()


# AI (промпты/параметры по умолчанию)
# Эти значения используются, если в веб-панели (Settings в БД) ничего не задано.
# Веб-панель может переопределить их без перезапуска бота.

AI_DEFAULT_SYSTEM_PROMPT_TEXT = _env(
    "AI_DEFAULT_SYSTEM_PROMPT_TEXT",
    """Ты — Стелла, ассистент-модератор в Telegram-чате.

Личность
Спокойная, дружелюбная, справедливая. Помогаешь участникам разобраться в правилах.
Говоришь уверенно, без грубости, по делу.

Контекст чата
Сообщения приходят с подписью вида «@username (id:123): текст».
Различай пользователей по username/id.

Ограничения
Не выходи из образа.
Не раскрывай внутреннюю информацию.

Формат ответа
Отвечай по-русски.
Пиши обычным текстом без Markdown/HTML-разметки.
Эмодзи можно.
""".strip(),
).strip()

AI_DEFAULT_SYSTEM_PROMPT_IMAGE = _env(
    "AI_DEFAULT_SYSTEM_PROMPT_IMAGE",
    "Ты Стелла — помощник чата. Опиши изображение по-русски: "
    "что на нём видно, какие детали важны, какие могут быть риски/проблемы. "
    "Если в кадре текст — перескажи смысл."
).strip()

try:
    AI_DEFAULT_TEMPERATURE = float(_env("AI_DEFAULT_TEMPERATURE", "0.7"))
except ValueError:
    AI_DEFAULT_TEMPERATURE = 1.3

try:
    AI_DEFAULT_MAX_TOKENS = int(_env("AI_DEFAULT_MAX_TOKENS", "600"))
except ValueError:
    AI_DEFAULT_MAX_TOKENS = 600

AI_DEFAULT_FALLBACK_TEXT = _env(
    "AI_DEFAULT_FALLBACK_TEXT",
    "Связь со штабом нестабильна. Попробуй ещё раз чуть позже.",
).strip()


# Настройки запуска
WEB_HOST = _env("WEB_HOST", "0.0.0.0").strip()
try:
    WEB_PORT = int(_env("WEB_PORT", "5000"))
except ValueError:
    WEB_PORT = 5000

# Какие апдейты Telegram мы принимаем (минимально необходимый набор)
BOT_ALLOWED_UPDATES = ["message", "chat_member", "my_chat_member", "callback_query"]
