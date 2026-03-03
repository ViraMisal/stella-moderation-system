"""Модели БД и авто-миграция для SQLite."""

from __future__ import annotations

import datetime
import json
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from core.config import DATABASE_URL

Base = declarative_base()

_connect_args: dict[str, Any] = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    role = Column(String(50), default="user")
    is_web_admin = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_activity = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)

    # Глобальный чёрный список
    is_blacklisted = Column(Boolean, default=False)
    blacklist_reason = Column(Text, nullable=True)
    blacklisted_at = Column(DateTime, nullable=True)
    blacklisted_by = Column(String(255), nullable=True)

    # Метаданные Telegram
    is_bot = Column(Boolean, default=False)
    language_code = Column(String(32), nullable=True)

    punishments = relationship("Punishment", back_populates="user")

    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        name = " ".join([p for p in [self.first_name, self.last_name] if p])
        return name or str(self.id)


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=True)
    chat_type = Column(String(50), nullable=True)  # private / group / supergroup / channel

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_activity = Column(DateTime, nullable=True)

    members = relationship("ChatMember", back_populates="chat")
    punishments = relationship("Punishment", back_populates="chat")

    def is_group(self) -> bool:
        return (self.chat_type or "") in ("group", "supergroup")


    topics = relationship("ChatTopic", back_populates="chat", cascade="all, delete-orphan")


class ChatTopic(Base):
    __tablename__ = "chat_topics"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), index=True, nullable=False)
    thread_id = Column(Integer, index=True, nullable=False)
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_activity = Column(DateTime, nullable=True)

    chat = relationship("Chat", back_populates="topics")

    __table_args__ = (
        UniqueConstraint("chat_id", "thread_id", name="uq_chat_topics_chat_thread"),
    )

class ChatMember(Base):
    __tablename__ = "chat_members"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)

    status = Column(String(50), nullable=True)  # member/administrator/creator/left/kicked
    is_admin = Column(Boolean, default=False)

    joined_at = Column(DateTime, default=datetime.datetime.utcnow)
    left_at = Column(DateTime, nullable=True)

    # Используется админ-панелью
    admin_prefix = Column(String(64), nullable=True)
    admin_rights = Column(Text, nullable=True)  # JSON

    user = relationship("User")
    chat = relationship("Chat", back_populates="members")


class Punishment(Base):
    __tablename__ = "punishments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id"), index=True, nullable=False)

    type = Column(String(50), nullable=False)  # mute/mutemedia/ban/kick
    reason = Column(Text, nullable=True)

    # Кто выдал
    admin_id = Column(Integer, nullable=True)
    admin_name = Column(String(255), nullable=True)

    date = Column(DateTime, default=datetime.datetime.utcnow)
    until_date = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)

    # Снятие
    removed_at = Column(DateTime, nullable=True)
    removed_by_id = Column(Integer, nullable=True)
    removed_by_name = Column(String(255), nullable=True)

    # Поддержка "испытательного срока": сколько попросили и сколько применили (в минутах)
    requested_duration_minutes = Column(Integer, nullable=True)
    applied_duration_minutes = Column(Integer, nullable=True)

    user = relationship("User", back_populates="punishments")
    chat = relationship("Chat", back_populates="punishments")

    def type_display(self) -> str:
        """Человекочитаемый тип наказания (шаблоны вызывают именно метод)."""
        mapping = {
            "mute": "Мут",
            "media_mute": "Медиамут",
            "mutemedia": "Медиамут",
            "ban": "Бан",
            "kick": "Кик",
            "warn": "Предупреждение",
            "unmute": "Снятие мута",
            "unban": "Разбан",
        }
        return mapping.get((self.type or "").lower(), self.type or "-")


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, nullable=True)
    author_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Appeal(Base):
    __tablename__ = "appeals"

    id = Column(Integer, primary_key=True, index=True)
    # Кто подал апелляцию (Telegram user_id)
    user_id = Column(Integer, index=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)

    # Текст апелляции
    text = Column(Text, nullable=False)

    # Когда создана
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    # Куда переслали (чат апелляций) и какой message_id там получился
    appeals_chat_id = Column(Integer, nullable=True)
    forwarded_message_id = Column(Integer, nullable=True)

    # Снимок активных наказаний на момент апелляции (как текст)
    punishments_snapshot = Column(Text, nullable=True)

    # Ответ администратора (если был)
    answered_at = Column(DateTime, nullable=True)
    answered_by_id = Column(Integer, nullable=True)
    answered_by_name = Column(String(255), nullable=True)
    answer_text = Column(Text, nullable=True)


class AdminLog(Base):
    __tablename__ = "admin_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Кто сделал действие
    admin_id = Column(Integer, nullable=True, index=True)
    admin_name = Column(String(255), nullable=True)

    # Что было сделано
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)

    # Технические детали
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)

    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_by = Column(String(255), nullable=True)

    @staticmethod
    def get(db, key: str, default: Optional[str] = None) -> Optional[str]:
        row = db.query(Settings).filter(Settings.key == key).first()
        if row is None:
            return default
        return row.value if row.value is not None else default

    @staticmethod
    def set(
        db,
        key: str,
        value: Optional[str],
        description: Optional[str] = None,
        updated_by: Optional[str] = None,
    ):
        row = db.query(Settings).filter(Settings.key == key).first()
        if row is None:
            row = Settings(key=key)
            db.add(row)
        row.value = value
        if description is not None:
            row.description = description
        row.updated_at = datetime.datetime.utcnow()
        row.updated_by = updated_by
        db.commit()


class Probation(Base):
    """Испытательный срок для пользователя в конкретном чате.

    Пока испытательный срок активен — новые тайм-наказания умножаются (обычно ×2).
    """

    __tablename__ = "probations"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)

    until_date = Column(DateTime, nullable=False)
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String(255), nullable=True)

    chat = relationship("Chat")
    user = relationship("User")


class RoleAssignment(Base):
    """Внутренние роли (owner/admin/mod) на чат.

    Используется для иерархии, когда Telegram-админка не отражает всё, что нужно.
    """

    __tablename__ = "role_assignments"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)

    role = Column(String(32), nullable=False)  # owner/admin/mod

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String(255), nullable=True)

    chat = relationship("Chat")
    user = relationship("User")


class AIConversation(Base):
    """Храним контекст диалога ИИ (по чату + пользователю)."""

    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, index=True, nullable=False)
    user_id = Column(Integer, index=True, nullable=False)

    # JSON-список сообщений вида {role, content}
    messages_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    def get_messages(self) -> list[dict[str, Any]]:
        if not self.messages_json:
            return []
        try:
            v = json.loads(self.messages_json)
            return v if isinstance(v, list) else []
        except Exception:
            return []

    def set_messages(self, messages: list[dict[str, Any]]):
        self.messages_json = json.dumps(messages, ensure_ascii=False)
        self.updated_at = datetime.datetime.utcnow()

    def get_context(self) -> list[dict[str, Any]]:
        """Алиас под старое имя (используется ботом)."""
        return self.get_messages()

    def set_context(self, messages: list[dict[str, Any]]):
        """Алиас под старое имя (используется ботом)."""
        self.set_messages(messages)


def _sqlite_add_column_if_missing(table: str, column_name: str, ddl: str):
    """Пробуем добавить колонку через ALTER TABLE ADD COLUMN для SQLite.

    В SQLite нет полноценного ALTER TABLE для многих операций,
    но ADD COLUMN работает, и нам этого достаточно.
    """

    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
        if column_name in cols:
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def ensure_schema():
    """Создать таблицы и докинуть недостающие колонки для старых SQLite БД."""

    Base.metadata.create_all(bind=engine)

    if not DATABASE_URL.startswith("sqlite"):
        return

    # Улучшаем параллельную работу бота и веб-панели с SQLite
    # (меньше "database is locked", быстрее чтение).
    try:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.execute(text("PRAGMA busy_timeout=5000"))
    except Exception:
        # На некоторых окружениях PRAGMA может быть запрещён — не критично
        pass

    # ChatMember (связь чат-пользователь)
    _sqlite_add_column_if_missing("chat_members", "admin_prefix", "admin_prefix VARCHAR(64)")
    _sqlite_add_column_if_missing("chat_members", "admin_rights", "admin_rights TEXT")

    # Punishment (наказания)
    _sqlite_add_column_if_missing(
        "punishments", "requested_duration_minutes", "requested_duration_minutes INTEGER"
    )
    _sqlite_add_column_if_missing(
        "punishments", "applied_duration_minutes", "applied_duration_minutes INTEGER"
    )

    # AdminLog (журнал действий)
    _sqlite_add_column_if_missing("admin_logs", "admin_id", "admin_id INTEGER")
    _sqlite_add_column_if_missing("admin_logs", "admin_name", "admin_name VARCHAR(255)")
    _sqlite_add_column_if_missing("admin_logs", "ip_address", "ip_address VARCHAR(64)")
    _sqlite_add_column_if_missing("admin_logs", "user_agent", "user_agent TEXT")


# Запускаем миграцию при импорте модуля (простая и безопасная).
ensure_schema()
