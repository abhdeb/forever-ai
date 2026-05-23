"""wsgi.py — Gunicorn entry point for Render.com / cloud hosting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from web_app import app  # noqa: F401
