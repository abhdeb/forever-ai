"""
_config.py — Central config loader.

Reads config.yaml, merges .env overrides, and exposes `cfg` dict.
Import this from every other module:

    from _config import cfg
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env from the project root (one level up from src/)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env", override=False)

_config_path = _ROOT / "config.yaml"
with open(_config_path) as _f:
    cfg: dict = yaml.safe_load(_f)

# Allow VAULT_PATH env var to override config
if os.environ.get("VAULT_PATH"):
    cfg["vault"]["path"] = os.environ["VAULT_PATH"]

# Resolve vault path relative to project root if not absolute
vault_p = Path(cfg["vault"]["path"])
if not vault_p.is_absolute():
    cfg["vault"]["path"] = str((_ROOT / vault_p).resolve())
