"""
SQLite-backed application tracker.
Prevents re-applying to the same job and keeps a full history.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from config import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL,
                platform    TEXT NOT NULL,
                title       TEXT,
                company     TEXT,
                location    TEXT,
                url         TEXT,
                salary      TEXT,
                score       INTEGER,
                status      TEXT DEFAULT 'applied',
                applied_at  TEXT,
                notes       TEXT,
                UNIQUE(job_id, platform)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skipped (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL,
                platform    TEXT NOT NULL,
                reason      TEXT,
                skipped_at  TEXT,
                UNIQUE(job_id, platform)
            )
        """)
        conn.commit()


def already_applied(job_id: str, platform: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM applications WHERE job_id=? AND platform=?",
            (job_id, platform),
        ).fetchone()
        return row is not None


def already_skipped(job_id: str, platform: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM skipped WHERE job_id=? AND platform=?",
            (job_id, platform),
        ).fetchone()
        return row is not None


def log_application(
    job_id: str,
    platform: str,
    title: str,
    company: str,
    location: str,
    url: str,
    salary: str,
    score: int,
    status: str = "applied",
    notes: str = "",
):
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO applications
              (job_id, platform, title, company, location, url, salary, score, status, applied_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, platform, title, company, location, url,
                salary, score, status,
                datetime.now().isoformat(timespec="seconds"),
                notes,
            ),
        )
        conn.commit()


def log_skip(job_id: str, platform: str, reason: str):
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO skipped (job_id, platform, reason, skipped_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, platform, reason, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def update_status(job_id: str, platform: str, status: str, notes: str = ""):
    with _connect() as conn:
        conn.execute(
            "UPDATE applications SET status=?, notes=? WHERE job_id=? AND platform=?",
            (status, notes, job_id, platform),
        )
        conn.commit()


def get_stats() -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM applications GROUP BY status"
        ).fetchall()
        by_platform = conn.execute(
            "SELECT platform, COUNT(*) as cnt FROM applications GROUP BY platform"
        ).fetchall()
        skipped = conn.execute("SELECT COUNT(*) FROM skipped").fetchone()[0]
    return {
        "total_applied": total,
        "skipped": skipped,
        "by_status": {r["status"]: r["cnt"] for r in by_status},
        "by_platform": {r["platform"]: r["cnt"] for r in by_platform},
    }


def get_recent(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT title, company, platform, location, salary, score, status, applied_at
            FROM applications
            ORDER BY applied_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
