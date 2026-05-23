"""
chat.py — Rich terminal chat interface for Forever AI.

Run:  python src/chat.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly: python src/chat.py
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text
from rich import print as rprint

from agent import Agent
from indexer import reindex_vault
from retriever import retrieve

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────

def _print_banner():
    console.print()
    console.print(Panel(
        "[bold cyan]Forever AI[/bold cyan]  —  Your AI Second Brain\n"
        "[dim]Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit[/dim]",
        expand=False,
        border_style="cyan",
    ))
    console.print()


def _print_help():
    console.print(Panel(
        "[bold]Commands[/bold]\n\n"
        "  [cyan]/help[/cyan]           Show this message\n"
        "  [cyan]/reset[/cyan]          Clear conversation history (vault stays intact)\n"
        "  [cyan]/reindex[/cyan]        Re-embed all vault files into ChromaDB\n"
        "  [cyan]/search <query>[/cyan] Search vault without calling the LLM\n"
        "  [cyan]/quit[/cyan]  [cyan]/exit[/cyan]   Exit the chat\n"
        "\n[dim]Everything else is sent to your AI thinking partner.[/dim]",
        border_style="dim",
        expand=False,
    ))


def _handle_search(query: str):
    if not query.strip():
        console.print("[yellow]Usage: /search <query>[/yellow]")
        return
    with console.status("[cyan]Searching vault…[/cyan]"):
        results = retrieve(query, top_k=5)
    if not results:
        console.print("[yellow]No matching notes found.[/yellow]")
        return
    console.print()
    for i, chunk in enumerate(results, 1):
        console.print(Panel(
            chunk.text,
            title=f"[bold]{i}. {chunk.title}[/bold]  [dim]{chunk.source}[/dim]  "
                  f"[green]score {chunk.score:.2f}[/green]",
            border_style="green",
        ))


def _handle_reindex():
    with console.status("[cyan]Reindexing vault…[/cyan]"):
        stats = reindex_vault(verbose=False)
    console.print(
        f"[green]✓ Reindex complete:[/green] "
        f"{stats['files']} files, {stats['chunks']} chunks, {stats['errors']} errors."
    )


# ── Main chat loop ────────────────────────────────────────────────────────

def main():
    _print_banner()

    agent = Agent()

    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        # ── Built-in commands ────────────────────────────────────────────
        if user_input.lower() in ("/quit", "/exit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        if user_input.lower() == "/help":
            _print_help()
            continue

        if user_input.lower() == "/reset":
            agent.reset()
            console.print("[yellow]Conversation history cleared.[/yellow]")
            continue

        if user_input.lower() == "/reindex":
            _handle_reindex()
            continue

        if user_input.lower().startswith("/search "):
            _handle_search(user_input[8:])
            continue

        if user_input.startswith("/"):
            console.print(f"[red]Unknown command:[/red] {user_input}  (type /help)")
            continue

        # ── LLM query ────────────────────────────────────────────────────
        console.print()
        with console.status("[cyan]Thinking…[/cyan]"):
            try:
                reply = agent.chat(user_input)
            except EnvironmentError as e:
                console.print(f"[red]Configuration error:[/red] {e}")
                continue
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
                continue

        console.print(Rule(style="dim"))
        console.print(Markdown(reply))
        console.print(Rule(style="dim"))
        console.print()


if __name__ == "__main__":
    main()
