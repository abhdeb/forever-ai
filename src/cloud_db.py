"""
cloud_db.py — PostgreSQL + pgvector data layer (Supabase).

Handles: users, notes, and vector chunks.
Falls back gracefully when DATABASE_URL is not set (local mode).
"""

from __future__ import annotations

import os
import time
import uuid
import hashlib
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

# ── Connection pool ───────────────────────────────────────────────────────

_pool: Optional[ThreadedConnectionPool] = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise EnvironmentError(
                "DATABASE_URL is not set. Add it to your .env file.\n"
                "Get it from: Supabase → Settings → Database → Connection string (URI)"
            )
        _pool = ThreadedConnectionPool(1, 10, dsn=db_url)
    return _pool


@contextmanager
def _conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Schema bootstrap ──────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist. Safe to call on every startup."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    email         TEXT UNIQUE NOT NULL,
                    name          TEXT DEFAULT '',
                    password_hash BYTEA,
                    created_at    TIMESTAMP DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title      TEXT NOT NULL DEFAULT 'Untitled',
                    content    TEXT NOT NULL DEFAULT '',
                    folder     TEXT NOT NULL DEFAULT 'general',
                    tags       TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS vault_chunks (
                    id          TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    note_id     TEXT REFERENCES notes(id) ON DELETE CASCADE,
                    source      TEXT NOT NULL,
                    title       TEXT DEFAULT '',
                    tags        TEXT DEFAULT '',
                    content     TEXT NOT NULL,
                    embedding   vector(384),
                    chunk_index INT DEFAULT 0,
                    indexed_at  BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS vault_chunks_user_idx
                ON vault_chunks (user_id)
            """)

            # Vector index (only created if table has rows; ignore error if not ready)
            try:
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS vault_chunks_vec_idx
                    ON vault_chunks USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 50)
                """)
            except Exception:
                conn.rollback()


# ── Users ─────────────────────────────────────────────────────────────────

def register_user(email: str, name: str, password: str) -> Optional[Dict]:
    """Hash password and insert user. Returns None if email already taken."""
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        with _conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO users (email, name, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, email, name, created_at
                    """,
                    (email.lower(), name, hashed),
                )
                return dict(cur.fetchone())
    except psycopg2.errors.UniqueViolation:
        return None


def verify_user(email: str, password: str) -> Optional[Dict]:
    """Return user dict if credentials are valid, else None."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, name, password_hash FROM users WHERE email = %s",
                (email.lower(),),
            )
            row = cur.fetchone()
    if not row or not row["password_hash"]:
        return None
    if bcrypt.checkpw(password.encode(), bytes(row["password_hash"])):
        return {"id": row["id"], "email": row["email"], "name": row["name"]}
    return None


def get_user(user_id: str) -> Optional[Dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, email, name FROM users WHERE id = %s", (user_id,)
            )
            row = cur.fetchone()
    return dict(row) if row else None


# ── Notes ─────────────────────────────────────────────────────────────────

def create_note(user_id: str, title: str, content: str,
                folder: str = "general", tags: str = "") -> Dict:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO notes (user_id, title, content, folder, tags)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (user_id, title, content, folder, tags),
            )
            return dict(cur.fetchone())


def update_note(note_id: str, user_id: str, title: str = None,
                content: str = None, folder: str = None,
                tags: str = None) -> Optional[Dict]:
    fields, values = [], []
    if title   is not None: fields.append("title = %s");   values.append(title)
    if content is not None: fields.append("content = %s"); values.append(content)
    if folder  is not None: fields.append("folder = %s");  values.append(folder)
    if tags    is not None: fields.append("tags = %s");    values.append(tags)
    if not fields:
        return get_note(note_id, user_id)
    fields.append("updated_at = NOW()")
    values.extend([note_id, user_id])
    sql = f"UPDATE notes SET {', '.join(fields)} WHERE id = %s AND user_id = %s RETURNING *"
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, values)
            row = cur.fetchone()
    return dict(row) if row else None


def delete_note(note_id: str, user_id: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM notes WHERE id = %s AND user_id = %s", (note_id, user_id)
            )
            return cur.rowcount > 0


def list_notes(user_id: str, folder: str = None) -> List[Dict]:
    sql = "SELECT id, title, folder, tags, updated_at FROM notes WHERE user_id = %s"
    params = [user_id]
    if folder:
        sql += " AND folder = %s"
        params.append(folder)
    sql += " ORDER BY folder, updated_at DESC"
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def get_note(note_id: str, user_id: str) -> Optional[Dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM notes WHERE id = %s AND user_id = %s",
                (note_id, user_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def list_folders(user_id: str) -> List[str]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT folder FROM notes WHERE user_id = %s ORDER BY folder",
                (user_id,),
            )
            return [r[0] for r in cur.fetchall()]


# ── Vector chunks ─────────────────────────────────────────────────────────

def _vec_str(embedding: list) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"


def upsert_chunks(chunks: List[Dict]):
    """
    Each chunk dict: id, user_id, note_id, source, title, tags,
                     content, embedding (list[float]), chunk_index
    """
    if not chunks:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO vault_chunks
                    (id, user_id, note_id, source, title, tags, content, embedding, chunk_index, indexed_at)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    content     = EXCLUDED.content,
                    embedding   = EXCLUDED.embedding,
                    title       = EXCLUDED.title,
                    tags        = EXCLUDED.tags,
                    indexed_at  = EXCLUDED.indexed_at
                """,
                [
                    (
                        c["id"], c["user_id"], c.get("note_id"),
                        c["source"], c["title"], c.get("tags", ""),
                        c["content"], _vec_str(c["embedding"]),
                        c.get("chunk_index", 0), int(time.time()),
                    )
                    for c in chunks
                ],
                template="(%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)",
            )


def delete_chunks_for_note(note_id: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vault_chunks WHERE note_id = %s", (note_id,))


def delete_chunks_for_user(user_id: str):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vault_chunks WHERE user_id = %s", (user_id,))


def search_chunks(user_id: str, embedding: list,
                  top_k: int = 6, min_score: float = 0.30) -> List[Dict]:
    vec = _vec_str(embedding)
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, note_id, source, title, tags, content, chunk_index,
                       1 - (embedding <=> %s::vector) AS score
                FROM vault_chunks
                WHERE user_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec, user_id, vec, top_k),
            )
            return [dict(r) for r in cur.fetchall() if r["score"] >= min_score]


def get_context_notes(user_id: str) -> List[Dict]:
    """Return notes in the _context folder (always-include content)."""
    return list_notes(user_id, folder="_context")
