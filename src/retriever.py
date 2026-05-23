"""
retriever.py — Semantic search over your vault.

Cloud mode  (DATABASE_URL set): queries pgvector (Supabase)
Local mode  (no DATABASE_URL):  queries ChromaDB
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from _config import cfg


# ── Public data structure ─────────────────────────────────────────────────

class Chunk:
    """A retrieved vault chunk with its similarity score and metadata."""
    def __init__(self, text: str, source: str, title: str, score: float, tags: str = ""):
        self.text   = text
        self.source = source
        self.title  = title
        self.score  = score
        self.tags   = tags

    def __repr__(self):
        return f"<Chunk source={self.source!r} score={self.score:.3f}>"

    def to_context_block(self) -> str:
        header = f"[Note: {self.title}]  (source: {self.source}, relevance: {self.score:.2f})"
        return f"{header}\n{self.text}"


# ── Cloud mode ────────────────────────────────────────────────────────────

def retrieve_cloud(query: str, user_id: str,
                   top_k: Optional[int] = None,
                   min_score: Optional[float] = None) -> List[Chunk]:
    from indexer import embed_text
    import cloud_db as db
    k     = top_k     if top_k     is not None else cfg["retrieval"]["top_k"]
    floor = min_score if min_score is not None else cfg["retrieval"]["min_score"]
    emb   = embed_text(query)
    rows  = db.search_chunks(user_id, emb, top_k=k, min_score=floor)
    return [
        Chunk(text=r["content"], source=r["source"],
              title=r.get("title", "Untitled"),
              score=float(r["score"]), tags=r.get("tags", ""))
        for r in rows
    ]


def load_always_include_cloud(user_id: str) -> str:
    import cloud_db as db
    context_notes = db.get_context_notes(user_id)
    sections = []
    for note in context_notes:
        full = db.get_note(note["id"], user_id)
        if full and full.get("content", "").strip():
            sections.append(f"[Always-Context: {note['title']}]\n{full['content'].strip()}")
    return "\n\n---\n\n".join(sections)


def build_context_cloud(query: str, user_id: str) -> str:
    parts: List[str] = []
    always_text = load_always_include_cloud(user_id)
    if always_text:
        parts.append("=== YOUR PERSISTENT CONTEXT (always loaded) ===\n" + always_text)
    chunks = retrieve_cloud(query, user_id)
    if chunks:
        retrieved = "\n\n---\n\n".join(c.to_context_block() for c in chunks)
        parts.append("=== RELEVANT NOTES FROM YOUR VAULT ===\n" + retrieved)
    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(parts) if parts else ""


# ── Local mode (ChromaDB) ─────────────────────────────────────────────────

def load_always_include(vault_path: str = None) -> str:
    vault       = Path(vault_path) if vault_path else Path(cfg["vault"]["path"])
    always_dirs = cfg["vault"].get("always_include", [])
    sections    = []
    for dir_name in always_dirs:
        folder = vault / dir_name
        if not folder.exists():
            continue
        for md_file in sorted(folder.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8").strip()
                if text:
                    sections.append(f"[Always-Context: {md_file.name}]\n{text}")
            except Exception:
                pass
    return "\n\n---\n\n".join(sections)


def retrieve(query: str, top_k: int = None, min_score: float = None,
             collection_name: str = None) -> List[Chunk]:
    from indexer import _get_collection
    k     = top_k     if top_k     is not None else cfg["retrieval"]["top_k"]
    floor = min_score if min_score is not None else cfg["retrieval"]["min_score"]
    collection = _get_collection(collection_name=collection_name)
    count = collection.count()
    if count == 0:
        return []
    results = collection.query(
        query_texts=[query],
        n_results=min(k, count),
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    for doc, meta, dist in zip(results["documents"][0],
                                results["metadatas"][0],
                                results["distances"][0]):
        score = max(0.0, 1.0 - dist)
        if score < floor:
            continue
        chunks.append(Chunk(
            text=doc, source=meta.get("source", "unknown"),
            title=meta.get("title", "Untitled"),
            score=score, tags=meta.get("tags", ""),
        ))
    return chunks


def build_context(query: str, vault_path: str = None,
                  collection_name: str = None) -> str:
    parts = []
    always_text = load_always_include(vault_path=vault_path)
    if always_text:
        parts.append("=== YOUR PERSISTENT CONTEXT (always loaded) ===\n" + always_text)
    chunks = retrieve(query, collection_name=collection_name)
    if chunks:
        retrieved = "\n\n---\n\n".join(c.to_context_block() for c in chunks)
        parts.append("=== RELEVANT NOTES FROM YOUR VAULT ===\n" + retrieved)
    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(parts) if parts else ""



# ── Public data structure ─────────────────────────────────────────────────

class Chunk:
    """A retrieved vault chunk with its similarity score and metadata."""
    def __init__(self, text: str, source: str, title: str, score: float, tags: str = ""):
        self.text   = text
        self.source = source
        self.title  = title
        self.score  = score
        self.tags   = tags

    def __repr__(self):
        return f"<Chunk source={self.source!r} score={self.score:.3f}>"

    def to_context_block(self) -> str:
        """Format chunk as a labelled block for injection into an LLM prompt."""
        header = f"[Note: {self.title}]  (file: {self.source}, relevance: {self.score:.2f})"
        return f"{header}\n{self.text}"


# ── Always-include loader (master context) ────────────────────────────────

def load_always_include(vault_path: str = None) -> str:
    """
    Return the raw text of every file inside vault/_context/ (or whatever
    directories are listed under vault.always_include in config.yaml).
    These are prepended to every query verbatim.
    """
    vault = Path(vault_path) if vault_path else Path(cfg["vault"]["path"])
    always_dirs: List[str] = cfg["vault"].get("always_include", [])
    sections: List[str] = []

    for dir_name in always_dirs:
        folder = vault / dir_name
        if not folder.exists():
            continue
        for md_file in sorted(folder.rglob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8").strip()
                if text:
                    sections.append(
                        f"[Always-Context: {md_file.name}]\n{text}"
                    )
            except Exception:
                pass

    return "\n\n---\n\n".join(sections)


# ── Core retrieval ────────────────────────────────────────────────────────

def retrieve(query: str, top_k: int = None, min_score: float = None, collection_name: str = None) -> List[Chunk]:
    """
    Embed *query*, search ChromaDB, and return a ranked list of Chunk objects.
    """
    k     = top_k    if top_k    is not None else cfg["retrieval"]["top_k"]
    floor = min_score if min_score is not None else cfg["retrieval"]["min_score"]

    collection = _get_collection(collection_name=collection_name)

    # If collection is empty, return gracefully
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(k, count),
        include=["documents", "metadatas", "distances"],
    )

    chunks: List[Chunk] = []
    docs      = results["documents"][0]
    metas     = results["metadatas"][0]
    distances = results["distances"][0]

    for doc, meta, dist in zip(docs, metas, distances):
        # ChromaDB cosine distance → similarity: score = 1 - distance
        score = max(0.0, 1.0 - dist)
        if score < floor:
            continue
        chunks.append(
            Chunk(
                text   = doc,
                source = meta.get("source", "unknown"),
                title  = meta.get("title", "Untitled"),
                score  = score,
                tags   = meta.get("tags", ""),
            )
        )

    return chunks


# ── Context assembler ─────────────────────────────────────────────────────

def build_context(query: str, vault_path: str = None, collection_name: str = None) -> str:
    """
    Assemble the full context string to inject into the LLM prompt:

      1. Always-include notes (master context, preferences, etc.)
      2. Top-K retrieved chunks relevant to *query*
    """
    parts: List[str] = []

    always_text = load_always_include(vault_path=vault_path)
    if always_text:
        parts.append("=== YOUR PERSISTENT CONTEXT (always loaded) ===\n" + always_text)

    chunks = retrieve(query, collection_name=collection_name)
    if chunks:
        retrieved_text = "\n\n---\n\n".join(c.to_context_block() for c in chunks)
        parts.append("=== RELEVANT NOTES FROM YOUR VAULT ===\n" + retrieved_text)

    return "\n\n" + ("\n\n" + "="*60 + "\n\n").join(parts) if parts else ""
