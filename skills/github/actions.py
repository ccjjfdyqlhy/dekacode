from .client import GitHubClient


async def workflow_list(gh: GitHubClient, owner: str, repo: str) -> str:
    data = await gh.get(f"/repos/{owner}/{repo}/actions/workflows")
    workflows = data.get("workflows", [])
    if not workflows:
        return "No workflows found."
    lines = []
    for w in workflows:
        state = "✓" if w["state"] == "active" else "✗"
        lines.append(f"{state} {w['name']}  (id={w['id']})  [{w['state']}]")
        lines.append(f"   path: {w['path']}")
    return "\n".join(lines)


async def workflow_runs(gh: GitHubClient, owner: str, repo: str,
                        workflow_id: int | str | None = None,
                        branch: str | None = None,
                        status: str | None = None,
                        event: str | None = None,
                        per_page: int = 20) -> str:
    path = f"/repos/{owner}/{repo}/actions/runs"
    if workflow_id:
        path = f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
    params: dict = {"per_page": min(per_page, 100)}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event
    data = await gh.get(path, params)
    runs = data.get("workflow_runs", [])
    if not runs:
        return "No workflow runs found."
    lines = []
    for r in runs:
        created = r["created_at"][:16] if r.get("created_at") else ""
        lines.append(f"#{r['run_number']} [{r['status']}/{r['conclusion']}] {r['name']}")
        lines.append(f"  branch: {r['head_branch']}  event: {r['event']}  {created}")
        lines.append(f"  workflow: {r['workflow_id']}  id={r['id']}")
    return "\n".join(lines)


async def workflow_trigger(gh: GitHubClient, owner: str, repo: str,
                           workflow_id: int | str,
                           ref: str = "main",
                           inputs: dict | None = None) -> str:
    data: dict = {"ref": ref}
    if inputs:
        data["inputs"] = inputs
    await gh.post(f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches", data)
    return f"Dispatched workflow {workflow_id} on ref={ref}"


async def workflow_cancel(gh: GitHubClient, owner: str, repo: str,
                          run_id: int) -> str:
    await gh.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/cancel")
    return f"Cancelled run #{run_id}"


async def workflow_rerun(gh: GitHubClient, owner: str, repo: str,
                         run_id: int) -> str:
    await gh.post(f"/repos/{owner}/{repo}/actions/runs/{run_id}/rerun")
    return f"Re-queued run #{run_id}"


async def workflow_get_run(gh: GitHubClient, owner: str, repo: str,
                           run_id: int) -> str:
    data = await gh.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}")
    lines = [
        f"Run #{data['run_number']} (id={data['id']})",
        f"workflow: {data['name']}  (id={data['workflow_id']})",
        f"status: {data['status']}  conclusion: {data['conclusion']}",
        f"branch: {data['head_branch']}  commit: {data['head_sha'][:8]}",
        f"event: {data['event']}  created: {data['created_at'][:16]}",
        f"duration: {data.get('run_started_at', '')[:16]} → {data.get('updated_at', '')[:16]}",
    ]
    return "\n".join(lines)
