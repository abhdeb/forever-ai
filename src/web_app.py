"""
web_app.py — Flask web app for Forever AI.

Run (local):  python src/web_app.py
Run (cloud):  gunicorn wsgi:app
Then open:    http://127.0.0.1:5050
"""

from __future__ import annotations

import os
import sys
import secrets
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, request, jsonify, render_template, abort, session
from flask_cors import CORS

from _config import cfg
from agent import Agent
from auth import auth_bp, init_oauth, login_required

# ── App factory ───────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent.parent / "templates"),
    static_folder=str(Path(__file__).parent.parent / "static"),
)

app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)

CORS(app, resources={r"/api/*": {"origins": "*"}})

app.register_blueprint(auth_bp)
init_oauth(app)

_CLOUD = bool(os.environ.get("DATABASE_URL"))

# ── Per-user agent registry ───────────────────────────────────────────────

_agents: dict = {}


def _get_agent(user_id: str) -> Agent:
    if user_id not in _agents:
        _agents[user_id] = Agent(user_id=user_id)
    return _agents[user_id]


def _user_vault_path(user_id: str) -> str:
    return str(Path(cfg["vault"]["path"]) / "users" / user_id)


def _user_collection(user_id: str) -> str:
    return f"fa_u_{user_id[:20]}"


# ── Pages ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html", user=session)


# ── Chat API ──────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data    = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        abort(400, "message is required")
    agent = _get_agent(session["user_id"])
    try:
        reply = agent.chat(message)
    except EnvironmentError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"reply": reply})


@app.route("/api/reset", methods=["POST"])
@login_required
def api_reset():
    _get_agent(session["user_id"]).reset()
    return jsonify({"status": "ok"})


@app.route("/api/history", methods=["GET"])
@login_required
def api_history():
    return jsonify(_get_agent(session["user_id"]).history)


@app.route("/api/me", methods=["GET"])
@login_required
def api_me():
    return jsonify({
        "id":    session.get("user_id"),
        "name":  session.get("user_name"),
        "email": session.get("user_email"),
    })


# ── Search API ────────────────────────────────────────────────────────────

@app.route("/api/search", methods=["GET"])
@login_required
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        abort(400, "q parameter is required")
    k   = min(int(request.args.get("k", 5)), 20)
    uid = session["user_id"]
    if _CLOUD:
        from retriever import retrieve_cloud
        chunks = retrieve_cloud(query, uid, top_k=k)
    else:
        from retriever import retrieve
        chunks = retrieve(query, top_k=k, collection_name=_user_collection(uid))
    return jsonify([
        {"title": c.title, "source": c.source, "text": c.text,
         "score": round(c.score, 4), "tags": c.tags}
        for c in chunks
    ])


# ── Reindex API ───────────────────────────────────────────────────────────

@app.route("/api/reindex", methods=["POST"])
@login_required
def api_reindex():
    uid = session["user_id"]
    try:
        if _CLOUD:
            from indexer import reindex_all_notes
            stats = reindex_all_notes(uid)
        else:
            from indexer import reindex_vault
            stats = reindex_vault(verbose=False,
                                  vault_path=_user_vault_path(uid),
                                  collection_name=_user_collection(uid))
        return jsonify(stats)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Notes API (cloud mode) ────────────────────────────────────────────────

@app.route("/api/notes", methods=["GET"])
@login_required
def api_list_notes():
    if not _CLOUD:
        return jsonify({"error": "Notes API requires cloud mode (DATABASE_URL)"}), 400
    import cloud_db as db
    uid    = session["user_id"]
    folder = request.args.get("folder") or None
    return jsonify(db.list_notes(uid, folder=folder))


@app.route("/api/notes/folders", methods=["GET"])
@login_required
def api_list_folders():
    if not _CLOUD:
        return jsonify([])
    import cloud_db as db
    return jsonify(db.list_folders(session["user_id"]))


@app.route("/api/notes/<note_id>", methods=["GET"])
@login_required
def api_get_note(note_id):
    if not _CLOUD:
        return jsonify({"error": "Notes API requires cloud mode"}), 400
    import cloud_db as db
    note = db.get_note(note_id, session["user_id"])
    if not note:
        abort(404)
    return jsonify(note)


@app.route("/api/notes", methods=["POST"])
@login_required
def api_create_note():
    if not _CLOUD:
        return jsonify({"error": "Notes API requires cloud mode"}), 400
    import cloud_db as db
    from indexer import index_note
    data    = request.get_json(silent=True) or {}
    title   = (data.get("title") or "Untitled").strip()
    content = (data.get("content") or "").strip()
    folder  = (data.get("folder") or "general").strip()
    tags    = (data.get("tags") or "").strip()
    uid     = session["user_id"]
    note    = db.create_note(uid, title, content, folder, tags)
    index_note(note, uid)
    return jsonify(note), 201


@app.route("/api/notes/<note_id>", methods=["PUT"])
@login_required
def api_update_note(note_id):
    if not _CLOUD:
        return jsonify({"error": "Notes API requires cloud mode"}), 400
    import cloud_db as db
    from indexer import index_note
    data = request.get_json(silent=True) or {}
    uid  = session["user_id"]
    note = db.update_note(
        note_id, uid,
        title   = data.get("title"),
        content = data.get("content"),
        folder  = data.get("folder"),
        tags    = data.get("tags"),
    )
    if not note:
        abort(404)
    index_note(note, uid)
    return jsonify(note)


@app.route("/api/notes/<note_id>", methods=["DELETE"])
@login_required
def api_delete_note(note_id):
    if not _CLOUD:
        return jsonify({"error": "Notes API requires cloud mode"}), 400
    import cloud_db as db
    uid = session["user_id"]
    if not db.delete_note(note_id, uid):
        abort(404)
    try:
        db.delete_chunks_for_note(note_id)
    except Exception:
        pass
    return jsonify({"status": "deleted"})


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    host  = cfg["web"]["host"]
    port  = cfg["web"]["port"]
    debug = cfg["web"]["debug"]
    if not os.environ.get("FLASK_SECRET_KEY"):
        print("[warning] FLASK_SECRET_KEY not set — sessions won't persist across restarts.")
    if _CLOUD:
        print(f"[cloud mode] Connected to Supabase, LLM={cfg['llm']['provider']}")
    else:
        print(f"[local mode] Vault={cfg['vault']['path']}, LLM={cfg['llm']['provider']}")
    print(f"Starting Forever AI at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
