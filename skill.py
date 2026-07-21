import importlib
import inspect
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from models import SkillResult, ToolDefinition

logger = logging.getLogger(__name__)


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

    def load_skills_from_module(
        self, module_path: str, graph=None, **kwargs
    ) -> list[str]:
        """动态加载模块中所有 Skill 子类的实例"""
        loaded = []
        try:
            module = importlib.import_module(module_path)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Skill) and obj is not Skill:
                    try:
                        sig = inspect.signature(obj.__init__)
                        params = list(sig.parameters.keys())
                        init_kwargs = {}
                        if "self" in params:
                            params.remove("self")
                        if "graph" in params and graph is not None:
                            init_kwargs["graph"] = graph
                        for key, value in kwargs.items():
                            if key in params:
                                init_kwargs[key] = value
                        skill = obj(**init_kwargs)
                        self.register(skill)
                        loaded.append(skill.name)
                        logger.debug(f"Loaded skill: {skill.name} from {module_path}")
                    except Exception as e:
                        logger.error(f"Failed to instantiate {name}: {e}")
        except Exception as e:
            logger.error(f"Failed to import module {module_path}: {e}")
        return loaded

    def load_skills_from_package(
        self, package_path: str, graph=None, **kwargs
    ) -> list[str]:
        """动态加载包目录下所有模块中的 Skill 子类"""
        loaded = []
        fs_path = Path(package_path.replace(".", "/"))
        if not fs_path.exists():
            logger.warning(f"Package directory not found: {package_path} -> {fs_path}")
            return loaded
        for py_file in fs_path.glob("**/*.py"):
            if py_file.name.startswith("_"):
                continue
            rel_to_pkg = py_file.relative_to(fs_path)
            module_path = package_path + "." + str(rel_to_pkg).replace("\\", "/").replace("/", ".").replace(".py", "")
            loaded.extend(self.load_skills_from_module(module_path, graph=graph, **kwargs))
        return loaded

    def load_skills_from_config(
        self, skills_config: dict, graph=None, **kwargs
    ) -> list[str]:
        """根据配置字典加载技能
        
        配置格式:
        {
            "modules": ["skills.bash", "skills.file_ops"],
            "packages": ["skills.core"],
            "exclude": ["deprecated_skill"]
        }
        """
        loaded = []
        exclude_set = set(skills_config.get("exclude", []))
        for module_path in skills_config.get("modules", []):
            loaded.extend(self.load_skills_from_module(module_path, graph=graph, **kwargs))
        for package_path in skills_config.get("packages", []):
            loaded.extend(self.load_skills_from_package(package_path, graph=graph, **kwargs))
        if exclude_set:
            for skill_name in exclude_set:
                if skill_name in self._skills:
                    del self._skills[skill_name]
                    loaded = [n for n in loaded if n != skill_name]
                    logger.debug(f"Excluded skill: {skill_name}")
        return loaded
