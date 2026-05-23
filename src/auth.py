"""
auth.py — Authentication: email+password AND Google OAuth.

Routes:
  GET/POST  /login              → sign-in form
  GET/POST  /register           → create account form
  GET       /auth/logout
  GET       /auth/google        → redirect to Google
  GET       /auth/google/callback → handle Google callback
"""

from __future__ import annotations

import os
import re
import shutil
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint, redirect, url_for, session,
    render_template, request, jsonify,
)

auth_bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_oauth = None  # Authlib OAuth registry, set in init_oauth()


# ── Compatibility shim ────────────────────────────────────────────────────

def init_oauth(app):
    """Called by web_app.py. Initialises DB and (optionally) Google OAuth."""
    global _oauth
    _get_db().init_db()
    if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
        from authlib.integrations.flask_client import OAuth
        _oauth = OAuth(app)
        _oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )


def _get_db():
    if os.environ.get("DATABASE_URL"):
        import cloud_db as _db
    else:
        import db as _db
    return _db


# ── login_required decorator ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


# ── Email / password routes ───────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user_id"):
        return redirect("/")
    google_enabled = _oauth is not None
    if request.method == "POST":
        db     = _get_db()
        email  = (request.form.get("email") or "").strip()
        passwd = request.form.get("password") or ""
        user   = db.verify_user(email, passwd)
        if not user:
            return render_template("login.html", tab="login", google=google_enabled,
                                   error="Invalid email or password.", email=email)
        _set_session(user)
        _bootstrap_vault(user["id"])
        return redirect("/")
    return render_template("login.html", tab="login", google=google_enabled)


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if session.get("user_id"):
        return redirect("/")
    google_enabled = _oauth is not None
    if request.method == "POST":
        db      = _get_db()
        email   = (request.form.get("email") or "").strip()
        name    = (request.form.get("name")  or "").strip()
        passwd  = request.form.get("password") or ""
        confirm = request.form.get("confirm")  or ""

        if not _EMAIL_RE.match(email):
            return render_template("login.html", tab="register", google=google_enabled,
                                   error="Enter a valid email address.", email=email, name=name)
        if len(passwd) < 8:
            return render_template("login.html", tab="register", google=google_enabled,
                                   error="Password must be at least 8 characters.", email=email, name=name)
        if passwd != confirm:
            return render_template("login.html", tab="register", google=google_enabled,
                                   error="Passwords do not match.", email=email, name=name)

        user = db.register_user(email, name, passwd)
        if not user:
            return render_template("login.html", tab="register", google=google_enabled,
                                   error="An account with this email already exists.", email=email, name=name)
        _set_session(user)
        _bootstrap_vault(user["id"])
        return redirect("/")
    return render_template("login.html", tab="register", google=google_enabled)


@auth_bp.route("/auth/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


# ── Google OAuth routes ───────────────────────────────────────────────────

@auth_bp.route("/auth/google")
def google_login():
    if _oauth is None:
        return redirect(url_for("auth.login_page"))
    callback_url = url_for("auth.google_callback", _external=True)
    return _oauth.google.authorize_redirect(callback_url)


@auth_bp.route("/auth/google/callback")
def google_callback():
    if _oauth is None:
        return redirect(url_for("auth.login_page"))
    try:
        token     = _oauth.google.authorize_access_token()
        userinfo  = token.get("userinfo") or _oauth.google.userinfo()
        email     = userinfo["email"]
        name      = userinfo.get("name", email.split("@")[0])
    except Exception:
        return redirect(url_for("auth.login_page"))

    db   = _get_db()
    user = db.get_user_by_email(email)
    if not user:
        # Auto-register Google users (no password)
        user = db.register_user(email, name, password=None)
    if not user:
        return redirect(url_for("auth.login_page"))

    _set_session(user)
    _bootstrap_vault(user["id"])
    return redirect("/")


# ── Helpers ───────────────────────────────────────────────────────────────

def _set_session(user: dict):
    from datetime import timedelta
    session.permanent = True
    session["user_id"]    = user["id"]
    session["user_name"]  = user.get("name", "")
    session["user_email"] = user.get("email", "")


def _bootstrap_vault(user_id: str):
    if os.environ.get("DATABASE_URL"):
        _bootstrap_cloud(user_id)
    else:
        _bootstrap_local(user_id)


def _bootstrap_cloud(user_id: str):
    import cloud_db as db
    if db.list_notes(user_id):
        return
    starters = [
        ("_context", "Master Context",
         "# Master Context\n\n"
         "> This note is **always injected** into every AI query.\n\n"
         "## Who I Am\nName: \nRole: \nPrimary focus areas:\n\n"
         "## Current Active Projects\n- \n\n"
         "## Core Goals (This Quarter)\n1. \n2. \n3. \n\n"
         "## Working Style\n- Preferred communication: concise, direct\n\n"
         "## Recent Context (update weekly)\nCurrent focus:\n"),
        ("_context", "AI Preferences",
         "# AI Preferences\n\n"
         "## Response Style\n- Be concise\n- Cite notes in [brackets]\n- No filler phrases\n\n"
         "## Do\n- Surface connections between ideas\n- Challenge assumptions\n\n"
         "## Don't\n- Hallucinate\n- Add unsolicited warnings\n"),
        ("projects", "Project Template",
         "# Project Name\n\n**Status:** Active\n**Started:** \n\n"
         "## Goal\n\n## Key Decisions\n\n## Open Questions\n- [ ] \n\n## Lessons Learned\n"),
    ]
    for folder, title, content in starters:
        db.create_note(user_id, title, content, folder=folder)


def _bootstrap_local(user_id: str):
    from _config import cfg
    vault_root = Path(cfg["vault"]["path"])
    user_vault = vault_root / "users" / user_id
    if user_vault.exists():
        return
    for folder in ["_context", "projects", "daily-notes", "meetings", "reflections"]:
        (user_vault / folder).mkdir(parents=True, exist_ok=True)
    for src in vault_root.rglob("*.md"):
        if "users" in src.parts:
            continue
        dst = user_vault / src.relative_to(vault_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))


from __future__ import annotations

import os
import re
import shutil
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint, redirect, url_for, session,
    render_template, request, jsonify,
)

auth_bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ── Compatibility shim ────────────────────────────────────────────────────

def init_oauth(app):
    """Called by web_app.py. Initialises DB (cloud or local)."""
    _get_db().init_db()


def _get_db():
    """Return cloud_db if DATABASE_URL is set, else local db."""
    if os.environ.get("DATABASE_URL"):
        import cloud_db as _db
    else:
        import db as _db
    return _db


# ── login_required decorator ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return decorated


# ── Routes ────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user_id"):
        return redirect("/")

    if request.method == "POST":
        db     = _get_db()
        email  = (request.form.get("email") or "").strip()
        passwd = request.form.get("password") or ""
        user   = db.verify_user(email, passwd)
        if not user:
            return render_template("login.html", tab="login",
                                   error="Invalid email or password.", email=email)
        _set_session(user)
        _bootstrap_vault(user["id"])
        return redirect("/")

    return render_template("login.html", tab="login")


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if session.get("user_id"):
        return redirect("/")

    if request.method == "POST":
        db      = _get_db()
        email   = (request.form.get("email") or "").strip()
        name    = (request.form.get("name")  or "").strip()
        passwd  = request.form.get("password") or ""
        confirm = request.form.get("confirm")  or ""

        if not _EMAIL_RE.match(email):
            return render_template("login.html", tab="register",
                                   error="Enter a valid email address.", email=email, name=name)
        if len(passwd) < 8:
            return render_template("login.html", tab="register",
                                   error="Password must be at least 8 characters.", email=email, name=name)
        if passwd != confirm:
            return render_template("login.html", tab="register",
                                   error="Passwords do not match.", email=email, name=name)

        user = db.register_user(email, name, passwd)
        if not user:
            return render_template("login.html", tab="register",
                                   error="An account with this email already exists.", email=email, name=name)
        _set_session(user)
        _bootstrap_vault(user["id"])
        return redirect("/")

    return render_template("login.html", tab="register")


@auth_bp.route("/auth/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


# ── Helpers ───────────────────────────────────────────────────────────────

def _set_session(user: dict):
    from datetime import timedelta
    session.permanent = True
    session["user_id"]    = user["id"]
    session["user_name"]  = user.get("name", "")
    session["user_email"] = user.get("email", "")


def _bootstrap_vault(user_id: str):
    """Seed starter notes for a brand-new user."""
    if os.environ.get("DATABASE_URL"):
        _bootstrap_cloud(user_id)
    else:
        _bootstrap_local(user_id)


def _bootstrap_cloud(user_id: str):
    """Create starter notes in PostgreSQL for a new cloud user."""
    import cloud_db as db
    if db.list_notes(user_id):
        return  # Already has notes

    starters = [
        ("_context", "Master Context",
         "# Master Context\n\n"
         "> This note is **always injected** into every AI query.\n\n"
         "## Who I Am\nName: \nRole: \nPrimary focus areas:\n\n"
         "## Current Active Projects\n- \n\n"
         "## Core Goals (This Quarter)\n1. \n2. \n3. \n\n"
         "## Working Style\n- Preferred communication: concise, direct\n\n"
         "## Recent Context (update weekly)\nCurrent focus:\n"),
        ("_context", "AI Preferences",
         "# AI Preferences\n\n"
         "## Response Style\n- Be concise\n- Cite notes in [brackets]\n- No filler phrases\n\n"
         "## Do\n- Surface connections between ideas\n- Challenge assumptions\n\n"
         "## Don't\n- Hallucinate\n- Add unsolicited warnings\n"),
        ("projects", "Project Template",
         "# Project Name\n\n**Status:** Active\n**Started:** \n\n"
         "## Goal\n\n## Key Decisions\n\n## Open Questions\n- [ ] \n\n## Lessons Learned\n"),
    ]
    for folder, title, content in starters:
        db.create_note(user_id, title, content, folder=folder)


def _bootstrap_local(user_id: str):
    """Copy template vault files for a new local user."""
    from _config import cfg
    vault_root = Path(cfg["vault"]["path"])
    user_vault = vault_root / "users" / user_id
    if user_vault.exists():
        return
    for folder in ["_context", "projects", "daily-notes", "meetings", "reflections"]:
        (user_vault / folder).mkdir(parents=True, exist_ok=True)
    for src in vault_root.rglob("*.md"):
        if "users" in src.parts:
            continue
        dst = user_vault / src.relative_to(vault_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))

