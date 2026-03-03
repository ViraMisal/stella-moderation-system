"""Gunicorn конфиг (удобно для VDS).

Параметры можно переопределять через переменные окружения:
- GUNICORN_BIND (по умолчанию 127.0.0.1:8000)
- GUNICORN_WORKERS (по умолчанию 2)
- GUNICORN_TIMEOUT (по умолчанию 30)
- GUNICORN_LOGLEVEL (по умолчанию info)

Логи по умолчанию уходят в stdout/stderr, поэтому их удобно смотреть через journalctl.
"""

import os

bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")

# В проде обычно лучше не включать reload
reload = os.getenv("GUNICORN_RELOAD", "0") in ("1", "true", "True", "yes")

# Логи
accesslog = os.getenv("GUNICORN_ACCESSLOG", "-")  # '-' => stdout
errorlog = os.getenv("GUNICORN_ERRORLOG", "-")    # '-' => stderr
