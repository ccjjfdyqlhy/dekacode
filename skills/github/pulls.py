from .client import GitHubClient


async def pr_list(gh: GitHubClient, owner: str, repo: str,
                  state: str = "open", sort: str = "created",
                  direction: str = "desc", per_page: int = 30) -> str:
    params = {"state": state, "sort": sort, "direction": direction, "per_page": min(per_page, 100)}
    items = await gh.paginate(f"/repos/{owner}/{repo}/pulls", params)
    if not items:
        return "No pull requests found."
    lines = []
    for pr in items:
        lines.append(f"#{pr['number']} [{pr['state']}] {pr['title']}")
        lines.append(f"  head: {pr['head']['label']}  base: {pr['base']['label']}")
        lines.append(f"  by {pr['user']['login']}  created: {pr['created_at'][:10]}")
        lines.append(f"  comments: {pr['comments']}  commits: {pr['commits']}  changed: {pr['changed_files']}")
    return "\n".join(lines)


async def pr_get(gh: GitHubClient, owner: str, repo: str, number: int) -> str:
    data = await gh.get(f"/repos/{owner}/{repo}/pulls/{number}")
    lines = [
        f"#{data['number']} [{data['state']}] {data['title']}",
        f"by {data['user']['login']}  created: {data['created_at'][:10]}",
        f"head: {data['head']['label']}  base: {data['base']['label']}",
        f"mergeable: {data['mergeable']}  draft: {data['draft']}",
        f"commits: {data['commits']}  changed files: {data['changed_files']}",
        f"additions: {data['additions']}  deletions: {data['deletions']}",
        f"---",
        data.get('body', '') or '(no description)',
    ]
    return "\n".join(lines)


async def pr_create(gh: GitHubClient, owner: str, repo: str,
                    title: str, head: str, base: str,
                    body: str = "", draft: bool = False) -> str:
    data = {"title": title, "head": head, "base": base, "body": body, "draft": draft}
    result = await gh.post(f"/repos/{owner}/{repo}/pulls", data)
    return f"Created PR #{result['number']}: {result['html_url']}"


async def pr_merge(gh: GitHubClient, owner: str, repo: str, number: int,
                   commit_title: str | None = None,
                   commit_message: str | None = None,
                   merge_method: str = "merge") -> str:
    data = {"merge_method": merge_method}
    if commit_title:
        data["commit_title"] = commit_title
    if commit_message:
        data["commit_message"] = commit_message
    result = await gh.put(f"/repos/{owner}/{repo}/pulls/{number}/merge", data)
    return f"Merged PR #{number}: {result.get('message', '')}"


async def pr_review(gh: GitHubClient, owner: str, repo: str, number: int,
                    body: str = "", event: str = "comment") -> str:
    if event not in ("approve", "comment", "request_changes"):
        return f"Invalid review event: {event}"
    data = {"body": body, "event": event}
    result = await gh.post(f"/repos/{owner}/{repo}/pulls/{number}/reviews", data)
    return f"Review submitted on PR #{number} (id: {result['id']})"


async def pr_add_comment(gh: GitHubClient, owner: str, repo: str,
                         number: int, body: str) -> str:
    result = await gh.post(f"/repos/{owner}/{repo}/pulls/{number}/comments", {"body": body})
    return f"Comment added to PR #{number}"


async def pr_list_files(gh: GitHubClient, owner: str, repo: str,
                        number: int) -> str:
    items = await gh.paginate(f"/repos/{owner}/{repo}/pulls/{number}/files")
    if not items:
        return "No files changed."
    lines = []
    for f in items:
        lines.append(f"{f['status']:>8}  +{f['additions']}/-{f['deletions']}  {f['filename']}")
    return "\n".join(lines)


async def pr_get_diff(gh: GitHubClient, owner: str, repo: str,
                      number: int, max_len: int = 30000) -> str:
    text = await gh.get_text(f"/repos/{owner}/{repo}/pulls/{number}",
                             accept="application/vnd.github.v3.diff")
    if len(text) > max_len:
        text = text[:max_len] + f"\n\n[...diff truncated at {max_len} chars]"
    return text
