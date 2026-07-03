from abc import ABC, abstractmethod

from models import SkillResult, ToolDefinition


class Skill(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        ...

    def get_tool_definition(self) -> ToolDefinition:
        return ToolDefinition(
            function={
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        )

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        ...


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def get_tool_definitions(self) -> list[ToolDefinition]:
        return [s.get_tool_definition() for s in self._skills.values()]

    async def execute(self, name: str, arguments: dict) -> SkillResult:
        skill = self.get(name)
        if not skill:
            return SkillResult(success=False, output=f"Skill '{name}' not found")
        return await skill.execute(**arguments)
