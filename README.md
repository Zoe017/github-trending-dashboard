# GitHub Trending Dashboard

A Flask-based dashboard that uses the GitHub API to find recently created open-source repositories, rank them by stars, and display issue counts, pull request counts, contributors, and project health status.

The current version has a working backend and frontend integration. It returns clear JSON errors for missing tokens, timeouts, GitHub failures, and rate limits. If live data cannot be refreshed after a successful request, the backend can return the latest cached result.

## Demo Capabilities

- Searches GitHub for repositories created in the last 14 days and ranks them by star count.
- Displays repository name, link, description, stars, open and closed issues, open and closed pull requests, top contributors, and health status.
- Calculates health status from open issue count: fewer than 10 is `green`, 10 to 50 is `yellow`, and more than 50 is `red`.
- Supports frontend search, table-header sorting by Stars / Open Issues / Closed Issues / Open PRs / Closed PRs, and row expansion for details.
- Shows one hoverable/clickable `?` marker in the Status header for health status explanations.
- Uses a 60-minute process-level dashboard cache and a 6-hour repository metrics cache to avoid repeated GitHub calls on every page load.
- Uses one REST repository search plus one batched GraphQL metrics request instead of multiple per-repository count requests.
- Returns readable JSON for missing tokens, authentication failures, timeouts, rate limits, and upstream GitHub errors.
- Shows a visible frontend error banner when the live API request fails and falls back to sample data.

## Architecture

```text
Browser
  -> GET / and GET /api/trending
       -> Flask (trending.py)
          -> 60-minute in-memory dashboard cache
          -> GitHub API
             -> REST: repository search and contributors
             -> GraphQL: batched open/closed issue and PR counts
       -> templates/index.html
          -> renders, searches, sorts, and expands repository rows
```

## Project Structure

```text
github-trending-dashboard/
├── trending.py             # Flask routes, GitHub API client logic, cache, health rules
├── templates/
│   └── index.html          # Dashboard UI
├── static/
│   └── bg-orange-cream.jpg # Orange glass background image
├── test_trending.py        # Automated backend and template checks
├── requirements.txt        # Python dependencies
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.10+
- A GitHub personal access token that can access public REST and GraphQL API data
- Python packages listed in `requirements.txt`

## Run Locally

```bash
cd /Users/zoeli/Desktop/github-trending-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN="your_github_token"
python3 trending.py
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001).

Do not commit your GitHub token. Keep it in your shell environment or in a local `.env` file that is ignored by Git.

## API Contract

### `GET /api/trending`

Returns a JSON object with the retrieval time and a list of repositories.

```json
{
  "cached_at": "2026-07-09T15:30:00",
  "stale": false,
  "repos": [
    {
      "rank": 1,
      "featured": true,
      "name": "owner/repository",
      "url": "https://github.com/owner/repository",
      "description": "Repository description",
      "stars": 1234,
      "open_issues": 3,
      "closed_issues": 18,
      "open_prs": 2,
      "closed_prs": 9,
      "top_contributors": ["alice", "bob"],
      "health_status": "green",
      "health_score": 79
    }
  ]
}
```

`health_score` is currently calculated only for featured rows. The API still returns it for compatibility, but the visible dashboard uses the simpler health status label instead of a Score column.

## Health Rule

| Open Issues | Status |
| --- | --- |
| `< 10` | `green` / `Healthy` |
| `10-50` | `yellow` / `Needs attention` |
| `> 50` | `red` / `Alert` |

## Verification

Run the automated checks:

```bash
python3 -m unittest -v
python3 -m py_compile trending.py
```

The current tests cover:

- Missing token JSON error handling.
- GitHub rate-limit JSON error handling.
- Stale cache fallback.
- Batched GraphQL metrics query shape.
- Frontend API error banner text.
- Frontend template checks for metric labels, Status help behavior, and removed Score/sort-readout UI.

## Known Limitations

1. Live GitHub verification requires a valid `GITHUB_TOKEN`.
2. The frontend is a plain HTML/CSS/JS page. If the visual design changes again, keep the background asset and the metric-sort contract aligned.
3. The caches are process-local. This is fine for a local Flask demo; a multi-instance deployment should use a shared cache such as Redis.
