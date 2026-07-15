import os
import re
from pathlib import Path
from typing import Optional

_YAML_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


class PromptFragment:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.title = ""
        self.description = ""
        self.enabled = True
        self.order = 50
        self.content = ""
        self.id = Path(file_path).stem
        self._parse()

    def _parse(self) -> None:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except (FileNotFoundError, IOError):
            self.content = ""
            return

        m = _YAML_FRONT_RE.match(raw)
        if m:
            yaml_text = m.group(1)
            self.content = m.group(2).strip()
            for line in yaml_text.strip().split("\n"):
                self._parse_yaml_line(line.strip())
        else:
            self.content = raw.strip()

    def _parse_yaml_line(self, line: str) -> None:
        if ":" not in line:
            return
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")

        if key == "title":
            self.title = value
        elif key == "description":
            self.description = value
        elif key == "enabled":
            self.enabled = value.lower() in ("true", "yes", "1")
        elif key == "order":
            try:
                self.order = int(value)
            except ValueError:
                pass


class PromptEngine:
    def __init__(self, prompts_dir: str | None = None):
        if prompts_dir:
            self.prompts_dir = Path(prompts_dir)
        else:
            self.prompts_dir = Path(__file__).parent / "prompts"
        self.fragments: list[PromptFragment] = []
        self._loaded = False

    def load_all(self) -> None:
        self.fragments.clear()
        if not self.prompts_dir.is_dir():
            return
        for fpath in sorted(self.prompts_dir.glob("*.md")):
            fragment = PromptFragment(str(fpath))
            self.fragments.append(fragment)
        self._loaded = True

    def get_enabled(self) -> list[PromptFragment]:
        if not self._loaded:
            self.load_all()
        return sorted(
            [f for f in self.fragments if f.enabled],
            key=lambda f: f.order,
        )

    def build_system_prompt(self, tool_descriptions: Optional[list[str]] = None) -> str:
        sections = []
        for frag in self.get_enabled():
            if frag.title.startswith("一次性模式"):
                continue
            content = frag.content
            if "{tools}" in content:
                if tool_descriptions:
                    content = content.replace(
                        "{tools}", "\n".join(f"- {d}" for d in tool_descriptions)
                    )
                else:
                    content = content.replace("{tools}", "(no tools available)")
            if content:
                sections.append(content)

        return "\n\n".join(sections)

    def build_oneshot_system_prompt(self, phase: str, tool_descriptions: Optional[list[str]] = None) -> str:
        exclude_titles = {"简言模式", "项目总览协议"}
        target = "一次性模式 - 信息收集阶段" if phase == "gather" else "一次性模式 - 执行阶段"
        sections = []
        for frag in sorted(self.fragments, key=lambda f: f.order):
            if not frag.enabled:
                continue
            if frag.title in exclude_titles:
                continue
            if frag.title.startswith("一次性模式") and frag.title != target:
                continue
            content = frag.content
            if "{tools}" in content:
                if tool_descriptions:
                    content = content.replace(
                        "{tools}", "\n".join(f"- {d}" for d in tool_descriptions)
                    )
                else:
                    content = content.replace("{tools}", "(no tools available)")
            if content:
                sections.append(content)
        return "\n\n".join(sections)

    def build_tool_descriptions(self, registry) -> list[str]:
        lines = []
        for skill_def in registry.get_tool_definitions():
            fn = skill_def.function
            name = fn["name"]
            desc = fn.get("description", "")
            params = fn.get("parameters", {}).get("properties", {})
            param_str = ", ".join(params.keys()) if params else ""
            lines.append(f"{name}: {desc}" + (f"  Args: {param_str}" if param_str else ""))
        return lines

    def get_fragment(self, fragment_id: str) -> PromptFragment | None:
        for frag in self.fragments:
            if frag.id == fragment_id:
                return frag
        return None

    def reload(self) -> None:
        self._loaded = False
        self.load_all()

    def summary(self) -> str:
        parts = []
        for frag in sorted(self.fragments, key=lambda f: f.order):
            flag = "✓" if frag.enabled else "✗"
            parts.append(f"  [{flag}] {frag.title} (order={frag.order})")
        return "\n".join(parts)
