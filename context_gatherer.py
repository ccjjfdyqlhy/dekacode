import os
import re
import subprocess
from dataclasses import dataclass, field


_REQ_RE = re.compile(r'(?:^|\s)@req\s+(\S+)')
_SYM_RE = re.compile(r'(?:^|\s)@sym\s+(\S+)')
_GREP_RE = re.compile(r'(?:^|\s)@grep\s+"([^"]+)"(?:\s+(\S+))?')
_LS_RE = re.compile(r'(?:^|\s)@ls\s+(\S+)')
_TREE_RE = re.compile(r'(?:^|\s)@tree(?=\s|$)')


@dataclass
class ParseResult:
    clean_input: str = ""
    context_block: str = ""
    directives_found: bool = False
    directive_kinds: list[str] = field(default_factory=list)


@dataclass
class Directive:
    kind: str  # req / sym / grep / ls / tree
    arg: str = ""
    glob: str = ""


class ContextGatherer:

    MAX_FILE_LINES = 500
    MAX_FILE_SIZE = 200 * 1024
    MAX_BLOCK_SIZE = 100_000

    def __init__(self, project_root: str, graph=None):
        self.project_root = project_root
        self.graph = graph

    def parse(self, user_input: str) -> ParseResult:
        directives = self._extract(user_input)
        clean = self._strip_directives(user_input)
        if not directives:
            return ParseResult(clean_input=clean, context_block="", directives_found=False)
        kinds = [d.kind for d in directives]
        block = self._execute(directives)
        if len(block) > self.MAX_BLOCK_SIZE:
            block = block[:self.MAX_BLOCK_SIZE] + "\n\n... [context truncated]"
        return ParseResult(clean_input=clean, context_block=block, directives_found=True, directive_kinds=kinds)

    def _extract(self, text: str) -> list[Directive]:
        directives = []
        for m in _REQ_RE.finditer(text):
            directives.append(Directive(kind="req", arg=m.group(1).strip()))
        for m in _SYM_RE.finditer(text):
            directives.append(Directive(kind="sym", arg=m.group(1).strip()))
        for m in _GREP_RE.finditer(text):
            pat = m.group(1)
            glob = m.group(2).strip() if m.lastindex and m.group(2) else ""
            directives.append(Directive(kind="grep", arg=pat, glob=glob))
        for m in _LS_RE.finditer(text):
            directives.append(Directive(kind="ls", arg=m.group(1).strip()))
        for m in _TREE_RE.finditer(text):
            directives.append(Directive(kind="tree"))
        return directives

    @staticmethod
    def _strip_directives(text: str) -> str:
        spans = []
        for m in _REQ_RE.finditer(text):
            spans.append((m.start(), m.end()))
        for m in _SYM_RE.finditer(text):
            spans.append((m.start(), m.end()))
        for m in _GREP_RE.finditer(text):
            spans.append((m.start(), m.end()))
        for m in _LS_RE.finditer(text):
            spans.append((m.start(), m.end()))
        for m in _TREE_RE.finditer(text):
            spans.append((m.start(), m.end()))
        if not spans:
            return text.strip()
        spans.sort()
        result = []
        pos = 0
        for s, e in spans:
            if s > pos:
                result.append(text[pos:s])
            pos = e
        if pos < len(text):
            result.append(text[pos:])
        return "".join(result).strip()

    def _execute(self, directives: list[Directive]) -> str:
        blocks: list[str] = []
        for d in directives:
            try:
                if d.kind == "req":
                    text = self._exec_req(d.arg)
                elif d.kind == "sym":
                    text = self._exec_sym(d.arg)
                elif d.kind == "grep":
                    text = self._exec_grep(d.arg, d.glob)
                elif d.kind == "ls":
                    text = self._exec_ls(d.arg)
                elif d.kind == "tree":
                    text = self._exec_tree()
                else:
                    continue
                if text:
                    blocks.append(text)
            except Exception as e:
                blocks.append(f"## @{d.kind} ERROR: {e}")
        return "\n\n".join(blocks)

    def _exec_req(self, path: str) -> str:
        abspath = path if os.path.isabs(path) else os.path.join(self.project_root, path)
        abspath = os.path.normpath(abspath)
        if not os.path.isfile(abspath):
            return f"## @req: {path}\n[ERROR] File not found: {abspath}"
        size = os.path.getsize(abspath)
        if size > self.MAX_FILE_SIZE:
            return f"## @req: {path}\n[SKIPPED] File too large ({size} bytes > {self.MAX_FILE_SIZE})"
        try:
            with open(abspath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return f"## @req: {path}\n[ERROR] {e}"
        if len(lines) > self.MAX_FILE_LINES:
            lines = lines[:self.MAX_FILE_LINES]
            lines.append(f"\n... [truncated at {self.MAX_FILE_LINES} lines]")
        content = "".join(lines)
        header = f"## File: {path}  ({abspath})"
        return f"{header}\n```\n{content.rstrip()}\n```"

    def _exec_sym(self, symbol: str) -> str:
        if not self.graph:
            return f"## @sym: {symbol}\n[SKIPPED] No code graph available"
        sym = self.graph.get(symbol)
        if not sym:
            return f"## @sym: {symbol}\n[NOT FOUND] Symbol not in code graph"
        fpath = sym.file_path
        if not os.path.isabs(fpath):
            candidates = [f for f in self.graph.files if f.endswith(fpath)]
            fpath = candidates[0] if candidates else fpath
        if not os.path.isfile(fpath):
            return f"## @sym: {symbol}  ({sym.file_path}:{sym.line})\n[ERROR] Source file not found"
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return f"## @sym: {symbol}\n[ERROR] {e}"
        start = max(0, sym.line - 2)
        end = min(len(lines), start + 30)
        source = "".join(lines[start:end])
        return f"## Symbol: {sym.signature}  ({sym.file_path}:{sym.line})\n```\n{source.rstrip()}\n```"

    def _exec_grep(self, pattern: str, glob: str) -> str:
        cmd = ["rg", "-n", "--no-heading", pattern]
        if glob:
            cmd.extend(["-g", glob])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
                cwd=self.project_root,
            )
        except subprocess.TimeoutExpired:
            return f"## @grep: /{pattern}/  {glob}\n[TIMEOUT] grep took too long"
        except FileNotFoundError:
            return f"## @grep: /{pattern}/  {glob}\n[SKIPPED] ripgrep (rg) not installed"
        output = result.stdout
        if not output:
            return f"## @grep: /{pattern}/  {glob}\n[EMPTY] No matches found"
        limit = 5000
        if len(output) > limit:
            output = output[:limit] + f"\n... [truncated, {len(result.stdout)} total chars]"
        return f"## Grep: /{pattern}/  {glob}\n```\n{output.rstrip()}\n```"

    def _exec_ls(self, path: str) -> str:
        abspath = path if os.path.isabs(path) else os.path.join(self.project_root, path)
        abspath = os.path.normpath(abspath)
        if not os.path.isdir(abspath):
            return f"## @ls: {path}\n[ERROR] Directory not found: {abspath}"
        try:
            entries = sorted(os.listdir(abspath))
        except Exception as e:
            return f"## @ls: {path}\n[ERROR] {e}"
        lines = []
        for e in entries:
            full = os.path.join(abspath, e)
            suffix = "/" if os.path.isdir(full) else ""
            lines.append(f"{e}{suffix}")
        return f"## Directory: {path}\n```\n" + "\n".join(lines) + "\n```"

    def _exec_tree(self) -> str:
        project = self.project_root
        lines = [os.path.basename(project) + "/"]
        try:
            for root, dirs, files in os.walk(project):
                if ".git" in dirs:
                    dirs.remove(".git")
                if "__pycache__" in dirs:
                    dirs.remove("__pycache__")
                if ".dekacode" in dirs:
                    dirs.remove(".dekacode")
                if ".venv" in dirs:
                    dirs.remove(".venv")
                if "node_modules" in dirs:
                    dirs.remove("node_modules")
                rel = os.path.relpath(root, project)
                if rel == ".":
                    depth = 0
                else:
                    depth = rel.count(os.sep) + 1
                indent = "  " * depth
                for d in dirs:
                    lines.append(f"{indent}{d}/")
                for f in files:
                    lines.append(f"{indent}{f}")
            return f"## Project Tree\n```\n" + "\n".join(lines) + "\n```"
        except Exception as e:
            return f"## @tree\n[ERROR] {e}"
