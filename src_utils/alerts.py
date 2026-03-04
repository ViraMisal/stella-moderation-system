"""Алерты в Telegram: уведомления суперадмину о критических событиях.

Отправляет напрямую через HTTP (urllib), без зависимости от bot-инстанса —
работает даже если бот упал.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

# Антиспам: не чаще раза в 60 сек на один тип алерта
_COOLDOWN_SEC = 60
_last_sent: dict[str, float] = {}
_lock = threading.Lock()


def _get_token() -> Optional[str]:
    return os.getenv("BOT_TOKEN", "").strip() or None


def _get_admin_ids() -> list[int]:
    raw = os.getenv("SUPERADMIN_IDS", os.getenv("ALLOWED_TG_IDS", ""))
    out = []
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                pass
    return out


def _should_send(alert_type: str) -> bool:
    now = time.time()
    with _lock:
        last = _last_sent.get(alert_type, 0)
        if now - last < _COOLDOWN_SEC:
            return False
        _last_sent[alert_type] = now
        return True


def _send_tg(token: str, chat_id: int, text: str) -> bool:
    """Отправка через Telegram Bot API (urllib, без requests)."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def send_alert(alert_type: str, message: str) -> None:
    """Отправляет алерт суперадминам если не в кулдауне.

    alert_type — ключ для антиспама (bot_started, bot_crash, web_error, db_down).
    message — текст сообщения (поддерживает HTML).
    """
    if not _should_send(alert_type):
        return

    token = _get_token()
    if not token:
        return

    admins = _get_admin_ids()
    if not admins:
        return

    prefix = {
        "bot_started": "[STARTED]",
        "bot_crash": "[CRASH]",
        "web_error": "[WEB ERROR]",
        "db_down": "[DB DOWN]",
    }.get(alert_type, "[ALERT]")

    text = f"<b>{prefix}</b> {message}"

    for uid in admins:
        # В отдельном потоке чтобы не блокировать основной код
        t = threading.Thread(target=_send_tg, args=(token, uid, text), daemon=True)
        t.start()
