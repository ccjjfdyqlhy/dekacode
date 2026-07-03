import ast
import os

from skill import Skill
from models import SkillResult


class PyCheckSkill(Skill):
    @property
    def name(self) -> str:
        return "py_check"

    @property
    def description(self) -> str:
        return "Check Python files for syntax errors using AST parsing"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to check (e.g. ['main.py', 'utils.py'])",
                },
            },
            "required": ["files"],
        }

    async def execute(self, files: list[str], **kwargs) -> SkillResult:
        if not files:
            return SkillResult(success=True, output="No files provided")

        passed = []
        failed = []

        for fpath in files:
            if not os.path.isfile(fpath):
                failed.append(f"  ✗ {fpath}  (file not found)")
                continue

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    source = f.read()
            except (IOError, UnicodeDecodeError) as e:
                failed.append(f"  ✗ {fpath}  (read error: {e})")
                continue

            try:
                ast.parse(source, filename=fpath)
                passed.append(fpath)
            except SyntaxError as e:
                failed.append(f"  ✗ {fpath}:{e.lineno}: {e.msg}")

        lines = []
        if passed:
            lines.append(f"({len(passed)} passed)")
            for f in passed:
                lines.append(f"  ✓ {f}")
        if failed:
            lines.append(f"({len(failed)} failed)")
            lines.extend(failed)

        return SkillResult(success=len(failed) == 0, output="\n".join(lines))
