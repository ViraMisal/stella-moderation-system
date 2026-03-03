"""Маршруты настроек: /settings, /settings/update, /settings/ai/reset."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from core.config import (
    AI_DEFAULT_FALLBACK_TEXT,
    AI_DEFAULT_MAX_TOKENS,
    AI_DEFAULT_SYSTEM_PROMPT_IMAGE,
    AI_DEFAULT_SYSTEM_PROMPT_TEXT,
    AI_DEFAULT_TEMPERATURE,
)
from core.models import AIConversation, SessionLocal, Settings
from core.settings import settings_cache
from web.context import get_current_admin_info
from web.decorators import superadmin_required
from web.utils import log_admin_action

settings_bp = Blueprint("settings", __name__)


@settings_bp.get("/settings")
@superadmin_required
def settings():
    db = SessionLocal()
    try:
        settings_dict = {s.key: s for s in db.query(Settings).all()}
    finally:
        db.close()

    return render_template("settings.html", settings=settings_dict, ai_defaults={
        "system_prompt_text": AI_DEFAULT_SYSTEM_PROMPT_TEXT,
        "system_prompt_image": AI_DEFAULT_SYSTEM_PROMPT_IMAGE,
        "temperature": AI_DEFAULT_TEMPERATURE,
        "max_tokens": AI_DEFAULT_MAX_TOKENS,
        "fallback_text": AI_DEFAULT_FALLBACK_TEXT,
    })


@settings_bp.post("/settings/update")
@superadmin_required
def update_settings():
    _, admin_name, _, _ = get_current_admin_info()

    kill_switch = request.form.get("kill_switch") == "on"
    appeals_chat_id_raw = (request.form.get("appeals_chat_id") or "").strip()
    ai_enabled = request.form.get("ai_enabled") == "on"
    ai_trigger = (request.form.get("ai_trigger") or "стелла").strip()
    ai_allowed_chats = (request.form.get("ai_allowed_chats") or "").strip()
    ai_user_whitelist = (request.form.get("ai_user_whitelist") or "").strip()
    ai_user_blacklist = (request.form.get("ai_user_blacklist") or "").strip()
    ai_system_prompt_text = (request.form.get("ai_system_prompt_text") or "").strip()
    ai_system_prompt_image = (request.form.get("ai_system_prompt_image") or "").strip()
    ai_fallback_text = (request.form.get("ai_fallback_text") or "").strip()

    # Числовые поля
    try:
        ai_rate_limit_seconds = max(0, int((request.form.get("ai_rate_limit_seconds") or "10").strip()))
    except ValueError:
        flash("Неверное значение rate limit (секунды)", "error")
        return redirect(url_for("settings.settings"))

    try:
        ai_max_history = max(0, int((request.form.get("ai_max_history") or "10").strip()))
    except ValueError:
        flash("Неверное значение max history", "error")
        return redirect(url_for("settings.settings"))

    ai_temperature_raw = (request.form.get("ai_temperature") or "").strip()
    ai_temperature = None
    if ai_temperature_raw:
        try:
            val = float(ai_temperature_raw)
            if not (0 <= val <= 2):
                raise ValueError
            ai_temperature = val
        except ValueError:
            flash("temperature должен быть в диапазоне 0..2", "error")
            return redirect(url_for("settings.settings"))

    ai_max_tokens_raw = (request.form.get("ai_max_tokens") or "").strip()
    ai_max_tokens = None
    if ai_max_tokens_raw:
        try:
            val = int(ai_max_tokens_raw)
            if not (50 <= val <= 4000):
                raise ValueError
            ai_max_tokens = val
        except ValueError:
            flash("max tokens должен быть в диапазоне 50..4000", "error")
            return redirect(url_for("settings.settings"))

    if appeals_chat_id_raw:
        try:
            int(appeals_chat_id_raw)
        except ValueError:
            flash("Неверный appeals_chat_id (должен быть числом)", "error")
            return redirect(url_for("settings.settings"))

    db = SessionLocal()
    try:
        S = Settings.set
        S(db, "kill_switch", "true" if kill_switch else "false",
          updated_by=admin_name, description="Emergency stop for moderation actions")
        S(db, "appeals_chat_id", appeals_chat_id_raw or None,
          updated_by=admin_name, description="Where /appeal messages are forwarded")
        S(db, "ai_enabled", "true" if ai_enabled else "false",
          updated_by=admin_name, description="Enable/disable conversational AI")
        S(db, "ai_trigger", ai_trigger, updated_by=admin_name, description="Trigger word(s) for AI")
        S(db, "ai_allowed_chats", ai_allowed_chats, updated_by=admin_name,
          description="Comma-separated chat IDs where AI is allowed")
        S(db, "ai_rate_limit_seconds", str(ai_rate_limit_seconds),
          updated_by=admin_name, description="Per-user AI rate limit (seconds)")
        S(db, "ai_max_history", str(ai_max_history),
          updated_by=admin_name, description="Max stored history messages for AI")
        S(db, "ai_user_whitelist", ai_user_whitelist, updated_by=admin_name,
          description="AI user whitelist (IDs)")
        S(db, "ai_user_blacklist", ai_user_blacklist, updated_by=admin_name,
          description="AI user blacklist (IDs)")
        S(db, "ai_system_prompt_text", ai_system_prompt_text or None,
          updated_by=admin_name, description="AI system prompt for text")
        S(db, "ai_system_prompt_image", ai_system_prompt_image or None,
          updated_by=admin_name, description="AI system prompt for images")
        S(db, "ai_temperature",
          str(ai_temperature) if ai_temperature is not None else None,
          updated_by=admin_name, description="AI temperature")
        S(db, "ai_max_tokens",
          str(ai_max_tokens) if ai_max_tokens is not None else None,
          updated_by=admin_name, description="AI max tokens")
        S(db, "ai_fallback_text", ai_fallback_text or None,
          updated_by=admin_name, description="Text returned when AI request fails")

        log_admin_action("settings_update", "Updated global settings")
        flash("Настройки сохранены!", "success")
    finally:
        db.close()

    settings_cache.invalidate_all()
    return redirect(url_for("settings.settings"))


@settings_bp.post("/settings/ai/reset")
@superadmin_required
def reset_ai_contexts():
    db = SessionLocal()
    try:
        db.query(AIConversation).delete()
        db.commit()
        log_admin_action("ai_reset", "Reset all AI conversations")
        flash("AI контексты сброшены", "success")
    finally:
        db.close()

    return redirect(url_for("settings.settings"))
