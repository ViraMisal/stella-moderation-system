"""Маршруты авторизации: /login, /tg_auth, /logout."""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from core.config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    ALLOWED_TG_IDS,
    BOT_TOKEN,
    BOT_USERNAME,
)
from core.models import SessionLocal, User
from src_utils.alerts import send_alert
from web.admin_groups import update_user_admin_status
from web.context import get_current_admin_info
from web.utils import log_admin_action

auth_bp = Blueprint("auth", __name__)

# --- Защита от перебора пароля ---
_LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "12"))
_LOGIN_RATE_WINDOW = int(os.getenv("LOGIN_RATE_WINDOW_SEC", "900"))
_LOGIN_FAILS: dict = {}
_LOGIN_LOCK = threading.Lock()


def _client_ip() -> str:
    xf = request.headers.get("X-Forwarded-For", "")
    return xf.split(",")[0].strip() if xf else (request.remote_addr or "unknown")


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    with _LOGIN_LOCK:
        arr = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < _LOGIN_RATE_WINDOW]
        _LOGIN_FAILS[ip] = arr
        return len(arr) >= _LOGIN_RATE_LIMIT


def _record_fail(ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILS.setdefault(ip, []).append(time.time())


def _clear_fails(ip: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(ip, None)


def _check_password(username: str, password: str) -> bool:
    if not hmac.compare_digest(username or "", ADMIN_USERNAME or ""):
        return False
    stored = ADMIN_PASSWORD or ""
    if stored.startswith(("pbkdf2:", "scrypt:", "argon2:")):
        try:
            return check_password_hash(stored, password or "")
        except Exception:
            return False
    return hmac.compare_digest(password or "", stored)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = _client_ip()
        if _is_rate_limited(ip):
            send_alert("brute_force", f"Rate limit на логин: {ip}")
            flash("Слишком много попыток входа. Подождите и попробуйте снова.", "error")
            return render_template("login.html", bot_username=BOT_USERNAME), 429

        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if _check_password(u, p):
            _clear_fails(ip)
            session.update({"admin": True, "who": f"local:{u}", "admin_id": None,
                            "role": "superadmin", "admin_chats": []})
            log_admin_action("login", f"Local login: {u}")
            flash("Вход выполнен успешно!", "success")
            return redirect(url_for("dashboard.dashboard"))
        _record_fail(ip)
        flash("Неверные учетные данные", "error")
    return render_template("login.html", bot_username=BOT_USERNAME)


@auth_bp.get("/tg_auth")
def tg_auth():
    if not BOT_TOKEN:
        flash("BOT_TOKEN не настроен", "error")
        return redirect(url_for("auth.login"))

    data = {k: v for k, v in request.args.items() if k != "hash"}
    received_hash = request.args.get("hash", "")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calc_hash, received_hash):
        flash("Telegram авторизация отклонена (hash mismatch).", "error")
        return redirect(url_for("auth.login"))

    try:
        auth_date = int(data.get("auth_date", "0") or "0")
    except (ValueError, TypeError):
        auth_date = 0
    if abs(time.time() - auth_date) > 3600:
        flash("Сессия авторизации устарела, попробуйте снова.", "error")
        return redirect(url_for("auth.login"))

    uid = int(data.get("id", "0") or "0")

    db = SessionLocal()
    try:
        user = db.get(User, uid)
        if not user:
            user = User(id=uid, username=data.get("username"),
                        first_name=data.get("first_name"),
                        last_name=data.get("last_name"))
            db.add(user)
            db.commit()
        if ALLOWED_TG_IDS and uid in ALLOWED_TG_IDS:
            user.role = "superadmin"
            user.is_web_admin = True
            db.commit()
    finally:
        db.close()

    role, admin_chats = update_user_admin_status(uid)

    db = SessionLocal()
    try:
        user = db.get(User, uid)
        if user:
            user.role = role
            user.is_web_admin = (role != "user")
            db.commit()
    finally:
        db.close()

    display_name = (
        f"@{data['username']}" if data.get("username")
        else (f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or f"ID:{uid}")
    )

    session.update({
        "admin": True, "who": display_name, "admin_id": uid,
        "admin_username": data.get("username", f"ID:{uid}"),
        "role": role, "admin_chats": admin_chats,
    })
    log_admin_action("login", f"Telegram login: {display_name} (role: {role})", uid, display_name)

    if role == "superadmin":
        flash("Вход выполнен как супер-администратор!", "success")
    elif role != "user":
        flash(f"Вход выполнен! Доступно {len(admin_chats)} групп(ы).", "success")
    else:
        flash("У вас пока нет прав администратора ни в одной группе.", "info")

    return redirect(url_for("dashboard.dashboard"))


@auth_bp.get("/logout")
def logout():
    admin_id, admin_name, _, _ = get_current_admin_info()
    log_admin_action("logout", admin_id=admin_id, admin_name=admin_name)
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("auth.login"))
