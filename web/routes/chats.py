"""Маршруты чатов: /chats, /chat/<id>, /api/chat/<id>/topics."""
from __future__ import annotations

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload

from core.config import BOT_TOKEN
from core.models import Chat, ChatMember, ChatTopic, Punishment, SessionLocal
from web.context import get_accessible_chats, is_current_superadmin
from web.decorators import login_required

chats_bp = Blueprint("chats", __name__)


@chats_bp.get("/chats")
@login_required
def chats_list():
    filter_type = request.args.get("filter", "all")

    db = SessionLocal()
    try:
        query = db.query(Chat)
        accessible = get_accessible_chats()
        if accessible is not None:
            if not accessible:
                return render_template("chats.html", chats=[], filter_type=filter_type)
            query = query.filter(Chat.id.in_(accessible))

        if filter_type == "private":
            query = query.filter(Chat.chat_type == "private")
        elif filter_type == "groups":
            query = query.filter(Chat.chat_type.in_(["group", "supergroup"]))

        chats = query.order_by(desc(Chat.last_activity)).all()

        chat_ids = [c.id for c in chats]
        if chat_ids:
            total_map = dict(
                db.query(Punishment.chat_id, func.count(Punishment.id))
                .filter(Punishment.chat_id.in_(chat_ids))
                .group_by(Punishment.chat_id).all()
            )
            active_map = dict(
                db.query(Punishment.chat_id, func.count(Punishment.id))
                .filter(Punishment.chat_id.in_(chat_ids), Punishment.active == True)
                .group_by(Punishment.chat_id).all()
            )
        else:
            total_map, active_map = {}, {}

        for chat in chats:
            chat.punishments_count = int(total_map.get(chat.id, 0) or 0)
            chat.active_punishments_count = int(active_map.get(chat.id, 0) or 0)

        return render_template("chats.html", chats=chats, filter_type=filter_type)
    finally:
        db.close()


@chats_bp.get("/chat/<chat_id>")
@login_required
def chat_detail(chat_id):
    try:
        chat_id = int(chat_id)
    except ValueError:
        flash("Неверный ID чата", "error")
        return redirect(url_for("chats.chats_list"))

    db = SessionLocal()
    try:
        chat = db.get(Chat, chat_id)
        if not chat:
            flash("Чат не найден", "error")
            return redirect(url_for("chats.chats_list"))

        accessible = get_accessible_chats()
        if accessible is not None and chat_id not in accessible:
            flash("У вас нет прав для просмотра этого чата.", "error")
            return redirect(url_for("chats.chats_list"))

        stats = {
            "total_punishments": db.query(func.count(Punishment.id))
                .filter(Punishment.chat_id == chat_id).scalar(),
            "active_punishments": db.query(func.count(Punishment.id))
                .filter(Punishment.chat_id == chat_id, Punishment.active == True).scalar(),
        }

        punishments = (
            db.query(Punishment)
            .options(joinedload(Punishment.user))
            .filter(Punishment.chat_id == chat_id)
            .order_by(desc(Punishment.date)).limit(20).all()
        )

        members = (
            db.query(ChatMember)
            .options(joinedload(ChatMember.user))
            .filter(ChatMember.chat_id == chat_id, ChatMember.left_at == None)
            .order_by(ChatMember.is_admin.desc(), ChatMember.joined_at.desc())
            .all()
        )
        admins = [m for m in members if m.is_admin]
        regular_members = [m for m in members if not m.is_admin]

        stats["total_members"] = db.query(func.count(ChatMember.id)).filter(
            ChatMember.chat_id == chat_id, ChatMember.left_at == None
        ).scalar() or 0
        stats["admins_count"] = db.query(func.count(ChatMember.id)).filter(
            ChatMember.chat_id == chat_id, ChatMember.is_admin == True, ChatMember.left_at == None
        ).scalar() or 0

        if chat.is_group() and BOT_TOKEN:
            try:
                import telebot
                tbot = telebot.TeleBot(BOT_TOKEN)
                chat.member_count = tbot.get_chat_member_count(chat_id)
                db.commit()
            except Exception:
                pass
    finally:
        db.close()

    return render_template("chat_detail.html", chat=chat, stats=stats,
                           punishments=punishments, members=regular_members,
                           admins=admins, all_members=members)


@chats_bp.get("/api/chat/<int:chat_id>/topics")
@login_required
def api_chat_topics(chat_id: int):
    if not is_current_superadmin():
        abort(403)

    db = SessionLocal()
    try:
        rows = (
            db.query(ChatTopic)
            .filter(ChatTopic.chat_id == chat_id)
            .order_by(ChatTopic.last_activity.desc(), ChatTopic.thread_id.desc())
            .all()
        )
        return jsonify([
            {"thread_id": r.thread_id, "title": (r.title or "").strip() or f"Topic {r.thread_id}"}
            for r in rows
        ])
    finally:
        db.close()
