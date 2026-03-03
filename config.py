# Конфигурация перенесена в core/config.py.
# Этот шим сохраняет обратную совместимость — все старые импорты работают.
from core.config import *  # noqa: F401, F403
from core.config import _env, _normalize_database_url, _parse_int_list  # noqa: F401
