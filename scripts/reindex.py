#!/usr/bin/env python3
"""
scripts/reindex.py — Full vault reindex.

Usage:
    python scripts/reindex.py [--watch]

  --watch   After initial reindex, stay running and watch for changes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from indexer import reindex_vault, start_watcher

console = Console()

def main():
    parser = argparse.ArgumentParser(description="Reindex the Forever AI vault.")
    parser.add_argument("--watch", action="store_true",
                        help="After reindex, watch for file changes and re-embed automatically.")
    args = parser.parse_args()

    console.print("[bold cyan]Forever AI — Vault Reindex[/bold cyan]")
    console.print()

    with console.status("[cyan]Embedding vault files…[/cyan]"):
        stats = reindex_vault(verbose=False)

    console.print(f"[green]✓ Done:[/green] {stats['files']} files, "
                  f"{stats['chunks']} chunks, {stats['errors']} errors.")

    if args.watch:
        console.print()
        console.print("[dim]Watching vault for changes…[/dim]")
        start_watcher()

if __name__ == "__main__":
    main()
