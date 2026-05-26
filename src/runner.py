"""
Orchestrates: search → score → apply across all platforms.
"""

import asyncio
import sys
from pathlib import Path
from rich.console import Console

from playwright.async_api import async_playwright

import sys, os
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    JOB_SEARCH_QUERIES, PLATFORMS, JOB_FIT_THRESHOLD,
    HEADLESS, SLOW_MO_MS, BLACKLISTED_COMPANIES, COOKIES_DIR,
)
from user_profile import USER_PROFILE
from src.tracker import init_db, already_applied, already_skipped, log_application, log_skip
from src.skip_controller import skipper
from src.cookie_manager import has_session, load_session, save_session
from src.scorer import score_job
from src.extractor import get_resume_path
from src.platforms.linkedin import LinkedInPlatform
from src.platforms.naukri import NaukriPlatform
from src.platforms.indeed import IndeedPlatform
from src.platforms.wellfound import WellfoundPlatform

console = Console()

PLATFORM_MAP = {
    "linkedin":  LinkedInPlatform(),
    "naukri":    NaukriPlatform(),
    "indeed":    IndeedPlatform(),
    "wellfound": WellfoundPlatform(),
}

LOGIN_URLS = {
    "linkedin":  "https://www.linkedin.com/login",
    "naukri":    "https://www.naukri.com/nlogin/login",
    "indeed":    "https://in.indeed.com/account/login",
    "wellfound": "https://wellfound.com/login",
}

# One shared browser profile for everything — Google is signed in once here
SHARED_PROFILE = COOKIES_DIR / "shared_profile"

CHROMIUM_BIN = "/usr/bin/chromium"
LAUNCH_ARGS  = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


def _shared_profile() -> Path:
    SHARED_PROFILE.mkdir(exist_ok=True)
    return SHARED_PROFILE


# ── login ─────────────────────────────────────────────────────────────────────


async def login_google():
    """
    Open the shared browser profile and let the user sign into Google once.
    All platforms will reuse this same Google session via 'Continue with Google'.
    """
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(_shared_profile()),
            executable_path=CHROMIUM_BIN,
            headless=False,
            slow_mo=SLOW_MO_MS,
            args=LAUNCH_ARGS,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://accounts.google.com")
        console.print(
            "\n[yellow]Browser opened.[/yellow]\n"
            "Sign into your [bold]Google account[/bold], then press [bold]Enter[/bold] here..."
        )
        input()
        await context.close()
    console.print("[green]Google session saved. You won't need to sign in again.[/green]")


async def login_platform(platform_name: str):
    """
    Open the shared browser (Google already signed in) and log into one platform.
    'Continue with Google' will work without re-authenticating.
    """
    if platform_name not in LOGIN_URLS:
        console.print(f"[red]Unknown platform: {platform_name}[/red]")
        return

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(_shared_profile()),
            executable_path=CHROMIUM_BIN,
            headless=False,
            slow_mo=SLOW_MO_MS,
            args=LAUNCH_ARGS,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(LOGIN_URLS[platform_name])

        console.print(
            f"\n[yellow]Browser opened for [bold]{platform_name}[/bold].[/yellow]\n"
            "Log in (Google is already signed in — just click 'Continue with Google').\n"
            "Once you reach the home/dashboard, press [bold]Enter[/bold] to save..."
        )
        input()

        await save_session(context, platform_name)
        console.print(f"[green]Session saved for {platform_name}.[/green]")
        await context.close()


async def login_all_platforms():
    """
    Sign into Google once, then loop through every platform in the same browser.
    User only interacts with Google auth a single time.
    """
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(_shared_profile()),
            executable_path=CHROMIUM_BIN,
            headless=False,
            slow_mo=SLOW_MO_MS,
            args=LAUNCH_ARGS,
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # Step 1 — Google sign-in
        await page.goto("https://accounts.google.com")
        console.print(
            "\n[bold yellow]Step 1/5 — Google[/bold yellow]\n"
            "Sign into your Google account, then press Enter..."
        )
        input()

        # Step 2–5 — each platform
        for i, platform_name in enumerate(PLATFORMS, start=2):
            await page.goto(LOGIN_URLS[platform_name])
            console.print(
                f"\n[bold yellow]Step {i}/{len(PLATFORMS)+1} — {platform_name}[/bold yellow]\n"
                "Click 'Continue with Google' (already signed in) or use email/password.\n"
                "Reach the home/dashboard, then press Enter..."
            )
            input()
            await save_session(context, platform_name)
            console.print(f"[green]✓ {platform_name} saved[/green]")

        await context.close()
    console.print("\n[bold green]All platforms logged in. You're ready to run.[/bold green]")


# ── run pipeline ──────────────────────────────────────────────────────────────

async def run_pipeline(dry_run: bool = False, platforms: list[str] | None = None):
    """Full search → score → apply pipeline."""
    init_db()
    skipper.start()
    console.print("[dim]Tip: type [bold]s[/bold] + Enter at any time to skip the current application.[/dim]\n")

    resume_path = get_resume_path()
    if not resume_path:
        console.print("[red]No resume PDF found in resume/. Add your PDF and retry.[/red]")
        sys.exit(1)

    active_platforms = platforms or PLATFORMS
    total_applied = 0
    total_skipped = 0

    async with async_playwright() as p:
        for platform_name in active_platforms:
            if platform_name not in PLATFORM_MAP:
                continue

            handler = PLATFORM_MAP[platform_name]

            session = load_session(platform_name)
            if not session:
                console.print(
                    f"[yellow]No saved session for {platform_name}. "
                    f"Run: python main.py login {platform_name}[/yellow]"
                )
                continue

            # Reuse the shared profile so the browser looks real
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(_shared_profile()),
                executable_path=CHROMIUM_BIN,
                headless=HEADLESS,
                slow_mo=SLOW_MO_MS,
                args=LAUNCH_ARGS,
            )
            page = context.pages[0] if context.pages else await context.new_page()

            console.rule(f"[bold blue]{platform_name.upper()}[/bold blue]")

            for query in JOB_SEARCH_QUERIES:
                console.print(f"  Searching: [cyan]{query}[/cyan]")
                try:
                    listings = await handler.search(page, query)
                    console.print(f"    Found [cyan]{len(listings)}[/cyan] listings")
                except Exception as e:
                    console.print(f"  [red]Search error: {e}[/red]")
                    continue

                for job in listings:
                    if already_applied(job.job_id, platform_name):
                        continue
                    if already_skipped(job.job_id, platform_name):
                        continue
                    if any(b.lower() in job.company.lower() for b in BLACKLISTED_COMPANIES):
                        log_skip(job.job_id, platform_name, "blacklisted company")
                        continue

                    if not job.description and platform_name == "linkedin":
                        try:
                            job.description = await handler.get_description(page, job)
                        except Exception:
                            pass

                    result = score_job(
                        title=job.title,
                        company=job.company,
                        description=job.description,
                        location=job.location,
                        salary_text=job.salary,
                    )
                    score       = result.get("score", 0)
                    reason      = result.get("reason", "")
                    should_apply = result.get("apply", False)

                    console.print(
                        f"    [{'green' if should_apply else 'dim'}]"
                        f"{job.title} @ {job.company} — score {score}/100 — {reason}"
                        f"[/{'green' if should_apply else 'dim'}]"
                    )

                    if not should_apply:
                        log_skip(job.job_id, platform_name, f"score {score}: {reason}")
                        total_skipped += 1
                        continue

                    if dry_run:
                        console.print(f"      [yellow][DRY RUN] Would apply: {job.url}[/yellow]")
                        continue

                    skipper.reset()  # clear any previous skip before starting
                    success, fail_reason = await handler.apply(page, job, str(resume_path))

                    # Check if user skipped mid-application
                    if skipper.requested():
                        log_skip(job.job_id, platform_name, "skipped by user")
                        console.print("      [yellow]⏭  Skipped.[/yellow]")
                        total_skipped += 1
                        skipper.reset()
                        continue
                    status  = "applied" if success else "failed"
                    log_application(
                        job_id=job.job_id, platform=platform_name,
                        title=job.title, company=job.company,
                        location=job.location, url=job.url,
                        salary=job.salary, score=score,
                        status=status, notes=fail_reason or reason,
                    )
                    if success:
                        console.print(f"      [green]✓ Applied:[/green] {job.title} @ {job.company}")
                    else:
                        console.print(
                            f"      [red]✗ Failed:[/red] {job.title} @ {job.company} "
                            f"[dim]({fail_reason})[/dim]"
                        )
                    if success:
                        total_applied += 1
                    else:
                        total_skipped += 1

                    await asyncio.sleep(2)

            await context.close()

    console.rule("[bold]Run complete[/bold]")
    console.print(f"  Applied: [green]{total_applied}[/green]  |  Skipped/failed: [dim]{total_skipped}[/dim]")
