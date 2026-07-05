from .client import GitHubClient


async def issue_list(gh: GitHubClient, owner: str, repo: str,
                     state: str = "open", labels: str | None = None,
                     assignee: str | None = None, sort: str = "created",
                     direction: str = "desc", per_page: int = 30) -> str:
    params = {"state": state, "sort": sort, "direction": direction, "per_page": min(per_page, 100)}
    if labels:
        params["labels"] = labels
    if assignee:
        params["assignee"] = assignee
    items = await gh.paginate(f"/repos/{owner}/{repo}/issues", params)
    if not items:
        return "No issues found."
    lines = []
    for i in items:
        if "pull_request" in i:
            continue
        lines.append(f"#{i['number']} [{i['state']}] {i['title']}")
        lines.append(f"  labels: {','.join(l['name'] for l in i['labels'])}" if i['labels'] else "  (no labels)")
        lines.append(f"  created: {i['created_at'][:10]}  comments: {i['comments']}")
    return "\n".join(lines)


async def issue_get(gh: GitHubClient, owner: str, repo: str, number: int,
                    include_comments: bool = True) -> str:
    data = await gh.get(f"/repos/{owner}/{repo}/issues/{number}")
    lines = [
        f"#{data['number']} [{data['state']}] {data['title']}",
        f"by {data['user']['login']}  created: {data['created_at'][:10]}",
        f"labels: {','.join(l['name'] for l in data['labels'])}" if data['labels'] else "",
        f"assignees: {','.join(a['login'] for a in data['assignees'])}" if data['assignees'] else "",
        f"---",
        data.get('body', '') or '(no description)',
    ]
    if include_comments:
        comments = await gh.paginate(f"/repos/{owner}/{repo}/issues/{number}/comments")
        if comments:
            lines.append("\n--- Comments ---")
            for c in comments:
                body = (c['body'] or '')[:2000]
                lines.append(f"\n[{c['user']['login']} @ {c['created_at'][:16]}]")
                lines.append(body)
    return "\n".join(lines)


async def issue_create(gh: GitHubClient, owner: str, repo: str,
                       title: str, body: str = "",
                       labels: list[str] | None = None,
                       assignees: list[str] | None = None) -> str:
    data = {"title": title, "body": body}
    if labels:
        data["labels"] = labels
    if assignees:
        data["assignees"] = assignees
    result = await gh.post(f"/repos/{owner}/{repo}/issues", data)
    return f"Created issue #{result['number']}: {result['html_url']}"


async def issue_update(gh: GitHubClient, owner: str, repo: str, number: int,
                       title: str | None = None, body: str | None = None,
                       state: str | None = None,
                       labels: list[str] | None = None,
                       assignees: list[str] | None = None) -> str:
    data: dict = {}
    if title is not None:
        data["title"] = title
    if body is not None:
        data["body"] = body
    if state is not None:
        data["state"] = state
    if labels is not None:
        data["labels"] = labels
    if assignees is not None:
        data["assignees"] = assignees
    if not data:
        return "Nothing to update."
    result = await gh.patch(f"/repos/{owner}/{repo}/issues/{number}", data)
    return f"Updated issue #{result['number']} ({result['html_url']})"


async def issue_close(gh: GitHubClient, owner: str, repo: str, number: int) -> str:
    return await issue_update(gh, owner, repo, number, state="closed")


async def issue_comment(gh: GitHubClient, owner: str, repo: str,
                        number: int, body: str) -> str:
    result = await gh.post(f"/repos/{owner}/{repo}/issues/{number}/comments", {"body": body})
    return f"Comment added to #{number} ({result['html_url']})"
