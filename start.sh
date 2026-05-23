#!/usr/bin/env bash
# ── Forever AI — Start Script ───────────────────────────────────────────
# Usage:
#   ./start.sh            → web UI at http://127.0.0.1:5050
#   ./start.sh cli        → terminal chat
#   ./start.sh reindex    → reindex vault then exit
#   ./start.sh watch      → reindex + watch for vault changes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

# ── Activate or create virtualenv ─────────────────────────────────────────

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"

# ── Install dependencies if needed ────────────────────────────────────────

pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ── Dispatch ─────────────────────────────────────────────────────────────

MODE="${1:-web}"

PYTHON="$VENV/bin/python"

case "$MODE" in
  web)
    echo "Starting Forever AI web UI → http://127.0.0.1:5050"
    "$PYTHON" "$SCRIPT_DIR/src/web_app.py"
    ;;
  cli)
    "$PYTHON" "$SCRIPT_DIR/src/chat.py"
    ;;
  reindex)
    "$PYTHON" "$SCRIPT_DIR/scripts/reindex.py"
    ;;
  watch)
    "$PYTHON" "$SCRIPT_DIR/scripts/reindex.py" --watch
    ;;
  *)
    echo "Usage: $0 [web|cli|reindex|watch]"
    exit 1
    ;;
esac
