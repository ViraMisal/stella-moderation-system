import logging
import os
import sys
from pathlib import Path


def setup_logging(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    # Не добавляем хендлер повторно, если он уже есть
    if logger.handlers:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    handler.setLevel(level)

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    return logger


def force_utf8_console() -> None:
    """Переключаем stdout/stderr на UTF-8.

    На Windows (и иногда на Linux с LANG=C) по умолчанию может быть cp1252 или ascii.
    Эмодзи в логах тогда падают с UnicodeEncodeError. Вызывать один раз при старте.
    """
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
