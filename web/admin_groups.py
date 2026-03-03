"""
Модуль для работы с администраторами групп
"""
import telebot

from core.config import ALLOWED_TG_IDS, BOT_TOKEN
from core.models import Chat, ChatMember, SessionLocal, User
from src_utils.logsetup import setup_logging

logger = setup_logging("admin_groups")


def get_user_admin_chats(user_id: int) -> list:
    """Получает список чатов где пользователь является администратором"""
    db = SessionLocal()
    try:
        admin_chats = []

        # Сначала проверяем в ChatMember (быстрее и не требует API запросов)
        chat_members = db.query(ChatMember).filter(
            ChatMember.user_id == user_id,
            ChatMember.is_admin == True,
            ChatMember.left_at == None
        ).all()

        for cm in chat_members:
            admin_chats.append(cm.chat_id)

        # Если через ChatMember ничего не найдено и есть BOT_TOKEN - проверяем через API
        if not admin_chats and BOT_TOKEN:
            bot = telebot.TeleBot(BOT_TOKEN)

            # Получаем все чаты из БД
            all_chats = db.query(Chat).filter(Chat.chat_type.in_(['group', 'supergroup'])).all()

            for chat in all_chats:
                try:
                    # Проверяем является ли пользователь админом
                    member = bot.get_chat_member(chat.id, user_id)
                    if member.status in ('administrator', 'creator'):
                        admin_chats.append(chat.id)
                except Exception as e:
                    logger.debug(
                        f"Не удалось проверить статус админа для пользователя {user_id} "
                        f"в чате {chat.id}: {e}"
                    )
                    continue

        return admin_chats

    except Exception as e:
        logger.error(f"Ошибка при получении админских чатов для пользователя {user_id}: {e}")
        return []
    finally:
        db.close()


def update_user_admin_status(user_id: int) -> tuple[str, list]:
    """
    Обновляет статус администратора пользователя
    Возвращает (роль, список_чатов_где_админ)
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return 'user', []


        # Если пользователь указан в SUPERADMIN_IDS (из .env),
        # то он должен иметь полный доступ к панели независимо от того,
        # является ли он админом каких-то чатов в Telegram.
        if ALLOWED_TG_IDS and user_id in ALLOWED_TG_IDS:
            user.role = 'superadmin'
            user.is_web_admin = True
            db.commit()
            return 'superadmin', []

        # Получаем список чатов где пользователь админ
        admin_chats = get_user_admin_chats(user_id)

        if not admin_chats:
            # Не админ ни в одной группе
            user.role = 'user'
            user.is_web_admin = False
        else:
            # Админ хотя бы в одной группе
            user.role = 'group_admin'
            user.is_web_admin = True

        db.commit()
        return user.role, admin_chats

    except Exception as e:
        logger.error(f"Error updating admin status for user {user_id}: {e}")
        return 'user', []
    finally:
        db.close()


def check_user_can_access_chat(user_id: int, chat_id: int) -> bool:
    """Проверяет может ли пользователь управлять этим чатом"""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return False

        # Супер-админ может всё
        if user.role == 'superadmin':
            return True

        # Обычный пользователь не может
        if user.role == 'user':
            return False

        # Админ группы - проверяем является ли он админом этого чата
        admin_chats = get_user_admin_chats(user_id)
        return chat_id in admin_chats

    finally:
        db.close()


def is_superadmin(user_id: int) -> bool:
    """Проверяет является ли пользователь супер-админом"""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        return user and user.role == 'superadmin'
    finally:
        db.close()


def set_superadmin(user_id: int):
    """Делает пользователя супер-админом"""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            user = User(id=user_id, role='superadmin', is_web_admin=True)
            db.add(user)
        else:
            user.role = 'superadmin'
            user.is_web_admin = True
        db.commit()
    finally:
        db.close()
