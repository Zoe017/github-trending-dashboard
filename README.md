# GitHub Trending Dashboard

A Flask dashboard and SQLite pipeline that track newly created GitHub repositories and retain a history of their rankings and metrics.

## What it does

- **Ingestion** fetches star-ranked search pages, keeps the first occurrence of each repository ID, and batches GraphQL issue and pull request counts in groups of up to 25. A REST call retrieves up to five contributors per repository.
- **Storage** separates repository attributes from observations. Each fresh web fetch or CLI run writes a snapshot. See the [ERD](docs/ERD.md) and [data dictionary](docs/data_dictionary.md).
- **Integrity** uses primary keys, foreign keys, uniqueness checks, and a single transaction per snapshot. An invalid row rolls back the entire snapshot.
- **Analytics** uses SQL views and pandas to report the latest ranking, health distribution, star growth, and language mix.
- **Dashboard** displays repository metrics with sorting and filtering. It serves cached responses and falls back to the last successful response when GitHub is unavailable.

## Architecture

```text
Cron ────→ ingest.py ──────────────────────┐
                                          ├→ GitHub client (REST + GraphQL)
Browser ─→ Flask                          │              │
           GET /                         │              ▼
           GET /api/trending ────────────┘            db.py ─→ SQLite ─→ analysis.py
           GET /api/repos/<owner>/<name>/history ─────→ db.py
```

The web route writes a snapshot after a successful fresh fetch when persistence is enabled. Cache hits and stale fallback responses skip writes. History is available under the repository's current full name.

## Data model

```text
language ─1:N─ repository ─1:N─ repo_snapshot ─N:1─ snapshot
                                     │
                                    1:N
                                     │
                           snapshot_contributor ─N:1─ contributor
```

- `repository` records what a repo *is*, including its GitHub ID and latest attributes.
- `repo_snapshot` records what it *measured* in one run, including rank, stars, forks, issues, and pull requests.
- The health view derives `health_status` from open issue counts at query time.

## Project structure

```text
.
├── trending.py          # Flask routes, caching, and GitHub client
├── db.py                # SQLite connection, transactional writes, and history
├── schema.sql           # Six tables, one index, and four reporting views
├── ingest.py            # One-shot job for scheduled collection
├── analysis.py          # pandas reports based on the SQL views
├── test_db.py           # Storage and integration tests
├── test_trending.py     # Existing dashboard tests
├── requirements.txt
├── docs/
│   ├── ERD.md
│   └── data_dictionary.md
└── templates/
    └── index.html
```

## Run locally

Run from the repository root with Python 3.10 or later. Set the token in your environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN=...
python3 ingest.py --limit 100
python3 analysis.py
python3 trending.py
```

Open [the dashboard](http://127.0.0.1:5001). The default search window is 14 days. Pass `--window-days` to change it, or `--db` to select a file for an individual CLI run.

Example crontab entry for a run every six hours. Configure the GitHub token in the scheduler's environment.

```cron
0 */6 * * * cd /path/to/repo && .venv/bin/python ingest.py --limit 100
```

| Environment variable | Effect |
| --- | --- |
| `TRENDING_DB` | SQLite file shared by web, ingestion, and analysis. Defaults to `trending.db` in the working directory. |
| `PERSIST_SNAPSHOTS` | Defaults to `1`. Set it to `0` to disable web writes. CLI ingestion still writes snapshots. |

## Health rule

| Open issues | Status |
| --- | --- |
| 0–9 | green |
| 10–50 | yellow |
| 51 or more | red |

## Tests

```bash
PERSIST_SNAPSHOTS=0 python3 -m unittest -v
```

Tests use mocked GitHub calls and temporary or in-memory databases to cover pagination, request batching, API behavior, history, constraints, and rollback.

## Limitations

- The dashboard caches data in process memory. Multiple server instances would need a shared cache such as Redis. Web snapshots can include issue, PR, and contributor metrics from the six-hour per-repository cache.
- SQLite suits a single-machine setup. A PostgreSQL port could use `TIMESTAMPTZ` for timestamps and `BIGINT GENERATED ALWAYS AS IDENTITY` for local surrogate keys. The GitHub-supplied repository ID would stay an explicit `BIGINT` primary key.
- GitHub Search exposes up to 1,000 results per query. This project ranks repositories created within the selected window by total stars. [GitHub Search documentation](https://docs.github.com/en/rest/search/search#search-repositories)
- Repository attributes use SCD Type 1 upserts. Historical reports therefore show current names and primary languages alongside historical metrics.
