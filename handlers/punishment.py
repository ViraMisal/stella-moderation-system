"""Наказания: сохранение в БД, деактивация, испытательный срок."""

from __future__ import annotations

import datetime
import html
from typing import Optional, Tuple

from telebot import types

from handlers.core import now_utc
from handlers.db import is_user_blacklisted
from handlers.helpers import get_appeals_chat_id, human_duration
from models import Chat, Probation, Punishment, SessionLocal
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.punishment")


def probation_multiplier(db, chat_id: int, user_id: int) -> Tuple[int, Optional[Probation]]:
    """Возвращает (множитель, запись испытательного срока). Множитель = 2 если срок активен."""
    pr = db.query(Probation).filter_by(chat_id=chat_id, user_id=user_id).first()
    if not pr:
        return 1, None
    if pr.until_date and pr.until_date > now_utc():
        return 2, pr
    # Срок истёк — чистим
    try:
        db.delete(pr)
        db.commit()
    except Exception:
        db.rollback()
    return 1, None


def save_punishment_record(
    db,
    *,
    user_id: int,
    chat_id: int,
    p_type: str,
    reason: str,
    admin_id: int,
    admin_name: str,
    until_date: Optional[datetime.datetime],
    requested_minutes: Optional[int],
    applied_minutes: Optional[int],
) -> Punishment:
    p = Punishment(
        user_id=user_id,
        chat_id=chat_id,
        type=p_type,
        reason=reason,
        admin_id=admin_id,
        admin_name=admin_name,
        date=now_utc(),
        until_date=until_date,
        active=False if p_type == "kick" else True,
        requested_duration_minutes=requested_minutes,
        applied_duration_minutes=applied_minutes,
    )
    db.add(p)
    db.commit()

    # Уведомляем пользователя в ЛС
    try:
        chat_obj = db.get(Chat, chat_id)
        chat_title = (chat_obj.title if chat_obj else None) or str(chat_id)
    except Exception:
        chat_title = str(chat_id)

    if not is_user_blacklisted(db, user_id):
        dur = human_duration(applied_minutes or 0)

        msg = (
            f"⚠️ Вам выдано наказание в чате <b>{html.escape(chat_title)}</b>\n\n"
            f"Тип: <b>{html.escape(str(p_type))}</b>\n"
            f"Срок: <b>{html.escape(dur)}</b>"
        )
        if reason:
            msg += f"\nПричина: {html.escape(reason)}"

        appeal_chat = get_appeals_chat_id()
        if appeal_chat:
            msg += "\n\nЕсли вы не согласны — напишите /appeal &lt;текст&gt; мне в личку."

        from handlers.helpers import notify_private
        notify_private(user_id, msg)

    return p


def deactivate_active_punishments(
    db,
    *,
    chat_id: int,
    user_id: int,
    types_to_close: Tuple[str, ...],
    removed_by_id: int,
    removed_by_name: str,
):
    now = now_utc()
    updated = (
        db.query(Punishment)
        .filter(
            Punishment.chat_id == chat_id,
            Punishment.user_id == user_id,
            Punishment.active == True,
            Punishment.type.in_(types_to_close),
        )
        .all()
    )
    for p in updated:
        p.active = False
        p.removed_at = now
        p.removed_by_id = removed_by_id
        p.removed_by_name = removed_by_name
        db.add(p)
    db.commit()
