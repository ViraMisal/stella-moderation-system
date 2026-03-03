"""Декораторы Flask для веб-панели."""
from __future__ import annotations

from functools import wraps

from flask import abort, redirect, session, url_for


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def superadmin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("auth.login"))
        if session.get("role") != "superadmin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper
