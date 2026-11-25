"""Capture one snapshot for a scheduler to run repeatedly.

Cron example (configure GITHUB_TOKEN in the job environment):
0 */6 * * * cd /path/to/repo && .venv/bin/python ingest.py --limit 100
"""

import argparse
import sqlite3
import sys
from contextlib import closing

import db
from trending import DEFAULT_LIMIT, WINDOW_DAYS, GitHubAPIError, get_repo_metrics, get_trending_repos


def main():
    parser = argparse.ArgumentParser(description="Capture a GitHub trending snapshot.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH)
    args = parser.parse_args()
    if args.limit < 1 or args.window_days < 1:
        parser.error("--limit and --window-days must be positive")

    try:
        repos = get_trending_repos(limit=args.limit, window_days=args.window_days)
        metrics = get_repo_metrics(repos)
        with closing(db.connect(args.db)) as conn:
            db.init_db(conn)
            snapshot_id = db.save_snapshot(
                conn, repos, metrics, window_days=args.window_days, source="cli"
            )
    except GitHubAPIError as error:
        print(error.message, file=sys.stderr)
        return 1
    except sqlite3.Error as error:
        print(f"Could not save snapshot: {error}", file=sys.stderr)
        return 1

    print(f"Saved snapshot {snapshot_id}: {len(repos)} repositories -> {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
