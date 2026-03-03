"""Маршруты пользователей: /users, /user/<id>, наказания, испытательный срок, ЧС."""
from __future__ import annotations

import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import cast, desc, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.types import String

from core.config import BOT_TOKEN
from core.models import Chat, ChatMember, Note, Probation, Punishment, SessionLocal, User
from core.settings import is_kill_switch_enabled
from web.context import get_accessible_chats, get_current_admin_info, is_current_superadmin
from web.decorators import login_required
from web.utils import log_admin_action, parse_duration_to_minutes, to_unix_ts_utc

users_bp = Blueprint("users", __name__)


@users_bp.get("/users")
@login_required
def users_list():
    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50

    db = SessionLocal()
    try:
        query = db.query(User)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                User.username.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                cast(User.id, String).ilike(like),
            ))

        total = query.count()
        users = query.order_by(desc(User.last_activity)).offset((page - 1) * per_page).limit(per_page).all()

        user_ids = [u.id for u in users]
        total_map, active_map = {}, {}
        if user_ids:
            total_map = dict(
                db.query(Punishment.user_id, func.count(Punishment.id))
                .filter(Punishment.user_id.in_(user_ids)).group_by(Punishment.user_id).all()
            )
            active_map = dict(
                db.query(Punishment.user_id, func.count(Punishment.id))
                .filter(Punishment.user_id.in_(user_ids), Punishment.active == True)
                .group_by(Punishment.user_id).all()
            )

        for user in users:
            user.punishments_count = int(total_map.get(user.id, 0) or 0)
            user.active_punishments_count = int(active_map.get(user.id, 0) or 0)

        total_pages = (total + per_page - 1) // per_page
        return render_template("users.html", users=users, page=page,
                               total_pages=total_pages, q=q)
    finally:
        db.close()


@users_bp.get("/user/<int:user_id>")
@login_required
def user_detail(user_id):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            flash("Пользователь не найден", "error")
            return redirect(url_for("users.users_list"))

        accessible = get_accessible_chats()
        punishments_q = db.query(Punishment).options(joinedload(Punishment.chat)).filter_by(user_id=user_id)
        if accessible is not None:
            punishments_q = punishments_q.filter(Punishment.chat_id.in_(accessible))
        punishments = punishments_q.order_by(desc(Punishment.date)).all()

        now = datetime.datetime.utcnow()
        current_status = {}
        for p in punishments:
            if p.active:
                if p.until_date and p.until_date <= now:
                    p.active = False
                    db.add(p)
                elif p.type != "ban":
                    from core.tz import to_msk_str
                    chat_title = p.chat.title if p.chat and p.chat.title else str(p.chat_id)
                    text = f"{p.type.upper()} в чате '{chat_title}'"
                    if p.until_date:
                        try:
                            text += f" до {to_msk_str(p.until_date)} МСК"
                        except Exception:
                            pass
                    else:
                        text += " (бессрочно)"
                    current_status[p.chat_id] = {"text": text, "type": p.type, "until": p.until_date}

        db.commit()
        notes = db.query(Note).filter_by(user_id=user_id).order_by(desc(Note.created_at)).all()

        probations_q = db.query(Probation).options(joinedload(Probation.chat)).filter_by(user_id=user_id)
        if accessible is not None:
            probations_q = probations_q.filter(Probation.chat_id.in_(accessible))
        probations_all = probations_q.order_by(desc(Probation.until_date)).all()

        probations = []
        for pr in probations_all:
            if pr.until_date <= now:
                db.delete(pr)
            else:
                probations.append(pr)
        if len(probations) != len(probations_all):
            db.commit()

        chats_q = db.query(Chat).order_by(Chat.title)
        chats = (
            chats_q.filter(Chat.id.in_(accessible)).all() if accessible is not None and accessible
            else [] if accessible == []
            else chats_q.all()
        )

        punishment_stats = dict(
            db.query(Punishment.type, func.count(Punishment.id))
            .filter(Punishment.user_id == user_id).group_by(Punishment.type).all()
        )
    finally:
        db.close()

    return render_template("user_detail.html", user=user, punishments=punishments,
                           current_status=current_status, notes=notes, chats=chats,
                           probations=probations, punishment_stats=punishment_stats)


@users_bp.post("/user/<int:user_id>/note")
@login_required
def add_note(user_id):
    content = request.form.get("note", "").strip()
    if not content:
        flash("Примечание не может быть пустым", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    admin_id, admin_name, _, _ = get_current_admin_info()

    db = SessionLocal()
    try:
        if not db.get(User, user_id):
            flash("Пользователь не найден", "error")
            return redirect(url_for("users.users_list"))
        db.add(Note(user_id=user_id, content=content,
                    author_id=admin_id, author_name=admin_name or "Admin"))
        db.commit()
        log_admin_action("note", f"Added note to user {user_id}")
        flash("Примечание добавлено", "success")
    finally:
        db.close()

    return redirect(url_for("users.user_detail", user_id=user_id))


@users_bp.post("/note/<int:note_id>/delete")
@login_required
def delete_note(note_id):
    db = SessionLocal()
    try:
        note = db.get(Note, note_id)
        if not note:
            flash("Примечание не найдено", "error")
            return redirect(url_for("users.users_list"))
        user_id = note.user_id
        db.delete(note)
        db.commit()
        log_admin_action("note_delete", f"Deleted note {note_id}")
        flash("Примечание удалено", "success")
        return redirect(url_for("users.user_detail", user_id=user_id))
    finally:
        db.close()


@users_bp.post("/user/<int:user_id>/probation")
@login_required
def set_probation(user_id):
    if is_kill_switch_enabled():
        flash("⛔️ Киллсвитч активен: изменения по модерации временно отключены.", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    admin_id, admin_name, _, _ = get_current_admin_info()

    try:
        chat_id = int(request.form.get("chat_id"))
    except Exception:
        flash("Неверный chat_id", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    accessible = get_accessible_chats()
    if accessible is not None and chat_id not in accessible:
        flash("У вас нет прав для управления этим чатом.", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    duration_str = (request.form.get("duration") or "").strip()
    reason = (request.form.get("reason") or "").strip()

    try:
        minutes = parse_duration_to_minutes(duration_str)
    except ValueError:
        flash("Неверный формат срока. Пример: 30d / 12h / 90m", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    if minutes <= 0:
        flash("Срок должен быть больше 0", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    now = datetime.datetime.utcnow()
    until_date = now + datetime.timedelta(minutes=minutes)

    db = SessionLocal()
    try:
        if not db.get(User, user_id):
            db.add(User(id=user_id))
        if not db.get(Chat, chat_id):
            db.add(Chat(id=chat_id))

        pr = db.query(Probation).filter_by(chat_id=chat_id, user_id=user_id).first()
        if pr:
            pr.until_date, pr.reason = until_date, reason
            pr.created_by_id, pr.created_by_name = admin_id, admin_name
        else:
            db.add(Probation(chat_id=chat_id, user_id=user_id, until_date=until_date,
                             reason=reason, created_by_id=admin_id, created_by_name=admin_name))

        db.commit()
        log_admin_action("probation", f"Set probation for user {user_id} in chat {chat_id}")
        flash("Испытательный срок назначен", "success")
    finally:
        db.close()

    return redirect(url_for("users.user_detail", user_id=user_id))


@users_bp.post("/probation/<int:probation_id>/delete")
@login_required
def delete_probation(probation_id):
    db = SessionLocal()
    try:
        pr = db.get(Probation, probation_id)
        if not pr:
            flash("Испытательный срок не найден", "error")
            return redirect(url_for("users.users_list"))

        accessible = get_accessible_chats()
        if accessible is not None and pr.chat_id not in accessible:
            flash("У вас нет прав для управления этим чатом.", "error")
            return redirect(url_for("users.user_detail", user_id=pr.user_id))

        if is_kill_switch_enabled():
            flash("⛔️ Киллсвитч активен.", "error")
            return redirect(url_for("users.user_detail", user_id=pr.user_id))

        user_id = pr.user_id
        db.delete(pr)
        db.commit()
        log_admin_action("probation_remove", f"Removed probation {probation_id}")
        flash("Испытательный срок снят", "success")
        return redirect(url_for("users.user_detail", user_id=user_id))
    finally:
        db.close()


@users_bp.post("/user/<int:user_id>/punish")
@login_required
def punish_user_via_web(user_id):
    if is_kill_switch_enabled():
        flash("⛔️ Киллсвитч активен: модерационные действия временно отключены.", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    try:
        chat_id = int(request.form.get("chat_id"))
    except Exception:
        flash("Неверный chat_id", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    p_type = (request.form.get("type") or "").strip()
    duration_str = (request.form.get("duration") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    admin_id, admin_name, _, _ = get_current_admin_info()

    accessible = get_accessible_chats()
    if accessible is not None and chat_id not in accessible:
        flash("У вас нет прав для управления этим чатом.", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    try:
        requested_minutes = parse_duration_to_minutes(duration_str) if duration_str else 0
    except ValueError:
        flash("Неверный формат длительности. Пример: 30m / 12h / 7d", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    now = datetime.datetime.utcnow()

    multiplier = 1
    if p_type in ("mute", "mutemedia", "ban") and requested_minutes > 0:
        db = SessionLocal()
        try:
            pr = db.query(Probation).filter_by(chat_id=chat_id, user_id=user_id).first()
            if pr and pr.until_date and pr.until_date > now:
                multiplier = 2
        finally:
            db.close()

    applied_minutes = requested_minutes * multiplier if requested_minutes > 0 else 0
    until_date = now + datetime.timedelta(minutes=applied_minutes) if applied_minutes > 0 else None
    until_ts = to_unix_ts_utc(until_date)

    try:
        import telebot
        from telebot import types
        tbot = telebot.TeleBot(BOT_TOKEN)

        try:
            member = tbot.get_chat_member(chat_id, user_id)
            if member.status in ("administrator", "creator"):
                flash("❌ Нельзя наказать администратора через эту форму. Сначала снимите права.", "error")
                return redirect(url_for("users.user_detail", user_id=user_id))
        except Exception:
            pass

        if p_type == "mute":
            tbot.restrict_chat_member(chat_id, user_id,
                                      permissions=types.ChatPermissions(can_send_messages=False),
                                      until_date=until_ts)
        elif p_type == "mutemedia":
            tbot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(
                can_send_messages=True, can_send_audios=False, can_send_documents=False,
                can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
                can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
                can_add_web_page_previews=True), until_date=until_ts)
        elif p_type == "ban":
            tbot.ban_chat_member(chat_id, user_id, until_date=until_ts)
        elif p_type == "kick":
            tbot.ban_chat_member(chat_id, user_id)
            tbot.unban_chat_member(chat_id, user_id)
        else:
            flash("Неизвестный тип наказания", "error")
            return redirect(url_for("users.user_detail", user_id=user_id))
    except Exception as e:
        flash(f"Ошибка применения наказания через Telegram: {e}", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    db = SessionLocal()
    try:
        if not db.get(User, user_id):
            db.add(User(id=user_id))
        if not db.get(Chat, chat_id):
            db.add(Chat(id=chat_id))
        db.add(Punishment(
            user_id=user_id, chat_id=chat_id, type=p_type, reason=reason,
            admin_id=admin_id, admin_name=admin_name or "web",
            date=now, until_date=until_date,
            active=False if p_type == "kick" else True,
            requested_duration_minutes=requested_minutes if p_type in ("mute", "mutemedia", "ban") else None,
            applied_duration_minutes=applied_minutes if p_type in ("mute", "mutemedia", "ban") else None,
        ))
        db.commit()
        log_admin_action("punishment", f"Applied {p_type} to user {user_id} in chat {chat_id}")
        flash(f"Наказание применено{f' (испытательный срок x{multiplier})' if multiplier > 1 else ''}", "success")
    finally:
        db.close()

    return redirect(url_for("users.user_detail", user_id=user_id))


@users_bp.post("/punishment/<int:pun_id>/cancel")
@login_required
def cancel_punishment(pun_id):
    admin_id, admin_name, _, _ = get_current_admin_info()

    db = SessionLocal()
    try:
        p = db.get(Punishment, pun_id)
        if not p:
            flash("Наказание не найдено", "error")
            return redirect(url_for("users.users_list"))

        accessible = get_accessible_chats()
        if accessible is not None and p.chat_id not in accessible:
            flash("У вас нет прав для управления этим чатом.", "error")
            return redirect(url_for("users.user_detail", user_id=p.user_id))

        if is_kill_switch_enabled():
            flash("⛔️ Киллсвитч активен.", "error")
            return redirect(url_for("users.user_detail", user_id=p.user_id))

        try:
            import telebot
            from telebot import types
            tbot = telebot.TeleBot(BOT_TOKEN)
            if p.type in ("mute", "mutemedia"):
                ch = tbot.get_chat(p.chat_id)
                perms = getattr(ch, "permissions", None) or types.ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True,
                    can_send_other_messages=True, can_add_web_page_previews=True)
                tbot.restrict_chat_member(p.chat_id, p.user_id, permissions=perms, until_date=0)
            elif p.type == "ban":
                tbot.unban_chat_member(p.chat_id, p.user_id)
        except Exception as e:
            flash(f"Ошибка при снятии наказания в Telegram: {e}", "error")
            return redirect(url_for("users.user_detail", user_id=p.user_id))

        p.active = False
        p.removed_at = datetime.datetime.utcnow()
        p.removed_by_id, p.removed_by_name = admin_id, admin_name
        db.commit()
        log_admin_action("remove_punishment", f"Removed punishment {pun_id}")
        flash("Наказание снято успешно", "success")
        return redirect(url_for("users.user_detail", user_id=p.user_id))
    finally:
        db.close()


@users_bp.post("/user/<int:user_id>/blacklist")
@login_required
def blacklist_user(user_id):
    if not is_current_superadmin():
        flash("Доступ запрещен. Черный список доступен только супер-администратору.", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    reason = request.form.get("reason", "").strip()
    admin_id, admin_name, _, _ = get_current_admin_info()

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            flash("Пользователь не найден", "error")
            return redirect(url_for("users.users_list"))
        user.is_blacklisted = True
        user.blacklist_reason = reason or "Заблокирован администратором"
        user.blacklisted_at = datetime.datetime.utcnow()
        user.blacklisted_by = admin_name or "Admin"
        db.commit()
        log_admin_action("blacklist", f"Blacklisted user {user_id}: {reason}")
        flash(f"Пользователь {user.display_name()} добавлен в ЧС", "success")
    finally:
        db.close()

    return redirect(url_for("users.user_detail", user_id=user_id))


@users_bp.post("/user/<int:user_id>/unblacklist")
@login_required
def unblacklist_user(user_id):
    if not is_current_superadmin():
        flash("Доступ запрещен.", "error")
        return redirect(url_for("users.user_detail", user_id=user_id))

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            flash("Пользователь не найден", "error")
            return redirect(url_for("users.users_list"))
        user.is_blacklisted = False
        user.blacklist_reason = None
        user.blacklisted_at = None
        user.blacklisted_by = None
        db.commit()
        log_admin_action("unblacklist", f"Unblacklisted user {user_id}")
        flash(f"Пользователь {user.display_name()} убран из ЧС", "success")
    finally:
        db.close()

    return redirect(url_for("users.user_detail", user_id=user_id))


@users_bp.get("/blacklist")
@login_required
def blacklist():
    if not is_current_superadmin():
        flash("Доступ запрещен.", "error")
        return redirect(url_for("dashboard.dashboard"))

    db = SessionLocal()
    try:
        blacklisted = db.query(User).filter(User.is_blacklisted == True).order_by(
            desc(User.blacklisted_at)).all()
    finally:
        db.close()

    return render_template("blacklist.html", users=blacklisted)
