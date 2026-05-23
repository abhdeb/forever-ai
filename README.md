# Forever AI — Your AI Second Brain

A local, private, compounding AI assistant powered by your own Markdown notes.

**Stack:** Python · ChromaDB · sentence-transformers · Claude/OpenAI/Ollama · Flask


---

## How it works

```
vault/*.md  ──embed──►  ChromaDB  ──retrieve──►  Claude API  ──►  Answer
   (your notes)          (local)      (RAG)          (LLM)
```

1. You write Markdown notes in `vault/` (Obsidian-compatible)
2. The indexer embeds every note and stores vectors in ChromaDB
3. When you ask a question, the retriever fetches the most relevant chunks
4. Those chunks are injected into the Claude (or OpenAI/Ollama) prompt
5. You get a contextual answer grounded in *your* knowledge

---

## Quick Start

```bash
# 1. Copy env file and add your API key
cp .env.example .env
#    → edit .env, add ANTHROPIC_API_KEY=sk-ant-...

# 2. Fill in your Master Context (takes 5 minutes, pays off forever)
open vault/_context/master-context.md

# 3. Launch (auto-creates venv, installs deps, starts web UI)
./start.sh

# → open http://127.0.0.1:5050
```

### Other modes

```bash
./start.sh cli       # Rich terminal chat
./start.sh reindex   # Force re-embed all vault files
./start.sh watch     # Reindex + watch vault for live changes
```

---

## Directory structure

```
thinking-wiki/
├── vault/                   ← Your notes (edit these in Obsidian or any editor)
│   ├── _context/            ← Always injected into every query
│   │   ├── master-context.md   ← START HERE: fill in your goals, projects, style
│   │   └── preferences.md
│   ├── projects/            ← One note per project (use _template.md)
│   ├── daily-notes/         ← Daily logs (use _template.md)
│   ├── meetings/            ← Meeting notes
│   └── reflections/         ← Long-form thinking
├── src/
│   ├── _config.py           ← Config loader
│   ├── indexer.py           ← Vault → ChromaDB pipeline
│   ├── retriever.py         ← Semantic search + context assembly
│   ├── agent.py             ← RAG + LLM dispatch
│   ├── chat.py              ← CLI interface
│   └── web_app.py           ← Flask web app
├── scripts/
│   └── reindex.py           ← Full reindex utility
├── templates/index.html     ← Web UI
├── static/                  ← CSS + JS
├── config.yaml              ← All configuration
├── .env                     ← Your API keys (git-ignored)
└── start.sh                 ← One-command launcher
```

---

## Configuration (`config.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `vault.path` | `./vault` | Root of your Markdown notes |
| `embeddings.provider` | `local` | `local` (private) or `openai` |
| `llm.provider` | `claude` | `claude`, `openai`, or `ollama` |
| `llm.claude_model` | `claude-opus-4-5` | Any Anthropic model |
| `retrieval.top_k` | `6` | Chunks retrieved per query |
| `retrieval.min_score` | `0.30` | Drop chunks below this similarity |
| `web.port` | `5050` | Web UI port |

---

## The "compounding" principle

Every note you add makes the AI smarter *for you*:

- **Projects:** Document the *why* behind decisions. Six months later, ask "why did I choose X?" and get a real answer.
- **Daily notes:** Brain-dump freely. The retriever will surface relevant past thoughts automatically.
- **Master context:** Keep it updated weekly. This is the AI's orientation — it reads it on every query.

---

## Switching to Ollama (fully offline)

```yaml
# config.yaml
llm:
  provider: "ollama"
  ollama_model: "llama3"
```

No API key needed. Install Ollama and `ollama pull llama3`.

---

## Adding to Obsidian

Point Obsidian's vault to `thinking-wiki/vault/`. Everything is plain Markdown —
tags, links, and graph view all work normally. The AI reads the same files.
