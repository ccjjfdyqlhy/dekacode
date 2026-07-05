"""
测试 GitHub Skill 模块：client / issues / pulls / actions / repos
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import pytest
from skill import SkillResult
from skills.github_ops import GitHubSkill, _ACTIONS, _ACTION_PARAMS


# ── Hub skill 基本功能 ──

def test_action_list():
    """所有 action 都应有 params 说明"""
    for a in _ACTIONS:
        assert a in _ACTION_PARAMS, f"{a} missing from _ACTION_PARAMS"


def test_no_token():
    import asyncio
    skill = GitHubSkill()
    r = asyncio.run(skill.execute("issue_list", {"owner": "o", "repo": "r"}))
    assert not r.success
    assert "token" in r.output.lower()


def test_properties():
    skill = GitHubSkill(token="test")
    assert skill.name == "github"
    assert "GitHub" in skill.description
    actions = skill.parameters["properties"]["action"]["enum"]
    assert "issue_list" in actions
    assert "pr_create" in actions
    assert "workflow_list" in actions
    assert "repo_info" in actions
    assert "search_code" in actions


# ── GitHubClient 单元测试 ──

@pytest.mark.asyncio
async def test_client_unauthenticated():
    from skills.github.client import GitHubClient
    gh = GitHubClient("")
    assert not gh.authenticated
    await gh.aclose()


@pytest.mark.asyncio
async def test_client_raises_on_bad_auth():
    from skills.github.client import GitHubClient
    gh = GitHubClient("invalid-token")
    try:
        await gh.get("/repos/octocat/Hello-World")
        assert False, "should have raised"
    except Exception as e:
        assert "401" in str(e) or "403" in str(e) or "error" in str(e).lower()
    finally:
        await gh.aclose()


# ── 无网络时的模拟验证 ──

def test_skill_result_model():
    r = SkillResult(success=True, output="ok")
    assert r.success
    assert r.output == "ok"


def test_dispatch_invalid_action():
    import asyncio
    skill = GitHubSkill(token="test")
    r = asyncio.run(skill.execute("nonexistent", {}))
    assert not r.success
    assert "Unknown" in r.output


# ── 全 action 枚举验证 ──

def test_all_actions_have_routes():
    skill = GitHubSkill(token="test")

    async def check_action(action):
        p = _get_dummy_params(action)
        result = await skill.execute(action, p)
        # Should NOT say "Unknown" — means routing works even if API call fails
        assert "Unknown" not in result.output, f"{a}: routing failed"
        return result

    for a in _ACTIONS:
        r = asyncio.run(check_action(a))
        # API will 401 with bad token — that's fine, routing works
        if r.success:
            print(f"  {a}: succeeded (test token may be set?)")


def _get_dummy_params(action: str) -> dict:
    """为每个 action 生成合法结构但不真实的数据"""
    base = {"owner": "test-owner", "repo": "test-repo"}
    number = {"number": 1}
    if action == "issue_create":
        return {**base, "title": "test"}
    if action == "issue_update":
        return {**base, "number": 1, "title": "updated"}
    if action == "issue_comment":
        return {**base, "number": 1, "body": "test"}
    if action in ("issue_get", "issue_close", "issue_update",
                  "pr_get", "pr_merge", "pr_review", "pr_add_comment",
                  "pr_list_files", "pr_get_diff"):
        return {**base, **number}
    if action == "pr_create":
        return {**base, "title": "test", "head": "feature", "base": "main"}
    if action == "pr_review":
        return {**base, "number": 1, "body": "LGTM", "event": "approve"}
    if action == "pr_add_comment":
        return {**base, "number": 1, "body": "comment"}
    if action == "pr_merge":
        return {**base, "number": 1}
    if action == "workflow_runs":
        return {**base}
    if action == "workflow_trigger":
        return {**base, "workflow_id": 1, "ref": "main"}
    if action in ("workflow_cancel", "workflow_rerun", "workflow_get_run"):
        return {**base, "run_id": 1}
    if action in ("search_code", "search_issues"):
        return {"q": "test"}
    return base


if __name__ == '__main__':
    import asyncio

    errors = []
    tests = [
        ("action_list", test_action_list),
        ("no_token", test_no_token),
        ("properties", test_properties),
        ("skill_result_model", test_skill_result_model),
        ("dispatch_invalid_action", test_dispatch_invalid_action),
        ("all_actions_have_routes", test_all_actions_have_routes),
    ]

    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  ✗ {name}: {e}")

    if not errors:
        print("\nAll github tests passed!")
    else:
        print(f"\n{len(errors)} test(s) failed")
        sys.exit(1)
