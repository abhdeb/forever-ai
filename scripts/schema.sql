-- =============================================================
-- Forever AI — Supabase schema setup
-- Run this ONCE in the Supabase SQL editor (supabase.com → SQL editor)
-- =============================================================

-- 1. Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Users table
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT DEFAULT '',
    password_hash BYTEA,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- 3. Notes table (vault content stored in the DB)
CREATE TABLE IF NOT EXISTS notes (
    id         TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT 'Untitled',
    content    TEXT NOT NULL DEFAULT '',
    folder     TEXT NOT NULL DEFAULT 'general',
    tags       TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS notes_user_idx ON notes (user_id);
CREATE INDEX IF NOT EXISTS notes_folder_idx ON notes (user_id, folder);

-- 4. Vector chunks table (384-dim, all-MiniLM-L6-v2)
CREATE TABLE IF NOT EXISTS vault_chunks (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_id     TEXT REFERENCES notes(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    title       TEXT DEFAULT '',
    tags        TEXT DEFAULT '',
    content     TEXT NOT NULL,
    embedding   vector(384),
    chunk_index INT  DEFAULT 0,
    indexed_at  BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE INDEX IF NOT EXISTS vault_chunks_user_idx ON vault_chunks (user_id);

-- Vector cosine-similarity index (created after you have some data)
-- Run manually once you've indexed at least a few notes:
--
-- CREATE INDEX vault_chunks_vec_idx
--   ON vault_chunks USING ivfflat (embedding vector_cosine_ops)
--   WITH (lists = 50);

-- 5. Disable Row Level Security (internal app — server-side auth)
ALTER TABLE users        DISABLE ROW LEVEL SECURITY;
ALTER TABLE notes        DISABLE ROW LEVEL SECURITY;
ALTER TABLE vault_chunks DISABLE ROW LEVEL SECURITY;
