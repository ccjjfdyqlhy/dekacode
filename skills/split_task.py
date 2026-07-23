from skill import Skill
from models import SkillResult


class SplitTaskSkill(Skill):
    """主 Agent 调用此工具将复杂问题拆解为并发子任务。"""

    @property
    def name(self) -> str:
        return "split_task"

    @property
    def description(self) -> str:
        return (
            "Split a complex problem into sub-tasks for parallel sub-agents to execute concurrently. "
            "Each sub-agent has its own context and can call tools independently. "
            "Use this when a problem requires exploring multiple directions, analyzing separate files, "
            "or evaluating alternative approaches simultaneously. "
            "Write each sub-task prompt as a self-contained instruction for an independent agent."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "Sub-tasks to execute in parallel",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short descriptive title shown to the user",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Full prompt for the sub-agent. Be specific about what to analyze, what tools to use, and what output format to produce. The sub-agent runs independently with full tool access.",
                            },
                        },
                        "required": ["title", "prompt"],
                    },
                },
            },
            "required": ["tasks"],
        }

    async def execute(self, tasks: list[dict], **kwargs) -> SkillResult:
        if not tasks:
            return SkillResult(success=False, output="No tasks provided for splitting.")
        titles = [t.get("title", "Unnamed") for t in tasks]
        return SkillResult(
            success=True,
            output=f"Spawned {len(tasks)} sub-tasks: {', '.join(titles)}",
        )
