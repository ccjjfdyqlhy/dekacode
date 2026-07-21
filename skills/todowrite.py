from skill import Skill
from models import SkillResult
from state.todo import TodoTracker

_tracker = TodoTracker()


def get_tracker() -> TodoTracker:
    return _tracker


class TodowriteSkill(Skill):
    @property
    def name(self) -> str:
        return "todowrite"

    @property
    def description(self) -> str:
        return "Create and update a structured task list for the current coding session. Tracks progress of multi-step work."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The updated todo list",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Brief description of the task",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Status of the task",
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Priority level of the task",
                            },
                        },
                        "required": ["content", "status", "priority"],
                    },
                },
            },
            "required": ["todos"],
        }

    async def execute(self, todos: list[dict], **kwargs) -> SkillResult:
        _tracker.set_todos(todos)
        done = sum(1 for t in todos if t.get("status") in ("completed", "cancelled"))
        total = len(todos)
        pending = [t for t in todos if t.get("status") not in ("completed", "cancelled")]
        if not pending:
            return SkillResult(success=True, output=f"All {total} tasks done.")
        active = [t for t in pending if t.get("status") == "in_progress"]
        next_up = active[0]["content"] if active else (pending[0]["content"] if pending else "")
        return SkillResult(
            success=True,
            output=f"{done}/{total} done. Next: {next_up}",
        )
