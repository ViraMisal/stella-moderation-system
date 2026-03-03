"""WSGI entrypoint для Gunicorn.

Пример запуска:
  gunicorn -c gunicorn_conf.py wsgi:app
"""

from web import app  # noqa: F401
