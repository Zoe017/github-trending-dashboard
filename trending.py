import os
from datetime import date, datetime, timedelta

import requests
from flask import Flask, jsonify, send_from_directory


app = Flask(__name__)

GITHUB_REST_API = "https://api.github.com"
GITHUB_GRAPHQL_API = "https://api.github.com/graphql"
GITHUB_API_VERSION = "2026-03-10"
REQUEST_TIMEOUT = (3.05, 15)
CACHE_DURATION = timedelta(minutes=60)
METRICS_CACHE_DURATION = timedelta(hours=6)
HTTP = requests.Session()

TRENDING_CACHE = {
    "data": None,
    "timestamp": None,
}
REPO_METRICS_CACHE = {}


class GitHubAPIError(Exception):
    """A safe, user-facing error from an upstream GitHub API request."""

    def __init__(self, status_code, message, *, upstream_status=None, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.upstream_status = upstream_status
        self.retry_after = retry_after


def github_headers():
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubAPIError(
            503,
            "GitHub API is not configured. Set the GITHUB_TOKEN environment variable.",
        )

    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def response_message(response):
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload.get("message") if isinstance(payload, dict) else None


def github_request(method, url, **kwargs):
    """Make one bounded GitHub request and normalize upstream failures."""
    try:
        response = HTTP.request(
            method,
            url,
            headers=github_headers(),
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
    except requests.Timeout as error:
        raise GitHubAPIError(
            504,
            "GitHub API request timed out. Please try again.",
        ) from error
    except requests.RequestException as error:
        raise GitHubAPIError(
            503,
            "GitHub API is temporarily unreachable. Please try again.",
        ) from error

    if response.status_code >= 400:
        message = response_message(response) or "GitHub API request failed."
        remaining = response.headers.get("X-RateLimit-Remaining")
        retry_after = response.headers.get("Retry-After")
        is_rate_limit = (
            response.status_code == 429
            or remaining == "0"
            or "rate limit" in message.lower()
        )

        if is_rate_limit:
            raise GitHubAPIError(
                429,
                "GitHub API rate limit reached. Please retry after the limit resets.",
                upstream_status=response.status_code,
                retry_after=retry_after or response.headers.get("X-RateLimit-Reset"),
            )
        if response.status_code == 401:
            raise GitHubAPIError(
                502,
                "GitHub authentication failed. Check GITHUB_TOKEN and try again.",
                upstream_status=401,
            )
        raise GitHubAPIError(
            502,
            "GitHub API rejected the request. Please try again later.",
            upstream_status=response.status_code,
        )

    try:
        return response.json()
    except ValueError as error:
        raise GitHubAPIError(
            502,
            "GitHub API returned an invalid response.",
        ) from error


def github_get(path, *, params=None):
    return github_request("GET", f"{GITHUB_REST_API}{path}", params=params)


def github_graphql(query, variables):
    payload = github_request(
        "POST",
        GITHUB_GRAPHQL_API,
        json={"query": query, "variables": variables},
    )
    errors = payload.get("errors", [])
    if errors:
        message = errors[0].get("message", "GitHub GraphQL request failed.")
        if "rate limit" in message.lower():
            raise GitHubAPIError(429, "GitHub API rate limit reached. Please retry later.")
        raise GitHubAPIError(502, "GitHub GraphQL request failed. Please try again.")
    return payload.get("data", {})


def get_trending_repos():
    since = (date.today() - timedelta(days=14)).isoformat()
    payload = github_get(
        "/search/repositories",
        params={
            "q": f"created:>{since}",
            "sort": "stars",
            "order": "desc",
            "per_page": 20,
        },
    )
    return payload["items"]


def build_metrics_query(repos):
    """Build one GraphQL query for all issue/PR count combinations."""
    variable_definitions = []
    variables = {}
    selections = []

    for index, repo in enumerate(repos):
        owner_key = f"owner_{index}"
        name_key = f"name_{index}"
        alias = f"repo_{index}"
        variable_definitions.extend((f"${owner_key}: String!", f"${name_key}: String!"))
        variables[owner_key] = repo["owner"]["login"]
        variables[name_key] = repo["name"]
        selections.append(
            f"""
            {alias}: repository(owner: ${owner_key}, name: ${name_key}) {{
              openIssues: issues(states: OPEN) {{ totalCount }}
              closedIssues: issues(states: CLOSED) {{ totalCount }}
              openPrs: pullRequests(states: OPEN) {{ totalCount }}
              closedPrs: pullRequests(states: [CLOSED, MERGED]) {{ totalCount }}
            }}
            """
        )

    query = f"query RepositoryMetrics({', '.join(variable_definitions)}) {{ {' '.join(selections)} }}"
    return query, variables


def get_bulk_repo_counts(repos):
    query, variables = build_metrics_query(repos)
    data = github_graphql(query, variables)
    counts = {}

    for index, repo in enumerate(repos):
        node = data.get(f"repo_{index}")
        if node is None:
            raise GitHubAPIError(502, "GitHub returned incomplete repository metrics.")
        counts[repo["full_name"]] = {
            "open_issues": node["openIssues"]["totalCount"],
            "closed_issues": node["closedIssues"]["totalCount"],
            "open_prs": node["openPrs"]["totalCount"],
            "closed_prs": node["closedPrs"]["totalCount"],
        }
    return counts


def get_top_contributors(owner, name, top_n=5):
    try:
        contributors = github_get(
            f"/repos/{owner}/{name}/contributors",
            params={"per_page": top_n},
        )
    except GitHubAPIError as error:
        # Empty repositories can return 409; deleted repositories can disappear
        # between the ranking query and this request. Neither should fail the page.
        if error.upstream_status in {404, 409}:
            return []
        raise
    return [contributor["login"] for contributor in contributors]


def cached_metrics(repo_name):
    cached = REPO_METRICS_CACHE.get(repo_name)
    if cached and datetime.now() - cached["timestamp"] < METRICS_CACHE_DURATION:
        return dict(cached["data"])
    return None


def get_repo_metrics(repos):
    """Use cached metrics where possible; batch all remaining counts into one call."""
    metrics_by_repo = {}
    missing_repos = []

    for repo in repos:
        repo_name = repo["full_name"]
        metrics = cached_metrics(repo_name)
        if metrics is None:
            missing_repos.append(repo)
        else:
            metrics_by_repo[repo_name] = metrics

    if not missing_repos:
        return metrics_by_repo

    counts_by_repo = get_bulk_repo_counts(missing_repos)
    for repo in missing_repos:
        repo_name = repo["full_name"]
        metrics = {
            **counts_by_repo[repo_name],
            "top_contributors": get_top_contributors(
                repo["owner"]["login"], repo["name"]
            ),
        }
        REPO_METRICS_CACHE[repo_name] = {
            "data": metrics,
            "timestamp": datetime.now(),
        }
        metrics_by_repo[repo_name] = dict(metrics)

    return metrics_by_repo


def compute_health(open_issues):
    if open_issues < 10:
        return "green"
    if open_issues <= 50:
        return "yellow"
    return "red"


def compute_health_score(metrics):
    total_issues = metrics["open_issues"] + metrics["closed_issues"]
    total_prs = metrics["open_prs"] + metrics["closed_prs"]
    issue_resolution_rate = (
        1.0 if total_issues == 0 else metrics["closed_issues"] / total_issues
    )
    pr_closure_rate = 1.0 if total_prs == 0 else metrics["closed_prs"] / total_prs
    return round(issue_resolution_rate * 50 + pr_closure_rate * 50)


def cache_payload(payload, timestamp, *, stale=False, warning=None):
    response = {
        **payload,
        "cached_at": timestamp.isoformat(timespec="seconds"),
        "stale": stale,
    }
    if warning:
        response["warning"] = warning
    return jsonify(response)


@app.errorhandler(GitHubAPIError)
def handle_github_error(error):
    payload = {"error": {"message": error.message}}
    if error.retry_after:
        payload["error"]["retry_after"] = error.retry_after
    return jsonify(payload), error.status_code


@app.route("/")
def home():
    # Serve the UI bundle directly so Flask does not parse its {{ ... }} expressions.
    return send_from_directory(app.template_folder, "index.html")


@app.route("/api/trending")
def trending():
    cache_timestamp = TRENDING_CACHE["timestamp"]
    cached_data = TRENDING_CACHE["data"]
    if (
        cached_data is not None
        and cache_timestamp is not None
        and datetime.now() - cache_timestamp < CACHE_DURATION
    ):
        return cache_payload(cached_data, cache_timestamp)

    try:
        result = {"repos": []}
        repos = get_trending_repos()
        metrics_by_repo = get_repo_metrics(repos)
        for rank, repo in enumerate(repos, start=1):
            metrics = dict(metrics_by_repo[repo["full_name"]])
            featured = rank <= 5
            metrics.update(
                {
                    "rank": rank,
                    "featured": featured,
                    "name": repo["full_name"],
                    "url": repo["html_url"],
                    "description": repo.get("description"),
                    "stars": repo["stargazers_count"],
                    "health_status": compute_health(metrics["open_issues"]),
                }
            )
            if featured:
                metrics["health_score"] = compute_health_score(metrics)
            result["repos"].append(metrics)
    except GitHubAPIError as error:
        if cached_data is not None and cache_timestamp is not None:
            return cache_payload(
                cached_data,
                cache_timestamp,
                stale=True,
                warning="Live GitHub data is temporarily unavailable; showing the last successful result.",
            )
        raise error

    cache_timestamp = datetime.now()
    TRENDING_CACHE["data"] = result
    TRENDING_CACHE["timestamp"] = cache_timestamp
    return cache_payload(result, cache_timestamp)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
