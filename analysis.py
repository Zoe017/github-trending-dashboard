"""Read the SQL views so reports reuse the database's metric definitions."""

from contextlib import closing

import pandas as pd

import db


def main():
    with closing(db.connect()) as conn:
        db.init_db(conn)
        # Keep all sections on the same database state during scheduled writes.
        conn.execute("BEGIN")
        latest_id = conn.execute("SELECT MAX(snapshot_id) FROM snapshot").fetchone()[0]
        if latest_id is None:
            print("No snapshots yet. Run: python ingest.py")
            return

        latest = pd.read_sql_query(
            """SELECT rank, full_name, language, stars, open_issues, health_status
               FROM v_latest_trending ORDER BY rank""",
            conn,
        )
        growth = pd.read_sql_query(
            """SELECT * FROM v_star_growth ORDER BY star_gain DESC, full_name LIMIT 10""", conn
        )
        mix = pd.read_sql_query(
            """SELECT language, repo_count, total_stars FROM v_language_mix
               WHERE snapshot_id = ? ORDER BY repo_count DESC, language""",
            conn,
            params=(latest_id,),
        )

    health = latest["health_status"].value_counts().rename("repo_count").reset_index()
    for title, rows in (
        ("Latest trending", latest),
        ("Health status distribution", health),
        ("Top 10 star growth", growth),
        ("Latest snapshot language mix", mix),
    ):
        print(f"\n{title}")
        print(rows.to_string(index=False) if not rows.empty else "(no rows)")


if __name__ == "__main__":
    main()
