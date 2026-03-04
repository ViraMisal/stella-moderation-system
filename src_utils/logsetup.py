import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_HUMAN_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_HUMAN_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _JsonFormatter(logging.Formatter):
    """JSON-формат логов для прода."""

    def format(self, record):
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _add_file_handler(logger: logging.Logger, name: str, level: int) -> None:
    """Пишем логи в файл если задан LOG_DIR."""
    log_dir = os.getenv("LOG_DIR", "").strip()
    if not log_dir:
        return

    try:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)

        # Имя файла: bot.core -> bot_core.log
        safe_name = name.replace(".", "_")
        fh = RotatingFileHandler(
            path / f"{safe_name}.log",
            maxBytes=5 * 1024 * 1024,  # 5 МБ
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(_HUMAN_FMT, datefmt=_HUMAN_DATEFMT))
        logger.addHandler(fh)
    except Exception:
        # Не ломаем запуск если не получилось писать в файл
        pass


def setup_logging(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)

    if os.getenv("ENV", "development").lower() == "production":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_HUMAN_FMT, datefmt=_HUMAN_DATEFMT))

    handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    _add_file_handler(logger, name, level)

    return logger


def force_utf8_console() -> None:
    """Переключаем stdout/stderr на UTF-8."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
