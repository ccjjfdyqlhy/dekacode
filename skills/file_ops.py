import glob as glob_module
import os
import re

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
        return "Read the contents of a file (supports line range: file.py:10-30)"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "File path, optionally with line range (e.g. main.py:10-30)",
            },
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
                prefix = f"# {path} lines {s+1}-{e} ({total_lines} total)\n"
                content = prefix + content
            else:
                content = "".join(lines)
                total = len(content)
                content = f"# {path} ({total_lines} lines, {total} chars)\n" + content

            if total > 30000:
                content = content[:30000] + f"\n\n[...{total} chars total, truncated to 30000]"
            return SkillResult(success=True, output=content)
        except Exception as e:
            return SkillResult(success=False, output=str(e))


class WriteFileSkill(Skill):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file (overwrites existing content)"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file",
            },
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
        return "Find files matching a glob pattern"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g. '**/*.py')",
            },
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
        return "Search file contents using a regular expression"

    @property
    def parameters(self) -> dict:
        return {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for",
            },
            "include": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py')",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search (default: current directory)",
            },
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
