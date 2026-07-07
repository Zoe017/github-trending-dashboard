import os, requests, time
from datetime import date, timedelta

def get_trending_repos():
    since = (date.today() - timedelta(days=14)).isoformat()
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    params = {
        "q": f"created:>{since}",
        "sort": "stars",
        "order": "desc",
        "per_page": 5,
    }
    r = requests.get("https://api.github.com/search/repositories",
                     headers=headers, params=params)
    r.raise_for_status()
    return r.json()["items"]

# search the type that satisfy the query
# return the total count of the data of the repo
def count_search(query):
    time.sleep(0.5)  # wait for 0.5 sec
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    params = {
        "q" : query,
        "per_page" : 1
    }
    r = requests.get("https://api.github.com/search/issues",
                     headers= headers, params= params)
    r.raise_for_status()
    return r.json()["total_count"]


def get_top_contributors(owner, name, top_n=5):
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    params = {"per_page": top_n}
    r = requests.get(f"https://api.github.com/repos/{owner}/{name}/contributors",
                     headers=headers, params=params)
    r.raise_for_status()
    return [c["login"] for c in r.json()]

# return the open/closed issues and open/closed prs for one repo
def get_repo_metrics(owner, name):
    repo = f"{owner}/{name}"
    return {
        "open_issues":   count_search(f"repo:{repo} type:issue state:open"),
        "closed_issues": count_search(f"repo:{repo} type:issue state:closed"),
        "open_prs":      count_search(f"repo:{repo} type:pr state:open"),
        "closed_prs":    count_search(f"repo:{repo} type:pr state:closed"),
        "top_contributors": get_top_contributors(owner, name),
    }

def compute_health(open_issues):
    if open_issues < 10:
        return "green"
    elif open_issues <= 50:
        return "yellow"
    else:
        return "red"

if __name__ == "__main__":
    import json
    result = {"repos": []}
    for repo in get_trending_repos():
        owner = repo["owner"]["login"]
        name = repo["name"]
        print(f"抓取中: {owner}/{name} ...")   # 让你看到进度
        metrics = get_repo_metrics(owner, name)
        metrics["name"] = repo["full_name"]
        metrics["url"] = repo["html_url"]
        metrics["stars"] = repo["stargazers_count"]
        metrics["health_status"] = compute_health(metrics["open_issues"])
        result["repos"].append(metrics)
    print(json.dumps(result, indent=2))
