from skill import Skill, SkillResult

from skills.github.client import GitHubClient
from skills.github import issues, pulls, actions, repos


_ACTIONS = [
    # Issues
    "issue_list", "issue_get", "issue_create",
    "issue_update", "issue_close", "issue_comment",
    # Pull Requests
    "pr_list", "pr_get", "pr_create", "pr_merge",
    "pr_review", "pr_add_comment", "pr_list_files", "pr_get_diff",
    # Actions
    "workflow_list", "workflow_runs", "workflow_trigger",
    "workflow_cancel", "workflow_rerun", "workflow_get_run",
    # Repos / Search
    "repo_info", "search_code", "search_issues", "list_branches",
]

_ACTION_PARAMS = {
    "issue_list":      "owner, repo [, state, labels, assignee, sort, direction, per_page]",
    "issue_get":       "owner, repo, number [, include_comments]",
    "issue_create":    "owner, repo, title [, body, labels, assignees]",
    "issue_update":    "owner, repo, number [, title, body, state, labels, assignees]",
    "issue_close":     "owner, repo, number",
    "issue_comment":   "owner, repo, number, body",
    "pr_list":         "owner, repo [, state, sort, direction, per_page]",
    "pr_get":          "owner, repo, number",
    "pr_create":       "owner, repo, title, head, base [, body, draft]",
    "pr_merge":        "owner, repo, number [, commit_title, commit_message, merge_method]",
    "pr_review":       "owner, repo, number [, body, event]  (event: approve|comment|request_changes)",
    "pr_add_comment":  "owner, repo, number, body",
    "pr_list_files":   "owner, repo, number",
    "pr_get_diff":     "owner, repo, number [, max_len]",
    "workflow_list":   "owner, repo",
    "workflow_runs":   "owner, repo [, workflow_id, branch, status, event, per_page]",
    "workflow_trigger":"owner, repo, workflow_id, ref [, inputs]",
    "workflow_cancel": "owner, repo, run_id",
    "workflow_rerun":  "owner, repo, run_id",
    "workflow_get_run":"owner, repo, run_id",
    "repo_info":       "owner, repo",
    "search_code":     "q [, owner, repo, per_page]",
    "search_issues":   "q [, owner, repo, state, per_page]",
    "list_branches":   "owner, repo",
}


class GitHubSkill(Skill):
    def __init__(self, token: str = "", base_url: str = "https://api.github.com"):
        self._gh = GitHubClient(token, base_url) if token else None

    @property
    def name(self) -> str:
        return "github"

    @property
    def description(self) -> str:
        return (
            "GitHub 全功能接口：Issues / Pull Requests / Actions / 仓库搜索。"
            "所有操作需要 owner/repo 标识仓库。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": _ACTIONS,
                    "description": "要执行的操作",
                },
                "params": {
                    "type": "object",
                    "description": "操作参数（JSON 对象）。各 action 所需字段：\n" + "\n".join(
                        f"  {a}: {p}" for a, p in _ACTION_PARAMS.items()
                    ),
                },
            },
            "required": ["action", "params"],
        }

    async def execute(self, action: str, params: dict, **kwargs) -> SkillResult:
        if not self._gh or not self._gh.authenticated:
            return SkillResult(success=False, output="GitHub token not configured. Set GITHUB_TOKEN in .env")
        try:
            return await self._dispatch(action, params)
        except Exception as e:
            return SkillResult(success=False, output=f"GitHub error: {e}")

    async def _dispatch(self, action: str, p: dict) -> SkillResult:
        gh = self._gh

        # Issues
        if action == "issue_list":
            out = await issues.issue_list(gh, **p)
        elif action == "issue_get":
            out = await issues.issue_get(gh, **p)
        elif action == "issue_create":
            out = await issues.issue_create(gh, **p)
        elif action == "issue_update":
            out = await issues.issue_update(gh, **p)
        elif action == "issue_close":
            out = await issues.issue_close(gh, **p)
        elif action == "issue_comment":
            out = await issues.issue_comment(gh, **p)

        # Pull Requests
        elif action == "pr_list":
            out = await pulls.pr_list(gh, **p)
        elif action == "pr_get":
            out = await pulls.pr_get(gh, **p)
        elif action == "pr_create":
            out = await pulls.pr_create(gh, **p)
        elif action == "pr_merge":
            out = await pulls.pr_merge(gh, **p)
        elif action == "pr_review":
            out = await pulls.pr_review(gh, **p)
        elif action == "pr_add_comment":
            out = await pulls.pr_add_comment(gh, **p)
        elif action == "pr_list_files":
            out = await pulls.pr_list_files(gh, **p)
        elif action == "pr_get_diff":
            out = await pulls.pr_get_diff(gh, **p)

        # Actions
        elif action == "workflow_list":
            out = await actions.workflow_list(gh, **p)
        elif action == "workflow_runs":
            out = await actions.workflow_runs(gh, **p)
        elif action == "workflow_trigger":
            out = await actions.workflow_trigger(gh, **p)
        elif action == "workflow_cancel":
            out = await actions.workflow_cancel(gh, **p)
        elif action == "workflow_rerun":
            out = await actions.workflow_rerun(gh, **p)
        elif action == "workflow_get_run":
            out = await actions.workflow_get_run(gh, **p)

        # Repos / Search
        elif action == "repo_info":
            out = await repos.repo_info(gh, **p)
        elif action == "search_code":
            out = await repos.search_code(gh, **p)
        elif action == "search_issues":
            out = await repos.search_issues(gh, **p)
        elif action == "list_branches":
            out = await repos.list_branches(gh, **p)

        else:
            return SkillResult(success=False, output=f"Unknown github action: {action}")

        return SkillResult(success=True, output=out)
