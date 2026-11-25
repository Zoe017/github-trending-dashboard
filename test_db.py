import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import db
import trending


FIRST = "2026-11-24T12:00:00+00:00"
SECOND = "2026-11-25T12:00:00+00:00"
TABLES = ("language", "repository", "snapshot", "repo_snapshot", "contributor", "snapshot_contributor")


def repository(repo_id=1, name="a", language="Python", stars=20):
    return {
        "id": repo_id, "name": name, "full_name": f"acme/{name}", "owner": {"login": "acme"},
        "html_url": f"https://github.com/acme/{name}", "description": None,
        "created_at": "2026-11-20T12:00:00Z", "language": language,
        "stargazers_count": stars,
    }


def metrics(open_issues=9):
    return {
        "open_issues": open_issues, "closed_issues": 2, "open_prs": 1, "closed_prs": 4,
        "top_contributors": ["shared"],
    }


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        db.init_db(self.conn)

    def save(self, repos, captured_at=FIRST, counts=None):
        by_name = {repo["full_name"]: metrics() for repo in repos} if counts is None else counts
        return db.save_snapshot(
            self.conn, repos, by_name, window_days=14, source="cli", captured_at=captured_at
        )

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_repo_snapshot_requires_an_existing_repository(self):
        snapshot_id = self.save([])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO repo_snapshot VALUES (?, 999, 1, 0, 0, 0, 0, 0, 0)", (snapshot_id,)
            )

    def test_save_populates_all_tables_without_duplicate_lookups(self):
        self.save([repository(), repository(2, "b", None)])
        self.assertEqual([self.count(table) for table in TABLES], [1, 2, 1, 2, 1, 2])
        self.assertEqual(self.conn.execute("SELECT repo_count FROM snapshot").fetchone()[0], 2)
        self.assertIsNone(self.conn.execute(
            "SELECT language_id FROM repository WHERE repo_id = 2"
        ).fetchone()[0])

    def test_second_snapshot_preserves_identity_and_first_seen_after_rename(self):
        self.save([repository()])
        self.save([repository(name="renamed", stars=32)], captured_at=SECOND)
        self.assertEqual(self.count("repository"), 1)
        row = self.conn.execute("SELECT * FROM repository").fetchone()
        self.assertEqual((row["full_name"], row["first_seen_at"], row["last_seen_at"]),
                         ("acme/renamed", FIRST, SECOND))
        growth = self.conn.execute("SELECT * FROM v_star_growth").fetchone()
        self.assertEqual(tuple(growth)[3:], (20, 32, 12, 2))
        self.assertEqual([row["stars"] for row in db.repo_history(self.conn, "acme/renamed")], [20, 32])

    def test_invalid_second_row_rolls_back_every_table(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.save([repository(), repository(2, "b", "Go", stars=-1)])
        self.assertEqual([self.count(table) for table in TABLES], [0] * len(TABLES))

    def test_health_boundaries(self):
        repos = [repository(rank, f"repo{rank}") for rank in range(1, 5)]
        counts = {repo["full_name"]: metrics(n) for repo, n in zip(repos, (9, 10, 50, 51))}
        self.save(repos, counts=counts)
        rows = self.conn.execute("SELECT health_status FROM v_latest_trending ORDER BY rank")
        self.assertEqual([row[0] for row in rows], ["green", "yellow", "yellow", "red"])

    def test_language_mix_labels_missing_language(self):
        self.save([repository(language=None)])
        row = self.conn.execute("SELECT language, repo_count, total_stars FROM v_language_mix").fetchone()
        self.assertEqual(tuple(row), ("(none)", 1, 20))

    def test_contributor_requires_the_repository_to_appear_in_that_snapshot(self):
        self.save([repository()])
        snapshot_id = self.save([repository(2, "b")], captured_at=SECOND)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO snapshot_contributor VALUES (?, 1, 1, 'shared')", (snapshot_id,)
            )


class GitHubCollectionTests(unittest.TestCase):
    def test_pagination_keeps_first_duplicate_in_rank_order(self):
        first_page = [repository(n, str(n)) for n in (1, 2, 3)]
        second_page = [repository(3, "3", stars=1), repository(4, "4")]
        with patch.object(trending, "SEARCH_PAGE_SIZE", 3), patch.object(
            trending, "github_get", side_effect=[{"items": first_page}, {"items": second_page}]
        ) as request:
            rows = trending.get_trending_repos(limit=5)
        self.assertEqual(rows, first_page + second_page[1:])
        self.assertEqual([call.kwargs["params"]["page"] for call in request.call_args_list], [1, 2])

    def test_graphql_requests_are_bounded_and_reuse_cache(self):
        self.addCleanup(trending.REPO_METRICS_CACHE.clear)
        trending.REPO_METRICS_CACHE.clear()
        repos = [repository(n, str(n)) for n in range(1, 27)]

        def counts(batch):
            return {repo["full_name"]: metrics() for repo in batch}

        with patch.object(trending, "get_bulk_repo_counts", side_effect=counts) as graphql, patch.object(
            trending, "get_top_contributors", return_value=["shared"]
        ):
            self.assertEqual(len(trending.get_repo_metrics(repos)), 26)
            self.assertEqual(len(trending.get_repo_metrics(repos)), 26)
        self.assertEqual([len(call.args[0]) for call in graphql.call_args_list], [25, 1])


class SnapshotRouteTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.db"
        settings = patch.dict(trending.app.config, DB_PATH=self.path, PERSIST_SNAPSHOTS=True)
        settings.start()
        self.addCleanup(settings.stop)
        trending.TRENDING_CACHE.update(data=None, timestamp=None)
        self.addCleanup(trending.TRENDING_CACHE.update, data=None, timestamp=None)
        self.client = trending.app.test_client()

    def test_fresh_web_response_persists_once_and_history_uses_the_view(self):
        with patch.object(trending, "get_trending_repos", return_value=[repository()]), patch.object(
            trending, "get_repo_metrics", return_value={"acme/a": metrics(50)}
        ):
            fresh = self.client.get("/api/trending")
            cached = self.client.get("/api/trending")
        self.assertEqual((fresh.status_code, cached.status_code), (200, 200))
        self.assertEqual(fresh.get_json(), cached.get_json())
        response = self.client.get("/api/repos/acme/a/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["repo"], "acme/a")
        history, = response.json["snapshots"]
        self.assertEqual((history["stars"], history["health_status"]), (20, "yellow"))
        with closing(db.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT source FROM snapshot").fetchone()[0], "web")

    def test_no_history_returns_json_404(self):
        response = self.client.get("/api/repos/acme/a/history")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json, {"error": {"message": "No snapshots recorded for this repository."}})

    def test_persistence_error_still_returns_live_data(self):
        with patch.object(trending, "get_trending_repos", return_value=[repository()]), patch.object(
            trending, "get_repo_metrics", return_value={"acme/a": metrics()}
        ), patch.object(trending, "persist_snapshot", side_effect=sqlite3.OperationalError("locked")), (
            self.assertLogs(trending.app.logger, level="ERROR")
        ):
            response = self.client.get("/api/trending")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["stale"])

    def test_stale_result_is_not_persisted(self):
        trending.TRENDING_CACHE.update(data={"repos": []}, timestamp=datetime.now() - timedelta(hours=2))
        with patch.object(trending, "get_trending_repos", side_effect=trending.GitHubAPIError(429, "limited")), (
            patch.object(trending, "persist_snapshot")
        ) as persist:
            response = self.client.get("/api/trending")
        self.assertTrue(response.json["stale"])
        persist.assert_not_called()
