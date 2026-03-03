# admin_tools.py — расширенная панель управления администраторами (фикс прав, @username, совместимость)

import json
from functools import wraps

import telebot
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.config import BOT_TOKEN
from core.models import Chat, ChatMember, SessionLocal, User
from core.settings import is_kill_switch_enabled
from src_utils.logsetup import setup_logging

admin_tools_bp = Blueprint('admin_tools', __name__, url_prefix='')
logger = setup_logging("admin_tools")

# ---- Декораторы и проверки ----
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper

def is_superadmin():
    return session.get('role') == 'superadmin'

# ---- Утилиты ----
RIGHTS_CATALOG = [
    ('can_manage_chat',        'Управление чатом'),
    ('can_change_info',        'Изменение инфо'),
    ('can_delete_messages',    'Удаление сообщений'),
    ('can_invite_users',       'Приглашать пользователей'),
    ('can_restrict_members',   'Ограничивать участников'),
    ('can_pin_messages',       'Закреплять сообщения'),
    ('can_promote_members',    'Назначать админов'),
    ('can_manage_video_chats', 'Видеочаты'),
    ('can_manage_topics',      'Управлять темами'),
    ('is_anonymous',           'Анонимный админ'),
    # Канальные права
    ('can_post_messages',      'Постить сообщения (каналы)'),
    ('can_edit_messages',      'Редактировать посты (каналы)'),
]

_ALLOWED_PROMOTE_KWARGS = {k for k, _ in RIGHTS_CATALOG}

def parse_rights_from_form(form):
    rights = {}
    for key, _ in RIGHTS_CATALOG:
        rights[key] = (form.get(f'rights_{key}') == 'on')
    return rights

def get_tbot():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не настроен")
    return telebot.TeleBot(BOT_TOKEN)

def ensure_schema():
    """Добавляем при необходимости колонки admin_prefix и admin_rights в chat_members (SQLite)."""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        cols = [row[1] for row in db.execute(text("PRAGMA table_info(chat_members)")).fetchall()]
        alter = []
        if 'admin_prefix' not in cols:
            alter.append("ALTER TABLE chat_members ADD COLUMN admin_prefix VARCHAR(64)")
        if 'admin_rights' not in cols:
            alter.append("ALTER TABLE chat_members ADD COLUMN admin_rights TEXT")
        for sql in alter:
            db.execute(text(sql))
        if alter:
            db.commit()
    except Exception as e:
        logger.warning(f"ensure_schema error: {e}")
    finally:
        db.close()

def _rights_from_tg_admin_obj(tg_admin_obj):
    """Безопасно собираем права из объекта ChatMemberAdministrator."""
    out = {}
    ad = getattr(tg_admin_obj, '__dict__', {})
    for key, _ in RIGHTS_CATALOG:
        out[key] = bool(ad.get(key, False))
    return out

def _filter_rights_for_chat_type(chat_type: str, rights: dict):
    """Убираем флаги, которые не поддерживаются типом чата, чтобы избежать RIGHT_FORBIDDEN."""
    rights = dict(rights)
    if chat_type in ('group', 'supergroup'):
        # канальные права в группах запрещены
        for k in ('can_post_messages', 'can_edit_messages'):
            rights.pop(k, None)
    elif chat_type == 'channel':
        allowed_for_channels = {'is_anonymous', 'can_manage_chat', 'can_post_messages', 'can_edit_messages'}
        rights = {k: bool(v) for k, v in rights.items() if k in allowed_for_channels}
    return rights

def _filter_rights_by_bot_capabilities(bot_admin_obj, rights: dict):
    """Оставляем True только те права, которые бот реально может назначать в этом чате."""
    safe = {}
    for k, v in rights.items():
        if not v:
            safe[k] = False
            continue
        # если у бота нет соответствующего флага — не пытаемся его назначить
        safe[k] = bool(getattr(bot_admin_obj, k, False))
    return safe

def _resolve_user_id(db, chat_id: int, who: str | None, tbot=None):
    """who может быть числом или @username. Сначала БД, затем через Telegram API."""
    if not who:
        return None
    s = who.strip()
    if s.isdigit():
        return int(s)
    uname = s.lstrip('@').strip().lower()

    # поиск по БД
    u = db.query(User).filter(func.lower(User.username) == uname).first()
    if u:
        return u.id

    cm = (
        db.query(ChatMember)
          .join(User, ChatMember.user_id == User.id)
          .filter(
              ChatMember.chat_id == chat_id,
              func.lower(User.username) == uname
          )
          .first()
    )
    if cm:
        return cm.user_id

    # пробуем через Telegram API (если пользователь публичный/писал боту)
    if tbot and s.startswith('@'):
        try:
            ch = tbot.get_chat(s)  # может вернуть user/chat
            if hasattr(ch, 'id'):
                return int(ch.id)
        except Exception:
            pass
    return None

# ---- Страницы ----
@admin_tools_bp.route('/admins')
@login_required
def admins():
    if not is_superadmin():
        flash("Доступ только для супер-админа.", "error")
        return redirect(url_for('dashboard.dashboard'))

    ensure_schema()
    chat_id = request.args.get('chat_id', type=int)

    db = SessionLocal()
    try:
        chats = db.query(Chat).order_by(Chat.title).all()
        group_chats = [c for c in chats if c.chat_type in ('group', 'supergroup', 'channel')]

        if not group_chats:
            flash("Нет чатов для управления.", "info")
            return render_template(
                'admins.html',
                chats=[],
                selected_chat=None,
                admins=[],
                admins_by_chat={},  # совместимость со старыми шаблонами
                rights_catalog=RIGHTS_CATALOG
            )

        selected = db.get(Chat, chat_id) if chat_id else group_chats[0]

        admins_list = (
            db.query(ChatMember)
              .options(joinedload(ChatMember.user))
              .filter(
                  ChatMember.chat_id == selected.id,
                  ChatMember.is_admin == True,
                  ChatMember.left_at == None
              )
              .order_by(ChatMember.joined_at.desc())
              .all()
        )

        # Мягкая синхронизация с Telegram
        try:
            tbot = get_tbot()
            tg_admins = tbot.get_chat_administrators(selected.id)
            tg_rights_map = {a.user.id: a for a in tg_admins}
            changed = False
            for m in admins_list:
                a = tg_rights_map.get(m.user_id)
                if a:
                    m.admin_rights = json.dumps(_rights_from_tg_admin_obj(a), ensure_ascii=False)
                    db.add(m)
                    changed = True
            if changed:
                db.commit()
        except Exception as e:
            logger.warning(f"Не удалось обновить права из Telegram: {e}")

        admins_by_chat = {selected.id: {'chat': selected, 'admins': admins_list}}
        return render_template(
            'admins.html',
            chats=group_chats,
            selected_chat=selected,
            admins=admins_list,
            admins_by_chat=admins_by_chat,   # совместимость
            rights_catalog=RIGHTS_CATALOG
        )
    finally:
        db.close()

@admin_tools_bp.route('/admins/promote', methods=['POST'])
@login_required
def admins_promote():
    if not is_superadmin():
        flash("Доступ только для супер-админа.", "error")
        return redirect(url_for('dashboard.dashboard'))

    ensure_schema()
    if is_kill_switch_enabled():
        flash("⛔️ Киллсвитч активен: управление админами временно отключено.", "error")
        return redirect(url_for('admin_tools.admins', chat_id=request.form.get('chat_id') or ''))

    chat_id = request.form.get('chat_id', type=int)
    who     = (request.form.get('who') or '').strip()
    user_id = request.form.get('user_id', type=int)
    prefix  = (request.form.get('prefix') or '').strip()
    rights  = parse_rights_from_form(request.form)

    db = SessionLocal()
    try:
        if not chat_id:
            flash("Не указан чат.", "error")
            return redirect(url_for('admin_tools.admins'))

        chat = db.get(Chat, chat_id)
        if not chat:
            flash("Чат не найден.", "error")
            return redirect(url_for('admin_tools.admins'))

        tbot = get_tbot()

        if not user_id:
            user_id = _resolve_user_id(db, chat_id, who, tbot)
        if not user_id:
            flash("Не найден пользователь (укажите числовой ID или @username, доступный боту/в БД).", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id))

        try:
            me = tbot.get_me()
            bot_member = tbot.get_chat_member(chat_id, me.id)
            if getattr(bot_member, 'status', '') != 'administrator' or not getattr(bot_member, 'can_promote_members', False):
                flash("У бота нет права ‘Назначать админов’ в этом чате.", "error")
                return redirect(url_for('admin_tools.admins', chat_id=chat_id))

            # цель должна быть участником
            try:
                target = tbot.get_chat_member(chat_id, user_id)
                if getattr(target, 'status', 'left') in ('left', 'kicked'):
                    flash("Пользователь не состоит в чате. Сначала добавьте его в чат.", "error")
                    return redirect(url_for('admin_tools.admins', chat_id=chat_id))
            except Exception:
                pass

            rights = _filter_rights_for_chat_type(chat.chat_type, rights)
            rights = _filter_rights_by_bot_capabilities(bot_member, rights)
            rights = {k: bool(v) for k, v in rights.items() if k in _ALLOWED_PROMOTE_KWARGS}

            tbot.promote_chat_member(chat_id, user_id, **rights)
            if prefix:
                try:
                    tbot.set_chat_administrator_custom_title(chat_id, user_id, prefix[:16])
                except Exception as ee:
                    logger.warning(f"Не удалось установить приписку: {ee}")
        except Exception as e:
            msg = str(e)
            if 'RIGHT_FORBIDDEN' in msg:
                flash("Ошибка Telegram API: нет прав. Проверьте права бота и снимаемые/ставимые флаги.", "error")
            else:
                flash(f"Ошибка Telegram API при назначении: {e}", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id))

        # Обновляем БД
        user = db.get(User, user_id) or User(id=user_id)
        db.add(user)
        cm = db.query(ChatMember).filter_by(chat_id=chat_id, user_id=user_id).first()
        if not cm:
            cm = ChatMember(chat_id=chat_id, user_id=user_id)
        cm.is_admin = True
        cm.status = 'administrator'
        cm.admin_prefix = prefix[:64] if prefix else None
        cm.admin_rights = json.dumps(rights, ensure_ascii=False)
        db.add(cm)
        db.commit()

        flash("Администратор назначен/обновлён", "success")
        return redirect(url_for('admin_tools.admins', chat_id=chat_id))
    finally:
        db.close()

@admin_tools_bp.route('/admins/update', methods=['POST'])
@login_required
def admins_update():
    if not is_superadmin():
        flash("Доступ только для супер-админа.", "error")
        return redirect(url_for('dashboard.dashboard'))

    ensure_schema()
    if is_kill_switch_enabled():
        flash("⛔️ Киллсвитч активен: управление админами временно отключено.", "error")
        return redirect(url_for('admin_tools.admins', chat_id=request.form.get('chat_id') or ''))

    chat_id = request.form.get('chat_id', type=int)
    user_id = request.form.get('user_id', type=int)
    prefix  = (request.form.get('prefix') or '').strip()
    rights  = parse_rights_from_form(request.form)

    db = SessionLocal()
    try:
        if not chat_id or not user_id:
            flash("Некорректные данные", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id or ''))

        chat = db.get(Chat, chat_id)
        if not chat:
            flash("Чат не найден", "error")
            return redirect(url_for('admin_tools.admins'))

        try:
            tbot = get_tbot()
            me = tbot.get_me()
            bot_member = tbot.get_chat_member(chat_id, me.id)
            if getattr(bot_member, 'status', '') != 'administrator' or not getattr(bot_member, 'can_promote_members', False):
                flash("У бота нет права ‘Назначать админов’.", "error")
                return redirect(url_for('admin_tools.admins', chat_id=chat_id))

            rights = _filter_rights_for_chat_type(chat.chat_type, rights)
            rights = _filter_rights_by_bot_capabilities(bot_member, rights)
            rights = {k: bool(v) for k, v in rights.items() if k in _ALLOWED_PROMOTE_KWARGS}

            tbot.promote_chat_member(chat_id, user_id, **rights)
            if prefix:
                try:
                    tbot.set_chat_administrator_custom_title(chat_id, user_id, prefix[:16])
                except Exception as ee:
                    logger.warning(f"Не удалось установить приписку: {ee}")
        except Exception as e:
            msg = str(e)
            if 'RIGHT_FORBIDDEN' in msg:
                flash("Ошибка Telegram API: нет прав для изменения прав администратора.", "error")
            else:
                flash(f"Ошибка Telegram API: {e}", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id))

        cm = db.query(ChatMember).filter_by(chat_id=chat_id, user_id=user_id).first()
        if not cm:
            cm = ChatMember(chat_id=chat_id, user_id=user_id)
        cm.is_admin = True
        cm.status = 'administrator'
        cm.admin_prefix = prefix[:64] if prefix else None
        cm.admin_rights = json.dumps(rights, ensure_ascii=False)
        db.add(cm)
        db.commit()

        flash("Права администратора обновлены", "success")
        return redirect(url_for('admin_tools.admins', chat_id=chat_id))
    finally:
        db.close()

@admin_tools_bp.route('/admins/demote', methods=['POST'])
@login_required
def admins_demote():
    if not is_superadmin():
        flash("Доступ только для супер-админа.", "error")
        return redirect(url_for('dashboard.dashboard'))

    ensure_schema()
    if is_kill_switch_enabled():
        flash("⛔️ Киллсвитч активен: управление админами временно отключено.", "error")
        return redirect(url_for('admin_tools.admins', chat_id=request.form.get('chat_id') or ''))

    chat_id = request.form.get('chat_id', type=int)
    user_id = request.form.get('user_id', type=int)

    db = SessionLocal()
    try:
        if not chat_id or not user_id:
            flash("Некорректные данные", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id or ''))

        try:
            tbot = get_tbot()
            zeros = {k: False for k, _ in RIGHTS_CATALOG}
            tbot.promote_chat_member(chat_id, user_id, **zeros)
        except Exception as e:
            flash(f"Ошибка Telegram API при снятии прав: {e}", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id))

        cm = db.query(ChatMember).filter_by(chat_id=chat_id, user_id=user_id).first()
        if cm:
            cm.is_admin = False
            cm.status = 'member'
            cm.admin_prefix = None
            cm.admin_rights = None
            db.add(cm)
            db.commit()

        flash("Права администратора сняты", "success")
        return redirect(url_for('admin_tools.admins', chat_id=chat_id))
    finally:
        db.close()

@admin_tools_bp.route('/admins/ban', methods=['POST'])
@login_required
def admins_ban():
    if not is_superadmin():
        flash("Доступ только для супер-админа.", "error")
        return redirect(url_for('dashboard.dashboard'))

    ensure_schema()
    if is_kill_switch_enabled():
        flash("⛔️ Киллсвитч активен: управление админами временно отключено.", "error")
        return redirect(url_for('admin_tools.admins', chat_id=request.form.get('chat_id') or ''))

    chat_id = request.form.get('chat_id', type=int)
    user_id = request.form.get('user_id', type=int)

    db = SessionLocal()
    try:
        if not chat_id or not user_id:
            flash("Некорректные данные", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id or ''))

        try:
            tbot = get_tbot()
            zeros = {k: False for k, _ in RIGHTS_CATALOG}
            try:
                tbot.promote_chat_member(chat_id, user_id, **zeros)
            except Exception:
                pass
            tbot.ban_chat_member(chat_id, user_id)
        except Exception as e:
            flash(f"Ошибка Telegram API при бане: {e}", "error")
            return redirect(url_for('admin_tools.admins', chat_id=chat_id))

        cm = db.query(ChatMember).filter_by(chat_id=chat_id, user_id=user_id).first()
        if cm:
            cm.is_admin = False
            cm.status = 'kicked'
            cm.admin_prefix = None
            cm.admin_rights = None
            db.add(cm)
            db.commit()

        flash("Пользователь забанен в чате", "success")
        return redirect(url_for('admin_tools.admins', chat_id=chat_id))
    finally:
        db.close()

# ---- Совместимость со старыми шаблонами ----
@admin_tools_bp.route('/admins/revoke', methods=['POST'])
@login_required
def admins_revoke():
    """Алиас на admins_demote, чтобы старый шаблон с url_for('admin_tools.admins_revoke') не падал."""
    return admins_demote()

