import asyncio
import time
from dataclasses import dataclass, field
from models import Message, ToolCall, Function


@dataclass
class SubTask:
    title: str
    prompt: str
    status: str = "pending"  # pending, running, done, error
    output: str = ""
    elapsed: float = 0.0


@dataclass
class SubAgentResult:
    title: str
    output: str
    elapsed: float
    success: bool
    error: str = ""
    tool_count: int = 0


class SubAgent:
    """独立子 Agent，有独立的上下文和工具循环。"""

    def __init__(self, title: str, prompt: str, client, registry, graph=None,
                 max_turns: int = 8, output_limit: int = 4096, timeout: float = 60):
        self.title = title
        self.prompt = prompt
        self._client = client
        self._registry = registry
        self._graph = graph
        self._max_turns = max_turns
        self._output_limit = output_limit
        self._timeout = timeout

    async def run(self, system_prompt: str = "", parent_title: str = "") -> SubAgentResult:
        """执行子 Agent 的工具调用循环。"""
        from context import ContextManager

        sub_task_instruction = (
            f"You are a sub-agent working on: {self.title}\n\n"
            f"Before starting, create a SubTask plan using `todowrite` with `parent_index` set to the index "
            f"of the parent task \"{parent_title}\" in the global todo list. "
            f"Use `parent_index` only if you know the exact index of the parent task in the global todo. "
            f"Break your work into 2-5 specific sub-tasks. Mark one in_progress at a time. "
            f"Then execute your task using available tools.\n\n"
        )

        ctx = ContextManager(system_prompt)
        ctx.history.append(Message(role="system", content=sub_task_instruction))
        ctx.history.append(Message(role="user", content=self.prompt))

        t0 = time.time()
        tool_count = 0
        last_content = ""

        try:
            async with asyncio.timeout(self._timeout):
                for turn in range(self._max_turns):
                    request = ctx.build_request()
                    response = await self._client.chat(
                        request,
                        self._registry.get_tool_definitions(),
                        model_mode="flash",
                        max_tokens=self._output_limit,
                    )

                    choices = response.get("choices")
                    if not choices:
                        break

                    msg = choices[0].get("message", {})
                    content = msg.get("content") or ""
                    tool_calls_raw = msg.get("tool_calls")

                    if content:
                        last_content = content

                    if tool_calls_raw:
                        parsed = []
                        for tc in tool_calls_raw:
                            func = Function(
                                name=tc["function"]["name"],
                                arguments=tc["function"]["arguments"],
                            )
                            parsed.append(ToolCall(
                                id=tc["id"],
                                type=tc.get("type", "function"),
                                function=func,
                            ))
                        assistant = Message(role="assistant", content=content or None)
                        assistant.tool_calls = parsed
                        ctx.draft.append(assistant)

                        results = await asyncio.gather(
                            *[self._exec_tool(tc) for tc in parsed],
                            return_exceptions=True,
                        )

                        for tc, result_tuple in zip(parsed, results):
                            if isinstance(result_tuple, Exception):
                                ctx.add_tool_result(tc.id, tc.function.name, f"[Error] {result_tuple}")
                            else:
                                tc_result, text = result_tuple
                                ctx.add_tool_result(tc_result.id, tc_result.function.name, text)
                                tool_count += 1

                        ctx.commit_draft()
                    else:
                        break
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            elapsed = time.time() - t0
            return SubAgentResult(
                title=self.title,
                output=last_content,
                elapsed=elapsed,
                success=False,
                error=str(e),
                tool_count=tool_count,
            )

        elapsed = time.time() - t0
        return SubAgentResult(
            title=self.title,
            output=last_content or "(no output)",
            elapsed=elapsed,
            success=True,
            tool_count=tool_count,
        )

    async def _exec_tool(self, tc: ToolCall):
        import json
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            return (tc, f"[Parse Error] Invalid JSON: {tc.function.arguments[:200]}")
        try:
            result = await self._registry.execute(tc.function.name, args)
            text = result.output if result.success else f"[Error] {result.output}"
            return (tc, text)
        except Exception as e:
            return (tc, f"[Error] {type(e).__name__}: {e}")


async def run_sub_agents(
    tasks: list[dict],
    client,
    registry,
    graph=None,
    system_prompt: str = "",
    max_turns: int = 6,
    on_status=None,
) -> list[SubAgentResult]:
    """并发执行多个子 Agent。on_status(title, status) 用于回调状态更新。"""
    agents = [
        SubAgent(
            title=t["title"],
            prompt=t["prompt"],
            client=client,
            registry=registry,
            graph=graph,
            max_turns=max_turns,
        )
        for t in tasks
    ]

    class TrackedAgent:
        def __init__(self, agent, idx, total):
            self.agent = agent
            self.idx = idx
            self.total = total

    tracked = [TrackedAgent(a, i, len(agents)) for i, a in enumerate(agents)]

    async def run_one(ta: TrackedAgent):
        if on_status:
            on_status(ta.agent.title, "running")
        parent_title = ta.agent.title
        result = await ta.agent.run(system_prompt=system_prompt, parent_title=parent_title)
        if on_status:
            on_status(ta.agent.title, "done" if result.success else "error")
        return result

    results = await asyncio.gather(*[run_one(ta) for ta in tracked])
    return list(results)


def build_merge_prompt(results: list[SubAgentResult]) -> str:
    """构造合并提示词：先关注冲突，再全面检查。"""
    parts = [
        "You previously split a task into sub-tasks and ran them in parallel.",
        f"Below are the results from {len(results)} sub-agents.",
        "",
        "## Merge Instructions",
        "1. **Conflict Resolution** — Identify contradictions between sub-results. Determine which is correct, or synthesize a middle-ground solution.",
        "2. **Completeness Check** — Verify no important aspects were missed. Fill gaps if necessary.",
        "3. **Final Synthesis** — Produce a unified, actionable answer for the user.",
        "",
        "---",
        "",
    ]
    for i, r in enumerate(results):
        status = "✓" if r.success else "✗"
        parts.append(f"## Sub-task {i+1}: {r.title}  [{status}]  {r.elapsed:.1f}s")
        if r.error:
            parts.append(f"Error: {r.error}")
        parts.append(r.output)
        parts.append("")
    return "\n".join(parts)
