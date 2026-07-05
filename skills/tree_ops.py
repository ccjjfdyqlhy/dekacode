from skill import Skill, SkillResult

from skills.core.thought_tree import RoundTable


class TreeSkill(Skill):
    """思维树（Tree of Thoughts）Hub Skill — 圆桌讨论模式。"""

    def __init__(self):
        self._round_table: RoundTable | None = None

    @property
    def name(self) -> str:
        return "tree"

    @property
    def description(self) -> str:
        return (
            "思维树 — 多分支圆桌讨论。调用 start 启动多视角并行讨论，"
            "各分支通过 speak/read_chat 实时交流、协调，最终由任意分支 conclude 结束。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "speak", "read_chat", "complete", "conclude"],
                    "description": (
                        "start: 启动讨论，需传 branches 参数\n"
                        "speak: 向讨论区发言，需传 message\n"
                        "read_chat: 查看完整讨论记录\n"
                        "complete: 标记本分支完成，需传 summary\n"
                        "conclude: 输出最终结论，结束整个讨论，需传 answer"
                    ),
                },
                "branches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "hypothesis": {"type": "string"},
                        },
                        "required": ["id", "label"],
                    },
                    "description": "仅 start 需要：定义各分支的 id、label、hypothesis",
                },
                "message": {
                    "type": "string",
                    "description": "仅 speak 需要：发言内容",
                },
                "summary": {
                    "type": "string",
                    "description": "仅 complete 需要：该分支的总结",
                },
                "answer": {
                    "type": "string",
                    "description": "仅 conclude 需要：最终结论",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs) -> SkillResult:
        if action == "start":
            branches = kwargs.get("branches", [])
            if not branches:
                return SkillResult(success=False, output="start 需要 branches 参数")
            labels = [f"{b.get('label', b['id'])}: {b.get('hypothesis', '')}" for b in branches]
            return SkillResult(success=True, output=(
                f"已启动 {len(branches)} 个分支的圆桌讨论：\n"
                + "\n".join(f"  [{b['id']}] {b.get('label', b['id'])} — {b.get('hypothesis', '')}" for b in branches)
            ))
        elif action == "speak":
            return SkillResult(success=True, output="（发言已发布到讨论区）")
        elif action == "read_chat":
            return SkillResult(success=True, output="（查看 whiteboard 应在讨论中通过 tree.read_chat 获取）")
        elif action == "complete":
            return SkillResult(success=True, output="✓ 分支已完成")
        elif action == "conclude":
            return SkillResult(success=True, output="✓ 结论已提交")
        return SkillResult(success=False, output=f"未知 tree action: {action}")
