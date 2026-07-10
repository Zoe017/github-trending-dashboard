# GitHub Trending Dashboard

一个基于 Flask 与 GitHub API 的实时仪表盘：发现最近 14 天创建、按 Star 排序的开源仓库，并展示 issue、pull request、贡献者和项目健康状态。

> 当前版本已经完成前后端联调和离线接口验证。它对 Token、超时、GitHub 失败与限流返回清晰 JSON，并会在实时获取失败时使用上一次成功的缓存结果。

## Demo capabilities

- 从 GitHub Search API 查找最近 14 天创建的仓库，并按 Star 数排序。
- 展示仓库名、链接、简介、Star 数、开启/关闭的 issues 与 PR、前 5 位贡献者。
- 根据开启 issue 数给出健康状态：`< 10` 为 green、`10–50` 为 yellow、`> 50` 为 red。
- 前端支持搜索、按 Stars / open issues / open PRs 排序，以及展开查看详情。
- 后端使用 60 分钟进程内缓存和 6 小时仓库指标缓存，避免每次打开页面都重复请求 GitHub。
- 使用 1 次 REST 仓库搜索 + 1 次 GraphQL 批量指标查询，替代每个仓库的 4 次 Search API 计数请求。
- 对缺失 Token、鉴权失败、超时、GitHub 限流和上游异常返回可读 JSON；实时请求失败时优先展示最后一次成功结果。
- 页面会在实时 API 请求失败时显示具体错误原因，同时清楚标记当前正在展示 sample data。

## Architecture

```text
Browser
  └─ GET / and GET /api/trending
       ├─ Flask (trending.py)
       │    ├─ 60-minute in-memory cache
       │    └─ GitHub API
       │         ├─ REST: search repositories and contributors
       │         └─ GraphQL: batched open/closed issue and PR counts
       └─ templates/index.html
            └─ renders, searches, sorts, and expands repository rows
```

## Project structure

```text
github-trending-dashboard/
├── trending.py             # Flask routes, GitHub API client logic, cache, health rules
├── templates/
│   └── index.html          # Dashboard UI bundle
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.10+
- A GitHub personal access token that can access public REST and GraphQL API data
- Python packages: `Flask` and `requests`

## Run locally

```bash
cd /Users/zoeli/Desktop/github-trending-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN="your_github_token"
python3 trending.py
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001).

Do not commit the token. Keep it in your shell environment or a local `.env` file that is ignored by Git.

## API contract

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

`health_score` is currently calculated only for featured rows. It is an extra dashboard metric, not the assignment's primary health rule.

## Health rule

| Open issues | Status |
| --- | --- |
| `< 10` | green / Healthy |
| `10–50` | yellow / Needs attention |
| `> 50` | red / Alert |

## Verification completed

- `python3 -m py_compile trending.py`
- Flask test-client smoke test with mocked GitHub responses
  - `/` returns `200`
  - `/api/trending` returns JSON
  - cache path returns successfully
  - health thresholds and featured-row fields behave as expected
- Static check that the dashboard fetches `/api/trending` and consumes repository metrics.

## Known limitations

This is an honest pre-submission checklist, not a statement that these requirements are already complete.

1. **Live verification:** this checkout had no `GITHUB_TOKEN` during review, so a real GitHub API response has not yet been verified.
2. **Frontend maintainability:** `templates/index.html` is a generated packed bundle. Preserve the original UI source and the build/export steps if the layout needs continued iteration.
3. **Cache scope:** the caches are process-local. This is appropriate for a single local Flask process; a multi-instance deployment should use a shared cache such as Redis.

## Next steps before submission

1. Run one authenticated end-to-end check and capture a screenshot for the final presentation.
2. Extend the automated tests with an authenticated, non-destructive API smoke test before release.
3. Commit the dashboard template, `requirements.txt`, and this README after reviewing the generated UI artifact.
