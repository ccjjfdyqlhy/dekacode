from .client import GitHubClient


async def repo_info(gh: GitHubClient, owner: str, repo: str) -> str:
    d = await gh.get(f"/repos/{owner}/{repo}")
    lines = [
        f"{d['full_name']}  ⭐ {d['stargazers_count']}  🍴 {d['forks_count']}",
        f"language: {d['language']}  license: {d.get('license', {}).get('spdx_id', 'N/A') if d.get('license') else 'N/A'}",
        f"default_branch: {d['default_branch']}  open_issues: {d['open_issues_count']}",
        f"visibility: {d['visibility']}  archived: {d['archived']}  fork: {d['fork']}",
        f"created: {d['created_at'][:10]}  updated: {d['updated_at'][:10]}",
        f"description: {d.get('description', '(no description)')}",
        f"topics: {', '.join(d.get('topics', []))}" if d.get("topics") else "",
        f"url: {d['html_url']}",
    ]
    return "\n".join(line for line in lines if line)


async def search_code(gh: GitHubClient, q: str,
                      owner: str | None = None,
                      repo: str | None = None,
                      per_page: int = 10) -> str:
    query = q
    if owner and repo:
        query = f"{q} repo:{owner}/{repo}"
    elif owner:
        query = f"{q} user:{owner}"
    params: dict = {"q": query, "per_page": min(per_page, 100)}
    data = await gh.get("/search/code", params)
    items = data.get("items", [])
    if not items:
        return "No code search results."
    total = data.get("total_count", 0)
    lines = [f"Found {total} results (showing top {len(items)}):\n"]
    for i in items:
        path = i["path"]
        repo_full = i["repository"]["full_name"]
        url = i["html_url"]
        lines.append(f"  {path}  ({repo_full})")
    return "\n".join(lines)


async def search_issues(gh: GitHubClient, q: str,
                        owner: str | None = None,
                        repo: str | None = None,
                        state: str | None = None,
                        per_page: int = 10) -> str:
    query = q
    if owner and repo:
        query = f"{q} repo:{owner}/{repo}"
    elif owner:
        query = f"{q} user:{owner}"
    if state:
        query = f"{query} state:{state}"
    params: dict = {"q": query, "per_page": min(per_page, 100)}
    data = await gh.get("/search/issues", params)
    items = data.get("items", [])
    if not items:
        return "No issue search results."
    total = data.get("total_count", 0)
    lines = [f"Found {total} results (showing top {len(items)}):\n"]
    for i in items:
        repo_full = i["repository"]["full_name"]
        lines.append(f"  [{i['state']}] #{i['number']} {i['title']}")
        lines.append(f"    {repo_full}  by {i['user']['login']}  {i['created_at'][:10]}")
    return "\n".join(lines)


async def list_branches(gh: GitHubClient, owner: str, repo: str) -> str:
    items = await gh.paginate(f"/repos/{owner}/{repo}/branches")
    if not items:
        return "No branches found."
    lines = [f"Branches ({len(items)}):"]
    for b in items:
        sha = b["commit"]["sha"][:8]
        lines.append(f"  {b['name']}  ({sha})")
    return "\n".join(lines)
