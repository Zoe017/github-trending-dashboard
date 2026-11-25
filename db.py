"""Store one complete observation per transaction."""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DB_PATH = os.getenv("TRENDING_DB", "trending.db")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path=DEFAULT_DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # SQLite enforces foreign keys only when enabled on each connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def save_snapshot(conn, repos, metrics_by_repo, *, window_days, source, captured_at=None):
    """Keep dimensions and facts together so a failed row leaves no partial run."""
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with conn:
        cursor = conn.execute(
            "INSERT INTO snapshot (captured_at, window_days, repo_count, source) VALUES (?, ?, ?, ?)",
            (captured_at, window_days, len(repos), source),
        )
        snapshot_id = cursor.lastrowid
        for rank, repo in enumerate(repos, start=1):
            language_id = None
            if language := repo.get("language"):
                conn.execute("INSERT OR IGNORE INTO language (name) VALUES (?)", (language,))
                language_id = conn.execute(
                    "SELECT language_id FROM language WHERE name = ?", (language,)
                ).fetchone()["language_id"]

            repo_id = repo["id"]
            full_name = repo["full_name"]
            conn.execute(
                """INSERT INTO repository (
                       repo_id, full_name, owner_login, name, html_url, description,
                       language_id, created_at, first_seen_at, last_seen_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo_id) DO UPDATE SET
                       full_name = excluded.full_name, owner_login = excluded.owner_login,
                       name = excluded.name, html_url = excluded.html_url,
                       description = excluded.description, language_id = excluded.language_id,
                       last_seen_at = excluded.last_seen_at
                   WHERE excluded.last_seen_at >= repository.last_seen_at""",
                (
                    repo_id, full_name, repo["owner"]["login"], repo["name"], repo["html_url"],
                    repo.get("description"), language_id, repo["created_at"], captured_at, captured_at,
                ),
            )
            metrics = metrics_by_repo[full_name]
            conn.execute(
                """INSERT INTO repo_snapshot (
                       snapshot_id, repo_id, rank, stars, forks, open_issues, closed_issues,
                       open_prs, closed_prs
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id, repo_id, rank, repo["stargazers_count"], repo.get("forks_count", 0),
                    metrics["open_issues"], metrics["closed_issues"],
                    metrics["open_prs"], metrics["closed_prs"],
                ),
            )
            for position, login in enumerate(metrics["top_contributors"], start=1):
                conn.execute("INSERT OR IGNORE INTO contributor (login) VALUES (?)", (login,))
                conn.execute(
                    """INSERT INTO snapshot_contributor
                       (snapshot_id, repo_id, position, contributor_login) VALUES (?, ?, ?, ?)""",
                    (snapshot_id, repo_id, position, login),
                )
    return snapshot_id


def repo_history(conn, full_name):
    rows = conn.execute(
        """SELECT captured_at, rank, stars, forks, open_issues, open_prs, health_status
           FROM v_repo_snapshot_health
           WHERE full_name = ? ORDER BY captured_at""",
        (full_name,),
    )
    return [dict(row) for row in rows]
