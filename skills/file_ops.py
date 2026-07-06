import asyncio
import fnmatch
import glob as glob_module
import os
import re
from pathlib import Path

from models import SkillResult
from skill import Skill


_LINE_RANGE_RE = re.compile(r"^(.+):(\d+)?-(\d+)?$")


def _parse_file_ref(file_path: str) -> tuple[str, int | None, int | None]:
    m = _LINE_RANGE_RE.match(file_path)
    if m:
        path = m.group(1)
        start = int(m.group(2)) if m.group(2) else None
        end = int(m.group(3)) if m.group(3) else None
        return path, start, end
    return file_path, None, None


class ReadFileSkill(Skill):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read file (line range: file.py:10-30)"

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
            path, start_line, end_line = _parse_file_ref(file_path)
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            total_lines = len(lines)

            if start_line is not None or end_line is not None:
                s = (start_line or 1) - 1
                e = end_line or total_lines
                selected = lines[s:e]
                content = "".join(selected)
                total = len(content)
                content = f"# {path}:{s+1}-{e}\n{content}"
            else:
                content = "".join(lines)
                total = len(content)
                content = f"# {path} ({total_lines}L)\n{content}"

            if total > 30000:
                content = content[:30000] + f"\n[...+{total-30000}c]"
            return SkillResult(success=True, output=content)
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class WriteFileSkill(Skill):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write file (overwrite)"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
    }

    async def execute(self, file_path: str, content: str, **kwargs) -> SkillResult:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return SkillResult(success=True, output=f"Written {len(content)} bytes to {file_path}")
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class GlobSkill(Skill):
    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files by glob"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
        },
        "required": ["pattern"],
    }

    async def execute(self, pattern: str, **kwargs) -> SkillResult:
        try:
            matches = glob_module.glob(pattern, recursive=True)
            if not matches:
                return SkillResult(success=True, output="No files matched")
            output = "\n".join(matches)
            total = len(output)
            if total > 10000:
                output = output[:10000] + f"\n\n[...{len(matches)} files matched, {total} chars total, truncated to 10000]"
            return SkillResult(success=True, output=f"({len(matches)} files)\n{output}")
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class GrepSkill(Skill):
    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Regex search file contents"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "include": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
    }

    async def execute(self, pattern: str, include: str | None = None, path: str = ".", **kwargs) -> SkillResult:
        try:
            matches: list[str] = []
            compiled = re.compile(pattern)

            if include:
                full_pattern = os.path.join(path, include)
                candidates = glob_module.glob(full_pattern, recursive=True)
                for fpath in candidates:
                    if not os.path.isfile(fpath):
                        continue
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            for i, line in enumerate(f, 1):
                                if compiled.search(line):
                                    matches.append(f"{fpath}:{i}: {line.rstrip()}")
                    except Exception:
                        continue
            else:
                for root, _dirs, files in os.walk(path):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                for i, line in enumerate(f, 1):
                                    if compiled.search(line):
                                        matches.append(f"{fpath}:{i}: {line.rstrip()}")
                        except Exception:
                            continue

            if not matches:
                return SkillResult(success=True, output="No matches found")
            output = "\n".join(matches)
            total = len(output)
            if len(output) > 20000:
                output = output[:20000] + f"\n\n[...{len(matches)} matches, {total} chars total, truncated to 20000]"
            return SkillResult(success=True, output=f"({len(matches)} matches)\n{output}")
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class EditFileSkill(Skill):
    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit file via search-and-replace"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["file_path", "old_string", "new_string"],
        }

    async def execute(self, file_path: str, old_string: str, new_string: str, **kwargs) -> SkillResult:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            occurrences = content.count(old_string)
            if occurrences == 0:
                return SkillResult(success=False, output=f"edit_file: string not found in {file_path}")
            if occurrences > 1:
                return SkillResult(success=False, output=f"edit_file: found {occurrences} occurrences in {file_path}, must be unique — provide more surrounding context")
            new_content = content.replace(old_string, new_string)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            old_lines = old_string.count("\n") + 1
            new_lines = new_string.count("\n") + 1
            return SkillResult(success=True, output=f"Edited {file_path}: {old_lines} lines → {new_lines} lines")
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class ReadFilesSkill(Skill):
    @property
    def name(self) -> str:
        return "read_files"

    @property
    def description(self) -> str:
        return "Read multiple files at once"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["paths"],
        }

    async def execute(self, paths: list[str], **kwargs) -> SkillResult:
        results: list[str] = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                total = len(content)
                if total > 30000:
                    content = content[:30000] + f"\n\n[...{total} chars total, truncated to 30000]"
                results.append(f"# {path} ({total} chars)\n{content}")
            except Exception as e:
                results.append(f"# {path}\n[Error] {e}")
        output = "\n\n".join(results)
        if len(output) > 50000:
            output = output[:50000] + f"\n\n[...total output {len(output)} chars, truncated to 50000]"
        return SkillResult(success=True, output=output)


class GrepContextSkill(Skill):
    @property
    def name(self) -> str:
        return "grep_context"

    @property
    def description(self) -> str:
        return "Grep with context lines"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "include": {"type": "string"},
                "path": {"type": "string"},
                "context": {"type": "integer"},
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, include: str | None = None, path: str = ".", context: int = 3, **kwargs) -> SkillResult:
        try:
            compiled = re.compile(pattern)
            matches: list[str] = []
            if include:
                full_pattern = os.path.join(path, include)
                candidates = glob_module.glob(full_pattern, recursive=True)
            else:
                candidates = []
                for root, _dirs, files in os.walk(path):
                    for f in files:
                        candidates.append(os.path.join(root, f))

            for fpath in sorted(candidates):
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    for i, line in enumerate(lines, 1):
                        if compiled.search(line):
                            start = max(0, i - 1 - context)
                            end = min(len(lines), i + context)
                            ctx = []
                            for j in range(start, end):
                                marker = ">" if j == i - 1 else " "
                                ctx.append(f"{marker} {j+1}:{lines[j].rstrip()}")
                            matches.append(f"# {fpath}:{i}\n" + "\n".join(ctx))
                except Exception:
                    continue

            if not matches:
                return SkillResult(success=True, output="No matches found")
            output = "\n\n".join(matches)
            total = len(output)
            if total > 30000:
                output = output[:30000] + f"\n\n[...{len(matches)} matches, {total} chars total, truncated to 30000]"
            return SkillResult(success=True, output=f"({len(matches)} matches)\n{output}")
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class ListDirSkill(Skill):
    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List dir tree"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "depth": {"type": "integer"},
                "include": {"type": "string"},
            },
        }

    async def execute(self, path: str = ".", depth: int = 3, include: str | None = None, **kwargs) -> SkillResult:
        try:
            root_path = Path(path).resolve()
            lines: list[str] = [f"# {root_path}"]

            def _walk(dir_path: Path, current_depth: int) -> None:
                if current_depth > depth:
                    return
                try:
                    entries = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                except PermissionError:
                    return
                for entry in entries:
                    if entry.name.startswith(".") or entry.name in ("__pycache__", "node_modules", ".git"):
                        continue
                    indent = "  " * (current_depth - 1)
                    if entry.is_dir():
                        lines.append(f"{indent}{entry.name}/")
                        _walk(entry, current_depth + 1)
                    elif entry.is_file():
                        if include and not fnmatch.fnmatch(entry.name, include):
                            continue
                        lines.append(f"{indent}{entry.name}")

            _walk(root_path, 1)
            output = "\n".join(lines)
            if len(output) > 20000:
                output = output[:20000] + f"\n[...truncated, total {len(output)} chars]"
            return SkillResult(success=True, output=output)
        except Exception as e:
            return SkillResult(success=False, output=str(e))
