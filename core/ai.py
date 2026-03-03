"""Клиент DeepSeek Chat API."""

from __future__ import annotations

import base64
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from src_utils.logsetup import setup_logging

logger = setup_logging(__name__)


class DeepSeekError(RuntimeError):
    """Общая ошибка DeepSeek клиента."""


def _endpoint(path: str) -> str:
    base = DEEPSEEK_BASE_URL.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


# --- requests.Session с ретраями ---
# Это сильно повышает стабильность на локалке/ВДС, особенно при плохой сети.
_SESSION = requests.Session()

_retry = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=0.7,  # небольшая пауза между попытками
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("POST",),
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=10, pool_maxsize=10)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: Optional[str] = None,
    max_tokens: int = 600,
    temperature: float = 0.7,
    timeout_seconds: int = 40,
) -> str:
    """Обычный (не стриминговый) запрос к чату DeepSeek.

    timeout_seconds — общий read-timeout. Connect-timeout ставим короче.
    """

    if not DEEPSEEK_API_KEY:
        raise DeepSeekError("DEEPSEEK_API_KEY не задан")

    payload: dict[str, Any] = {
        "model": model or DEEPSEEK_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # На практике это снижает вероятность "протухшего" keep-alive соединения.
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
        "Connection": "close",
    }

    # timeout в requests можно задавать кортежем: (connect_timeout, read_timeout)
    connect_timeout = min(10, max(3, timeout_seconds // 4))
    timeout = (connect_timeout, max(10, timeout_seconds))

    try:
        resp = _SESSION.post(
            _endpoint("/chat/completions"),
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as e:
        # Сюда попадает как раз RemoteDisconnected/Connection aborted и т.п.
        raise DeepSeekError(f"Сетевая ошибка: {e}") from e

    if resp.status_code >= 400:
        # Попробуем достать человеческую ошибку
        try:
            data = resp.json()
            msg = (
                data.get("error", {}).get("message")
                or data.get("message")
                or resp.text
            )
        except Exception:
            msg = resp.text
        raise DeepSeekError(f"Ошибка DeepSeek API {resp.status_code}: {msg}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        raise DeepSeekError(f"Некорректный формат ответа DeepSeek: {e}") from e

    return (content or "").strip()


def chat_with_optional_image(
    *,
    system_prompt: str,
    user_prompt: str,
    history: list[dict[str, Any]] | None = None,
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    max_tokens: int = 600,
    temperature: float = 0.7,
) -> str:
    """Пытаемся отправить картинку через OpenAI vision-схему.

    DeepSeek может не поддерживать vision для конкретной модели — тогда
    мы откатываемся на text-only.
    """

    history = history or []

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)

    if image_bytes and image_mime:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content: list[dict[str, Any]] = [
            {"type": "text", "text": user_prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_mime};base64,{b64}"},
            },
        ]
        messages.append({"role": "user", "content": content})

        try:
            return chat_completion(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except DeepSeekError as e:
            logger.warning(
                "Не удалось обработать изображение через DeepSeek — откатываюсь на текстовый режим: %s", e
            )

    # только текст
    messages.append({"role": "user", "content": user_prompt})
    return chat_completion(messages, max_tokens=max_tokens, temperature=temperature)


def deepseek_chat_with_optional_image(
    *,
    messages: list[dict[str, Any]],
    image_bytes: bytes | None = None,
    image_mime: str | None = None,
    max_tokens: int = 600,
    temperature: float = 0.7,
) -> str:
    """Совместимая обёртка под старый вызов из bot.py.

    bot.py передаёт полный список messages (system + history + user).
    Если прилетела картинка — пытаемся прикрепить её к последнему user-сообщению.
    """

    if not messages:
        raise DeepSeekError("messages пустой")

    # Копируем поверхностно, чтобы не мутировать исходный список
    msgs = [dict(m) for m in messages]

    if image_bytes:
        mime = image_mime or "image/jpeg"

        last_user_idx = None
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is None:
            msgs.append({"role": "user", "content": ""})
            last_user_idx = len(msgs) - 1

        user_text = msgs[last_user_idx].get("content")
        if isinstance(user_text, list):
            # Уже структурированный контент, не трогаем
            user_text = ""
        if not isinstance(user_text, str):
            user_text = ""

        b64 = base64.b64encode(image_bytes).decode("ascii")
        msgs[last_user_idx]["content"] = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]

        try:
            return chat_completion(msgs, max_tokens=max_tokens, temperature=temperature)
        except DeepSeekError as e:
            logger.warning(
                "Не удалось обработать изображение через DeepSeek — откатываюсь на текстовый режим: %s", e
            )
            msgs[last_user_idx]["content"] = user_text

    return chat_completion(msgs, max_tokens=max_tokens, temperature=temperature)
