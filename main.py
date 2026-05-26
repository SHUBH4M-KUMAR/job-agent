#!/usr/bin/env python3
"""
Job Application Bot — CLI entry point.

Commands:
  login-google         Sign into Google once (shared across all platforms)
  login <platform>     Log in to a platform and save session
  run                  Run full search → score → apply pipeline
  dry-run              Search and score without submitting applications
  status               Show application statistics and recent history
  clear-session <p>    Delete saved session for a platform
  session-status       Show which platforms have active sessions
"""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent))

from src.tracker import init_db, get_stats, get_recent
from src.cookie_manager import clear_session, has_session
from config import PLATFORMS, OLLAMA_MODEL

console = Console()


@click.group()
def cli():
    """Automated job application bot."""
    pass


@cli.command("login-google")
def login_google():
    """Sign into Google once. All platforms reuse this session via 'Continue with Google'."""
    from src.runner import login_google as _login_google
    asyncio.run(_login_google())


@cli.command()
@click.argument("platform", type=click.Choice(PLATFORMS + ["all"]))
def login(platform):
    """Log in to PLATFORM. Use 'all' for every platform in one session."""
    from src.runner import login_platform, login_all_platforms
    if platform == "all":
        asyncio.run(login_all_platforms())
    else:
        asyncio.run(login_platform(platform))


@cli.command()
@click.option("--platform", "-p", multiple=True, help="Limit to specific platform(s).")
def run(platform):
    """Run the full pipeline: search → Ollama score → auto-apply."""
    _check_ollama()
    from src.runner import run_pipeline
    asyncio.run(run_pipeline(dry_run=False, platforms=list(platform) or None))


@cli.command("dry-run")
@click.option("--platform", "-p", multiple=True)
def dry_run(platform):
    """Search and score jobs without submitting any applications."""
    _check_ollama()
    from src.runner import run_pipeline
    asyncio.run(run_pipeline(dry_run=True, platforms=list(platform) or None))


@cli.command()
def status():
    """Show application statistics and recent applications."""
    init_db()
    stats = get_stats()
    console.print("\n[bold]Application Statistics[/bold]")
    console.print(f"  Total applied : [green]{stats['total_applied']}[/green]")
    console.print(f"  Total skipped : [dim]{stats['skipped']}[/dim]")

    if stats["by_platform"]:
        t = Table(title="By Platform", show_header=True, header_style="bold cyan")
        t.add_column("Platform"); t.add_column("Applied", justify="right")
        for plat, cnt in stats["by_platform"].items():
            t.add_row(plat, str(cnt))
        console.print(t)

    recent = get_recent(20)
    if recent:
        t3 = Table(title="Recent Applications", show_header=True, header_style="bold cyan")
        for col in ["Date", "Title", "Company", "Platform", "Score", "Status"]:
            t3.add_column(col)
        for r in recent:
            t3.add_row(r["applied_at"][:10], r["title"], r["company"],
                       r["platform"], str(r["score"]), r["status"])
        console.print(t3)


@cli.command("clear-session")
@click.argument("platform", type=click.Choice(PLATFORMS + ["all"]))
def clear_session_cmd(platform):
    """Delete saved login session for PLATFORM."""
    for p in (PLATFORMS if platform == "all" else [platform]):
        clear_session(p)
        console.print(f"[yellow]Session cleared for {p}.[/yellow]")


@cli.command("session-status")
def session_status():
    """Show which platforms have active saved sessions."""
    for p in PLATFORMS:
        icon = "[green]✓ saved[/green]" if has_session(p) else "[red]✗ not logged in[/red]"
        console.print(f"  {p:12} {icon}")


def _check_ollama():
    import ollama
    try:
        ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": "hi"}],
                    options={"num_predict": 1})
    except Exception as e:
        console.print(
            f"[red]Cannot reach Ollama with model '{OLLAMA_MODEL}'.[/red]\n"
            f"Error: {e}\n"
            f"Run: ollama serve  &&  ollama pull {OLLAMA_MODEL}"
        )
        sys.exit(1)


if __name__ == "__main__":
    cli()
