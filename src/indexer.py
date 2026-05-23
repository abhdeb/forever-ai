"""
indexer.py — Embedding + storage pipeline.

Cloud mode  (DATABASE_URL set): embeds notes → pgvector (Supabase)
Local mode  (no DATABASE_URL):  embeds .md files → ChromaDB
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import List, Optional

from _config import cfg

# ── Shared: fastembed embedder (ONNX, no PyTorch, ~150MB RAM) ───────────────

_st_model = None


def _get_model():
    global _st_model
    if _st_model is None:
        from fastembed import TextEmbedding
        _st_model = TextEmbedding(model_name=cfg["embeddings"]["local_model"])
    return _st_model


def embed_text(text: str) -> List[float]:
    model = _get_model()
    result = list(model.embed([text]))
    return result[0].tolist()


# ── Shared: text splitter ─────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    if len(text) <= chunk_size:
        return [text.strip()] if text.strip() else []
    chunks, start = [], 0
    while start < len(text):
        chunk = text[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def _chunk_id(source: str, index: int, content_hash: str) -> str:
    raw = f"{source}::{index}::{content_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Cloud mode ────────────────────────────────────────────────────────────

def index_note(note: dict, user_id: str):
    """
    Embed a single note (from PostgreSQL) and upsert chunks into pgvector.
    note: dict with keys id, title, content, folder, tags
    """
    import cloud_db as db
    content = (note.get("content") or "").strip()
    if not content:
        db.delete_chunks_for_note(note["id"])
        return

    title   = note.get("title", "Untitled")
    folder  = note.get("folder", "general")
    tags    = note.get("tags", "")
    source  = f"{folder}/{title}"

    chunk_size = cfg["retrieval"]["chunk_size"]
    overlap    = cfg["retrieval"]["chunk_overlap"]
    texts      = _split_text(content, chunk_size, overlap)
    if not texts:
        return

    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    embeddings   = _get_model().encode(texts)

    chunks = []
    for i, (text, emb) in enumerate(zip(texts, embeddings)):
        chunks.append({
            "id":          _chunk_id(source, i, content_hash),
            "user_id":     user_id,
            "note_id":     note["id"],
            "source":      source,
            "title":       title,
            "tags":        tags,
            "content":     text,
            "embedding":   emb.tolist(),
            "chunk_index": i,
        })

    db.delete_chunks_for_note(note["id"])
    db.upsert_chunks(chunks)


def reindex_all_notes(user_id: str) -> dict:
    """Reindex every note for a user. Returns stats dict."""
    import cloud_db as db
    notes  = db.list_notes(user_id)
    stats  = {"notes": 0, "chunks": 0, "errors": 0}
    for note_meta in notes:
        note = db.get_note(note_meta["id"], user_id)
        if not note:
            continue
        try:
            content = note.get("content", "").strip()
            chunk_size = cfg["retrieval"]["chunk_size"]
            overlap    = cfg["retrieval"]["chunk_overlap"]
            n = len(_split_text(content, chunk_size, overlap))
            index_note(note, user_id)
            stats["notes"]  += 1
            stats["chunks"] += n
        except Exception:
            stats["errors"] += 1
    return stats


# ── Local mode (ChromaDB — unchanged from original) ───────────────────────

def _get_collection(collection_name: str = None):
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    persist_dir = str(Path(__file__).parent.parent / cfg["chroma"]["persist_directory"])
    name = collection_name or cfg["chroma"]["collection_name"]
    client = chromadb.PersistentClient(path=persist_dir)
    ef = SentenceTransformerEmbeddingFunction(model_name=cfg["embeddings"]["local_model"])
    return client.get_or_create_collection(name=name, embedding_function=ef,
                                           metadata={"hnsw:space": "cosine"})


def index_file(file_path: Path, collection, vault_root: Path = None) -> int:
    import frontmatter
    try:
        post = frontmatter.load(str(file_path))
    except Exception:
        return 0
    body = post.content.strip()
    if not body:
        return 0
    meta = post.metadata
    vault_root = (vault_root or Path(cfg["vault"]["path"])).resolve()
    relative   = str(file_path.resolve().relative_to(vault_root))
    chunk_size = cfg["retrieval"]["chunk_size"]
    overlap    = cfg["retrieval"]["chunk_overlap"]
    texts      = _split_text(body, chunk_size, overlap)
    content_hash = hashlib.md5(body.encode()).hexdigest()[:8]
    ids, documents, metadatas = [], [], []
    for i, chunk in enumerate(texts):
        cid = _chunk_id(relative, i, content_hash)
        ids.append(cid)
        documents.append(chunk)
        metadatas.append({
            "source": relative,
            "title":  meta.get("title", file_path.stem),
            "tags":   ",".join(meta.get("tags", [])) if isinstance(meta.get("tags"), list)
                      else str(meta.get("tags", "")),
            "chunk_index":  i,
            "total_chunks": len(texts),
            "indexed_at":   int(time.time()),
        })
    existing = collection.get(where={"source": relative})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(texts)


def reindex_vault(verbose: bool = True, vault_path: str = None,
                  collection_name: str = None) -> dict:
    vp         = Path(vault_path).resolve() if vault_path else Path(cfg["vault"]["path"]).resolve()
    collection = _get_collection(collection_name=collection_name)
    md_files   = sorted(vp.rglob("*.md"))
    stats      = {"files": 0, "chunks": 0, "errors": 0}
    for fp in md_files:
        try:
            n = index_file(fp, collection, vault_root=vp)
            stats["files"] += 1; stats["chunks"] += n
            if verbose:
                print(f"  ✓  {fp.relative_to(vp)}  ({n} chunks)")
        except Exception as exc:
            stats["errors"] += 1
            if verbose:
                print(f"  ✗  {fp.relative_to(vp)}: {exc}")
    _prune_deleted_files(collection, vp, md_files)
    return stats


def _prune_deleted_files(collection, vault_root: Path, current_files: list):  # noqa: E501
    all_meta    = collection.get(include=["metadatas"])
    seen        = {str(fp.resolve().relative_to(vault_root)) for fp in current_files}
    to_delete   = [cid for cid, meta in zip(all_meta["ids"], all_meta["metadatas"])
                   if meta.get("source") not in seen]
    if to_delete:
        collection.delete(ids=to_delete)


def start_watcher():
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    collection = _get_collection()
    vault_path = Path(cfg["vault"]["path"]).resolve()
    class _H(FileSystemEventHandler):
        def _handle(self, path):
            p = Path(path)
            if p.suffix != ".md": return
            if p.exists():
                index_file(p, collection)
            else:
                rel = str(p.resolve().relative_to(vault_path))
                ex  = collection.get(where={"source": rel})
                if ex["ids"]: collection.delete(ids=ex["ids"])
        def on_modified(self, e):
            if not e.is_directory: self._handle(e.src_path)
        def on_created(self, e):
            if not e.is_directory: self._handle(e.src_path)
        def on_deleted(self, e):
            if not e.is_directory: self._handle(e.src_path)
    obs = Observer()
    obs.schedule(_H(), str(vault_path), recursive=True)
    obs.start()
    print(f"[watcher] Watching {vault_path} …  (Ctrl-C to stop)")
    try:
        import time as _t
        while True: _t.sleep(1)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()

import frontmatter          # python-frontmatter
import chromadb
from chromadb.utils.embedding_functions import (
    SentenceTransformerEmbeddingFunction,
    OpenAIEmbeddingFunction,
)

from _config import cfg


# ── Embedding function factory ────────────────────────────────────────────

def _build_embedding_fn():
    provider = cfg["embeddings"]["provider"]
    if provider == "local":
        return SentenceTransformerEmbeddingFunction(
            model_name=cfg["embeddings"]["local_model"]
        )
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY is not set.")
        return OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name=cfg["embeddings"]["openai_model"],
        )
    else:
        raise ValueError(f"Unknown embeddings provider: {provider!r}")


# ── ChromaDB client ──────────────────────────────────────────────────────

def _get_collection(collection_name: str = None):
    """Return a ChromaDB collection. Pass collection_name to get a user-specific one."""
    persist_dir = str(
        Path(__file__).parent.parent / cfg["chroma"]["persist_directory"]
    )
    name = collection_name or cfg["chroma"]["collection_name"]
    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_or_create_collection(
        name=name,
        embedding_function=_build_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )
    return collection


# ── Text splitting ────────────────────────────────────────────────────────

def _split_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split *text* into overlapping chunks of roughly *chunk_size* chars."""
    if len(text) <= chunk_size:
        return [text.strip()] if text.strip() else []

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ── ID generation ─────────────────────────────────────────────────────────

def _chunk_id(file_path: str, chunk_index: int, content_hash: str) -> str:
    """Stable, deterministic ID for a chunk."""
    raw = f"{file_path}::{chunk_index}::{content_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Single-file indexing ──────────────────────────────────────────────────

def index_file(file_path: Path, collection, vault_root: Path = None) -> int:
    """
    Parse *file_path*, split into chunks, and upsert into *collection*.
    Returns the number of chunks upserted.
    """
    try:
        post = frontmatter.load(str(file_path))
    except Exception:
        return 0

    body: str = post.content.strip()
    if not body:
        return 0

    meta: dict = post.metadata  # YAML frontmatter as dict
    vault_root = (vault_root or Path(cfg["vault"]["path"])).resolve()
    relative = str(file_path.resolve().relative_to(vault_root))

    chunk_size = cfg["retrieval"]["chunk_size"]
    overlap    = cfg["retrieval"]["chunk_overlap"]
    chunks     = _split_text(body, chunk_size, overlap)

    # Build metadata for each chunk
    ids, documents, metadatas = [], [], []
    content_hash = hashlib.md5(body.encode()).hexdigest()[:8]

    for i, chunk in enumerate(chunks):
        cid = _chunk_id(relative, i, content_hash)
        ids.append(cid)
        documents.append(chunk)
        metadatas.append(
            {
                "source": relative,
                "title": meta.get("title", file_path.stem),
                "tags":  ",".join(meta.get("tags", [])) if isinstance(meta.get("tags"), list) else str(meta.get("tags", "")),
                "chunk_index": i,
                "total_chunks": len(chunks),
                "indexed_at": int(time.time()),
            }
        )

    # Delete stale chunks for this file (in case chunk count changed)
    existing = collection.get(where={"source": relative})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    return len(chunks)


# ── Bulk reindex ──────────────────────────────────────────────────────────

def reindex_vault(verbose: bool = True, vault_path: str = None, collection_name: str = None) -> dict:
    """Reindex every .md file in the vault. Returns a stats dict."""
    vp = Path(vault_path).resolve() if vault_path else Path(cfg["vault"]["path"]).resolve()
    if not vp.exists():
        raise FileNotFoundError(f"Vault path not found: {vp}")

    collection = _get_collection(collection_name=collection_name)
    md_files   = sorted(vp.rglob("*.md"))

    stats = {"files": 0, "chunks": 0, "errors": 0}
    for fp in md_files:
        try:
            n = index_file(fp, collection, vault_root=vp)
            stats["files"] += 1
            stats["chunks"] += n
            if verbose:
                print(f"  ✓  {fp.relative_to(vp)}  ({n} chunks)")
        except Exception as exc:
            stats["errors"] += 1
            if verbose:
                print(f"  ✗  {fp.relative_to(vp)}: {exc}")

    _prune_deleted_files(collection, vp, md_files)
    return stats


def _prune_deleted_files(collection, vault_root: Path, current_files: list):  # noqa: E501
    """Remove chunks whose source file no longer exists in the vault."""
    all_meta = collection.get(include=["metadatas"])
    seen_sources = {str(fp.resolve().relative_to(vault_root)) for fp in current_files}
    to_delete = [
        cid
        for cid, meta in zip(all_meta["ids"], all_meta["metadatas"])
        if meta.get("source") not in seen_sources
    ]
    if to_delete:
        collection.delete(ids=to_delete)


# ── Live watcher ──────────────────────────────────────────────────────────

def start_watcher():
    """Block and watch the vault folder; re-index on every .md change."""
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    collection = _get_collection()
    vault_path = Path(cfg["vault"]["path"]).resolve()

    class _Handler(FileSystemEventHandler):
        def _handle(self, path: str):
            p = Path(path)
            if p.suffix != ".md":
                return
            if p.exists():
                n = index_file(p, collection)
                print(f"[watcher] re-indexed {p.name} ({n} chunks)")
            else:
                # File deleted — prune its chunks
                relative = str(p.resolve().relative_to(vault_path))
                existing = collection.get(where={"source": relative})
                if existing["ids"]:
                    collection.delete(ids=existing["ids"])
                print(f"[watcher] removed chunks for deleted {p.name}")

        def on_modified(self, event):
            if not event.is_directory:
                self._handle(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                self._handle(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                self._handle(event.src_path)

    observer = Observer()
    observer.schedule(_Handler(), str(vault_path), recursive=True)
    observer.start()
    print(f"[watcher] Watching {vault_path} for changes …  (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
