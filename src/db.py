"""
db.py — SQLite user store.

Stores Google-authenticated users: id (Google sub), email, name, picture.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent / "data" / "users.db"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         TEXT PRIMARY KEY,          -- Google sub
                email      TEXT UNIQUE NOT NULL,
                name       TEXT    DEFAULT '',
                picture    TEXT    DEFAULT '',
                created_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def upsert_user(sub: str, email: str, name: str, picture: str) -> dict:
    """Insert or update a user record. Returns the stored row as a dict."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, name, picture)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                email   = excluded.email,
                name    = excluded.name,
                picture = excluded.picture
            """,
            (sub, email, name, picture),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (sub,)).fetchone()
        return dict(row)


def get_user(sub: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (sub,)).fetchone()
        return dict(row) if row else None
