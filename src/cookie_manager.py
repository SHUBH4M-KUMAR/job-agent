"""
Saves and loads Playwright browser session state (cookies + localStorage)
per platform so the user only needs to log in once.
"""

import json
from pathlib import Path
from config import COOKIES_DIR


def session_path(platform: str) -> Path:
    return COOKIES_DIR / f"{platform}.json"


def has_session(platform: str) -> bool:
    p = session_path(platform)
    return p.exists() and p.stat().st_size > 10


async def save_session(context, platform: str):
    state = await context.storage_state()
    with open(session_path(platform), "w") as f:
        json.dump(state, f, indent=2)


def load_session(platform: str) -> dict | None:
    p = session_path(platform)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def clear_session(platform: str):
    p = session_path(platform)
    if p.exists():
        p.unlink()
