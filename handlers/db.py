"""Работа с базой данных: создание/обновление записей, троттлинг touch_activity.

Всё, что касается синхронизации БД с Telegram-апдейтами, живёт здесь.
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from telebot import types

from handlers.core import (
    SEEN_CHATS,
    SEEN_MEMBERS,
    SEEN_TOPICS,
    TOUCH_CHAT_INTERVAL,
    TOUCH_CHAT_TS,
    TOUCH_LOCK,
    TOUCH_MEMBER_INTERVAL,
    TOUCH_MEMBER_TS,
    TOUCH_TOPIC_INTERVAL,
    TOUCH_TOPIC_TS,
    now_utc,
)
from models import (
    Chat,
    ChatMember,
    ChatTopic,
    RoleAssignment,
    SessionLocal,
    User,
)
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.db")


# ---------------------------------------------------------------------------
# Создание/обновление записей
# ---------------------------------------------------------------------------

def ensure_user(db, tg_user: types.User) -> User:
    u = db.get(User, tg_user.id)
    if not u:
        u = User(id=tg_user.id)
        db.add(u)
    u.username = tg_user.username
    u.first_name = tg_user.first_name
    u.last_name = tg_user.last_name
    u.last_activity = now_utc()
    return u


def ensure_chat(db, tg_chat: types.Chat) -> Chat:
    c = db.get(Chat, tg_chat.id)
    if not c:
        c = Chat(id=tg_chat.id)
        db.add(c)
    c.title = tg_chat.title or tg_chat.username or str(tg_chat.id)
    c.chat_type = tg_chat.type
    c.last_activity = now_utc()
    return c


def ensure_chat_member(db, chat_id: int, user_id: int) -> ChatMember:
    cm = db.query(ChatMember).filter_by(chat_id=chat_id, user_id=user_id).first()
    if not cm:
        cm = ChatMember(chat_id=chat_id, user_id=user_id)
        db.add(cm)
    cm.left_at = None
    return cm


def ensure_chat_topic(db, chat_id: int, thread_id: int, title: Optional[str] = None) -> ChatTopic:
    tp = db.query(ChatTopic).filter_by(chat_id=chat_id, thread_id=thread_id).first()
    if not tp:
        tp = ChatTopic(chat_id=chat_id, thread_id=thread_id)
        db.add(tp)
    if title:
        tp.title = title
    tp.last_activity = now_utc()
    return tp


# ---------------------------------------------------------------------------
# Проверки
# ---------------------------------------------------------------------------

def is_user_blacklisted(db, user_id: int) -> bool:
    u = db.get(User, user_id)
    return bool(u and u.is_blacklisted)


def has_internal_role(db, chat_id: int, user_id: int) -> bool:
    return (
        db.query(RoleAssignment)
        .filter_by(chat_id=chat_id, user_id=user_id)
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Троттлинг активности
# ---------------------------------------------------------------------------

def _extract_topic_title(message: types.Message) -> Optional[str]:
    for attr in ("forum_topic_created", "forum_topic_edited"):
        v = getattr(message, attr, None)
        if not v:
            continue
        try:
            if isinstance(v, dict):
                name = v.get("name") or v.get("title")
                if name:
                    return str(name)
            else:
                name = getattr(v, "name", None) or getattr(v, "title", None)
                if name:
                    return str(name)
        except Exception:
            continue
    return None


def touch_topic_activity(message: types.Message) -> None:
    try:
        if not message or not message.chat:
            return
        if message.chat.type not in ("group", "supergroup"):
            return

        thread_id = getattr(message, "message_thread_id", None)
        if not thread_id:
            return
        try:
            thread_id_int = int(thread_id)
        except Exception:
            return

        key = (message.chat.id, thread_id_int)
        now_ts = time.time()
        title = _extract_topic_title(message)

        force = key not in SEEN_TOPICS
        last_ts = TOUCH_TOPIC_TS.get(key, 0)
        if not force and not title and (now_ts - last_ts < TOUCH_TOPIC_INTERVAL):
            return

        with TOUCH_LOCK:
            db = SessionLocal()
            try:
                ensure_chat(db, message.chat)
                ensure_chat_topic(db, message.chat.id, thread_id_int, title=title)
                db.commit()
                SEEN_TOPICS.add(key)
                TOUCH_TOPIC_TS[key] = now_ts
            except IntegrityError:
                db.rollback()
                try:
                    ensure_chat(db, message.chat)
                    ensure_chat_topic(db, message.chat.id, thread_id_int, title=title)
                    db.commit()
                    SEEN_TOPICS.add(key)
                    TOUCH_TOPIC_TS[key] = now_ts
                except Exception:
                    db.rollback()
            except Exception:
                db.rollback()
            finally:
                db.close()
    except Exception:
        return


def touch_activity(tg_chat: types.Chat, tg_user: Optional[types.User] = None) -> None:
    """Обновляет/создаёт записи чата и пользователя в БД с троттлингом."""
    if not tg_chat or tg_chat.type not in ("group", "supergroup"):
        return

    chat_id = tg_chat.id
    user_id = tg_user.id if tg_user else None

    now_ts = time.time()

    force_chat = chat_id not in SEEN_CHATS
    force_member = False
    key: Optional[Tuple[int, int]] = None
    if user_id is not None:
        key = (chat_id, user_id)
        force_member = key not in SEEN_MEMBERS

    if not force_chat:
        last_chat = TOUCH_CHAT_TS.get(chat_id, 0)
        if now_ts - last_chat < TOUCH_CHAT_INTERVAL:
            if user_id is None:
                return
            if not force_member:
                last_member = TOUCH_MEMBER_TS.get(key, 0) if key else 0
                if now_ts - last_member < TOUCH_MEMBER_INTERVAL:
                    return

    with TOUCH_LOCK:
        db = SessionLocal()
        try:
            ensure_chat(db, tg_chat)

            if tg_user:
                u = ensure_user(db, tg_user)
                try:
                    u.message_count = int(u.message_count or 0) + 1
                except Exception:
                    u.message_count = 1
                ensure_chat_member(db, chat_id, user_id)

            db.commit()

            SEEN_CHATS.add(chat_id)
            TOUCH_CHAT_TS[chat_id] = now_ts
            if key:
                SEEN_MEMBERS.add(key)
                TOUCH_MEMBER_TS[key] = now_ts

        except IntegrityError:
            db.rollback()
            try:
                ensure_chat(db, tg_chat)
                if tg_user:
                    u = ensure_user(db, tg_user)
                    try:
                        u.message_count = int(u.message_count or 0) + 1
                    except Exception:
                        u.message_count = 1
                    ensure_chat_member(db, chat_id, user_id)
                db.commit()
                SEEN_CHATS.add(chat_id)
                TOUCH_CHAT_TS[chat_id] = now_ts
                if key:
                    SEEN_MEMBERS.add(key)
                    TOUCH_MEMBER_TS[key] = now_ts
            except Exception:
                db.rollback()
                logger.debug("touch_activity: повтор после IntegrityError не удался", exc_info=True)
        except Exception as e:
            db.rollback()
            logger.warning("touch_activity error (%s)", type(e).__name__)
        finally:
            db.close()
