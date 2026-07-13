import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import trending


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class TrendingApiTests(unittest.TestCase):
    def setUp(self):
        trending.TRENDING_CACHE.update(data=None, timestamp=None)
        trending.REPO_METRICS_CACHE.clear()
        self.repos = [
            {
                "owner": {"login": "acme"},
                "name": "repo",
                "full_name": "acme/repo",
                "html_url": "https://github.com/acme/repo",
                "description": "A test repository",
                "stargazers_count": 42,
            }
        ]

    def test_missing_token_returns_json_error(self):
        with patch.dict(os.environ, {}, clear=True):
            response = trending.app.test_client().get("/api/trending")

        self.assertEqual(response.status_code, 503)
        self.assertIn("GITHUB_TOKEN", response.get_json()["error"]["message"])

    def test_rate_limit_becomes_429_json_error(self):
        upstream = FakeResponse(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0", "Retry-After": "60"},
        )
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), patch.object(
            trending.HTTP, "request", return_value=upstream
        ):
            response = trending.app.test_client().get("/api/trending")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()["error"]["retry_after"], "60")

    def test_stale_cache_is_returned_when_github_fails(self):
        trending.TRENDING_CACHE.update(
            data={"repos": [{"name": "cached/repo"}]},
            timestamp=datetime.now() - timedelta(hours=2),
        )
        with patch.object(
            trending,
            "get_trending_repos",
            side_effect=trending.GitHubAPIError(429, "rate limited"),
        ):
            response = trending.app.test_client().get("/api/trending")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(body["stale"])
        self.assertIn("warning", body)

    def test_metrics_query_batches_repositories(self):
        query, variables = trending.build_metrics_query(self.repos)

        self.assertEqual(variables, {"owner_0": "acme", "name_0": "repo"})
        self.assertIn("openIssues: issues(states: OPEN)", query)
        self.assertIn("closedPrs: pullRequests(states: [CLOSED, MERGED])", query)

    def test_frontend_has_a_specific_api_error_banner(self):
        page = Path("templates/index.html").read_text()

        self.assertIn("api-error-banner", page)
        self.assertIn("Live GitHub data unavailable:", page)

    def test_frontend_keeps_required_sort_headers_and_health_help(self):
        page = Path("templates/index.html").read_text()

        for label in ("Stars", "Open Issues", "Closed Issues", "Open PRs", "Closed PRs"):
            self.assertIn(label, page)
        for key in ("stars", "open_issues", "closed_issues", "open_prs", "closed_prs"):
            self.assertIn(f'data-sort="{key}"', page)
        self.assertIn("Healthy: fewer than 10 open issues.", page)
        self.assertIn("Needs attention: 10 to 50 open issues.", page)
        self.assertIn("Alert: more than 50 open issues.", page)
        self.assertIn("/static/bg-orange-cream.jpg", page)
        self.assertIn("floating-tooltip", page)
        self.assertNotIn("Sorted by Stars, high to low", page)
        self.assertNotIn("status-help", page)
        self.assertNotIn(">Score<", page)
        self.assertNotIn("Open iss.", page)
        self.assertNotIn("Closed iss.", page)


if __name__ == "__main__":
    unittest.main()
