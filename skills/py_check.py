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
        return "Check Python syntax via AST"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
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


class AstSummarySkill(Skill):
    @property
    def name(self) -> str:
        return "ast_summary"

    @property
    def description(self) -> str:
        return "List class/func defs (line nums, no body)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
            },
            "required": ["file_path"],
        }

    async def execute(self, file_path: str, **kwargs) -> SkillResult:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=file_path)

            def _walk(node: ast.AST, indent: str = "") -> list[str]:
                results: list[str] = []
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        results.append(f"{indent}{child.lineno}: def {child.name}")
                    elif isinstance(child, ast.ClassDef):
                        results.append(f"{indent}{child.lineno}: class {child.name}")
                        results.extend(_walk(child, indent + "  "))
                return results

            lines: list[str] = [f"# {file_path}"]
            lines.extend(_walk(tree))
            if len(lines) == 1:
                lines.append("(no class/function definitions found)")
            return SkillResult(success=True, output="\n".join(lines))
        except SyntaxError as e:
            return SkillResult(success=False, output=f"Syntax error: {e}")
        except Exception as e:
            return SkillResult(success=False, output=str(e))
