import asyncio
import json
import time
from dataclasses import dataclass, field

from models import Message, Function, ToolCall, SkillResult


@dataclass
class BranchState:
    id: str
    label: str
    hypothesis: str = ""
    history: list = field(default_factory=list)
    draft: list = field(default_factory=list)
    status: str = "active"
    turn: int = 0
    last_content: str = ""


class RoundTable:
    """圆桌讨论执行器：多分支并发思考 + 共享 whiteboard 群聊。"""

    def __init__(self, system_prompt: str, prefix: list,
                 branches_data: list[dict],
                 max_rounds: int = 3, max_turns: int = 5):
        self.system = Message(role="system", content=system_prompt)
        self.prefix = prefix
        self.branches: dict[str, BranchState] = {
            b["id"]: BranchState(
                id=b["id"],
                label=b.get("label", b["id"]),
                hypothesis=b.get("hypothesis", ""),
            ) for b in branches_data
        }
        self.whiteboard: list[str] = []
        self.round_num = 0
        self.max_rounds = max_rounds
        self.max_turns = max_turns
        self.conclusion: str | None = None
        self._console = None
        self._display = None

    def _whiteboard_text(self) -> str:
        if not self.whiteboard:
            return "## 讨论记录\n（暂无内容）"
        lines = ["## 讨论记录"]
        for idx, msg in enumerate(self.whiteboard):
            lines.append(f"{idx + 1}. {msg}")
        chat = "\n".join(lines)
        if len(chat) > 3000:
            chat = "## 讨论记录（最近）\n" + "\n".join(lines[-20:])
        return chat

    async def run(self, client, registry, model_mode: str,
                  token_counter=None, console=None, display=None) -> str:
        self._console = console
        self._display = display
        round_start = time.time()

        while self.round_num < self.max_rounds:
            active = [b for b in self.branches.values() if b.status == "active"]
            if not active:
                break
            self.round_num += 1

            labels = ", ".join(b.label for b in active)
            if self._console:
                self._console.print(
                    f"  [bold cyan]🌳 Round {self.round_num}/{self.max_rounds}[/]"
                    f"  [dim]({len(active)} branches: {labels})[/]"
                )

            if self._display:
                est = (time.time() - round_start) / max(self.round_num - 1, 1) * self.max_rounds
                await self._display.status(
                    f"🌳 Round {self.round_num}/{self.max_rounds}",
                    f"{len(active)} branches",
                    turn_estimated=est,
                )

            async def _run_branch(branch: BranchState):
                request = (
                    [self.system]
                    + self.prefix
                    + [Message(role="system", content=self._whiteboard_text())]
                    + branch.history
                    + branch.draft
                )
                tools = registry.get_tool_definitions()
                t0 = time.time()
                response = await client.chat(
                    request, tools, model_mode=model_mode, max_tokens=8192
                )
                elapsed = time.time() - t0
                if token_counter:
                    rec = token_counter.record(response, model=model_mode, elapsed=elapsed)
                    if self._display:
                        usage_text = "  "
                        from token_counter import fmt_tokens
                        usage_text += (
                            f"[yellow]↑[/] {fmt_tokens(rec.input_tokens)} [dim]in[/] "
                            f"[cyan]↓[/] {fmt_tokens(rec.output_tokens)} [dim]out[/] "
                            f"[dim]│[/] [bold yellow]¥{rec.cost:.4f}[/]"
                        )
                        branch.last_content = usage_text
                choices = response.get("choices", [])
                if not choices:
                    branch.last_content = ""
                    return
                msg = choices[0].get("message", {})
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls")

                if tool_calls:
                    parsed = []
                    for tc in tool_calls:
                        func = Function(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        )
                        parsed.append(ToolCall(
                            id=tc["id"], type=tc.get("type", "function"),
                            function=func,
                        ))
                    assistant = Message(
                        role="assistant", content=content or None, tool_calls=parsed,
                    )
                    branch.draft.append(assistant)

                    for tc in parsed:
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            branch.draft.append(Message(
                                role="tool", tool_call_id=tc.id,
                                name=tc.function.name,
                                content="[Parse Error] Invalid JSON arguments",
                            ))
                            continue

                        if tc.function.name == "tree":
                            result_text = self._handle_tree_action(branch, args)
                        else:
                            res = await registry.execute(tc.function.name, args)
                            result_text = res.output if res.success else f"[Error] {res.output}"

                        branch.draft.append(Message(
                            role="tool", tool_call_id=tc.id,
                            name=tc.function.name, content=result_text,
                        ))

                    branch.history.extend(branch.draft)
                    branch.draft.clear()
                    branch.turn += 1

                elif content:
                    branch.history.append(Message(role="assistant", content=content))
                    if self.conclusion is None:
                        self.whiteboard.append(f"[{branch.label}] {content[:500]}")

            tasks = [
                _run_branch(b)
                for b in self.branches.values()
                if b.status == "active"
            ]
            await asyncio.gather(*tasks)

            # 每轮结束后：打印各分支发言/完成状态
            if self._console:
                for b in self.branches.values():
                    if b.status == "completed" and b.turn > 0:
                        self._console.print(
                            f"  [dim]▸ {b.label}[/]  [green]✓ 完成[/]"
                            f"  {b.last_content if b.last_content else ''}"
                        )
                # 查找本轮新增的 whiteboard 发言
                for entry in self.whiteboard:
                    if f"Round {self.round_num}/" in entry or "branch:" in entry:
                        continue
                    if entry.startswith("["):
                        self._console.print(f"  [dim]{entry}[/]")

            if self._display:
                await self._display.end()

            if self.conclusion:
                return self.conclusion

        if self._display:
            await self._display.end()

        return self._format_final()

    def _handle_tree_action(self, branch: BranchState, args: dict) -> str:
        action = args.get("action", "")
        if action == "speak":
            msg = args.get("message", "")
            self.whiteboard.append(f"[{branch.label}] {msg}")
            if self._console:
                self._console.print(f"  [dim]💬 [{branch.label}] {msg[:200]}[/]")
            return "✓ 发言已发布到讨论区"
        elif action == "complete":
            summary = args.get("summary", "")
            branch.status = "completed"
            tag = f"✓ {summary}" if summary else "✓ 完成"
            self.whiteboard.append(f"[{branch.label}] {tag}")
            if self._console:
                self._console.print(
                    f"  [dim]▸ {branch.label}[/]  [green]{tag}[/]"
                    f"  {branch.last_content if branch.last_content else ''}"
                )
            return "✓ 分支已完成"
        elif action == "conclude":
            answer = args.get("answer", "")
            self.conclusion = answer
            self.whiteboard.append(f"[{branch.label}] 🏁 得出结论")
            if self._console:
                self._console.print(f"  [bold green]🏁 {branch.label}[/] 得出结论")
            return "✓ 结论已提交，讨论结束"
        elif action == "read_chat":
            return self._whiteboard_text()
        else:
            return f"未知 tree action: {action}"

    def _format_final(self) -> str:
        lines = [f"# 圆桌讨论结果（共 {self.round_num} 轮）\n"]
        for b in self.branches.values():
            tag = "✓" if b.status == "completed" else "⏳"
            lines.append(f"**{b.label}** [{tag}] — {b.hypothesis}  （{b.turn} 轮）")
        lines.append("\n---\n## 讨论记录\n")
        lines.append(self._whiteboard_text())
        return "\n".join(lines)
