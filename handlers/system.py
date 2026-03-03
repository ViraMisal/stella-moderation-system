"""Системные хендлеры: активность, /start /help /scan /where."""

from __future__ import annotations

from telebot import types
from telebot.handler_backends import ContinueHandling

from config import SUPERADMIN_IDS
from handlers.core import _set_topic_context, _tg_retry_call, bot
from handlers.db import (
    ensure_chat,
    ensure_chat_member,
    ensure_user,
    touch_activity,
    touch_topic_activity,
)
from handlers.guards import require_moderator
from handlers.helpers import safe_delete_message, send_temp_message
from models import ChatMember, SessionLocal
from src_utils.logsetup import setup_logging

logger = setup_logging("bot.system")


# ---------------------------------------------------------------------------
# Отслеживание активности
# ---------------------------------------------------------------------------

@bot.my_chat_member_handler()
def on_my_chat_member(update: types.ChatMemberUpdated):
    """Бот добавлен в группу / изменён его статус — регистрируем чат."""
    try:
        if not update or not update.chat:
            return
        if update.chat.type not in ("group", "supergroup"):
            return
        status = getattr(update.new_chat_member, "status", None)
        if status in ("member", "administrator", "creator", "restricted"):
            touch_activity(update.chat, None)
    except Exception as e:
        logger.warning("my_chat_member handler error: %s", e)


@bot.message_handler(
    func=lambda m: bool(m and m.chat and m.chat.type in ("group", "supergroup")),
    content_types=[
        "text", "photo", "video", "document", "sticker", "animation",
        "voice", "audio", "video_note", "location", "contact", "venue",
        "poll", "dice", "new_chat_members", "left_chat_member",
        "new_chat_title", "new_chat_photo", "delete_chat_photo",
        "pinned_message", "forum_topic_created", "forum_topic_edited",
    ],
)
def track_activity_handler(message: types.Message):
    """Обновляет БД при каждом сообщении в группе. Не пишет в чат."""
    _set_topic_context(message)
    try:
        if message.from_user:
            touch_activity(message.chat, message.from_user)
        else:
            touch_activity(message.chat, None)
        touch_topic_activity(message)
    except Exception:
        pass
    return ContinueHandling()


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message):
    if message.chat.type != "private":
        safe_delete_message(message.chat.id, message.message_id)
        return

    bot.send_message(
        message.chat.id,
        (
            "Привет! Я <b>Stella</b> — бот модерации и помощник чата.\n\n"
            "<b>Список команд</b> (в группах/супергруппах, обычно используйте <b>ответом на сообщение</b>):\n"
            "• <code>/mute 30m причина</code> — мут\n"
            "• <code>/mutemedia 1h причина</code> — медиамут\n"
            "• <code>/ban причина</code> — бан\n"
            "• <code>/kick причина</code> — кик\n"
            "• <code>/unmute</code> — снять мут\n"
            "• <code>/unban</code> — разбан\n"
            "• <code>/probation 30d причина</code> или <code>/isp</code> — испытательный срок (новые тайм‑наказания ×2)\n"
            "• <code>/unprobation</code> или <code>/noisp</code> — снять испытательный срок\n"
            "• <code>/scan</code> — принудительная синхронизация админов/приписок для панели\n\n"
            "<b>Апелляция</b> (только в личке):\n"
            "• <code>/appeal ваш текст</code> — отправить апелляцию если вы НЕ согласны с наказанием\n\n"
            "ℹ️ В случае проблем с ботом — писать @Redikin"
        ),
    )


@bot.message_handler(commands=["scan"])
def cmd_scan(message: types.Message):
    """Сканирует администраторов чата и обновляет БД."""
    if message.chat.type not in ("group", "supergroup"):
        safe_delete_message(message.chat.id, message.message_id)
        return

    if not require_moderator(message):
        return

    chat_id = message.chat.id
    try:
        admins = _tg_retry_call(bot.get_chat_administrators, chat_id, retries=3, base_delay=1.0)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Не получилось получить админов: {e}")
        return

    db = SessionLocal()
    try:
        ensure_chat(db, message.chat)
        db.query(ChatMember).filter_by(chat_id=chat_id).update({ChatMember.is_admin: False})
        db.commit()

        for a in admins:
            ensure_user(db, a.user)
            cm = ensure_chat_member(db, chat_id, a.user.id)
            cm.is_admin = True
            cm.status = a.status
            db.add(cm)
        db.commit()

        bot.send_message(chat_id, f"✅ Админы обновлены: {len(admins)}")
    except Exception as e:
        db.rollback()
        bot.send_message(chat_id, f"❌ Ошибка БД: {e}")
    finally:
        db.close()


@bot.message_handler(commands=["where", "topicid", "threadid"])
def cmd_where(message: types.Message):
    """Показывает chat_id и thread_id. Только суперадмины."""
    if message.chat.type not in ("group", "supergroup"):
        return

    if not message.from_user or message.from_user.id not in SUPERADMIN_IDS:
        return

    _set_topic_context(message)

    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)

    lines = [f"chat_id: <code>{chat_id}</code>"]
    if thread_id:
        lines.append(f"thread_id: <code>{thread_id}</code>")
    else:
        lines.append("thread_id: <code>—</code>")
    lines.append(f"message_id: <code>{message.message_id}</code>")

    send_temp_message(chat_id, "\n".join(lines), ttl_seconds=20)
