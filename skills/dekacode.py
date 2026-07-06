"""
DekaCode工具集线器Skill
连接core和project模块的所有功能

本Skill将原tools/core与tools/project模块完全整合进skills包，
AI Agent运行时可通过skill registry直接调用所有代码分析工具。
"""

import json
from typing import Any

from models import SkillResult
from skill import Skill


class DekaCodeSkill(Skill):
    """DekaCode工具集线器 - 整合core与project模块的全部代码分析能力"""

    @property
    def name(self) -> str:
        return "dekacode"

    @property
    def description(self) -> str:
        return """Code analysis toolkit: batch_bash, symbol_search, read_file, grep, find_def, find_ref, diagnose, fix_imports, diff_lines, summarize, key_files, module_map, snapshot. Pass action + params dict."""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "batch_bash", "symbol_search", "read_file",
                        "grep", "find_def", "find_ref",
                        "diagnose", "fix_imports", "diff_lines",
                        "summarize", "key_files", "module_map", "snapshot"
                    ],
                },
                "params": {
                    "type": "object",
                    "description": "Action args as dict. Keys vary by action: batch_bash→commands[], read_file/grep/find_def/find_ref→query str, diagnose→{file_path,error_message}, fix_imports→file_path, diff_lines→{commit_hash,file_pattern}, summarize→{file_path,project_root,max_files}, key_files/module_map/snapshot→{project_root}",
                },
                "project_root": {
                    "type": "string",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, project_root: str = ".", **kwargs) -> SkillResult:
        try:
            from skills.core import (
                batch_bash, batch_symbol_search,
                smart_read_file, smart_grep,
                find_definition, find_references,
                diagnose_error, fix_imports
            )
        except ImportError as e:
            return SkillResult(success=False, output=f"core import: {e}")
        try:
            from skills.project import (
                git_diff_lines, summarize_file, summarize_project,
                key_files, module_map, create_project_snapshot
            )
        except ImportError as e:
            return SkillResult(success=False, output=f"project import: {e}")

        project_root = project_root or "."
        p = kwargs.get("params") or {}

        def _get(key, default=None):
            return p.get(key) or kwargs.get(key, default)

        if action == "batch_bash":
            cmds = _get("commands") or _get("batch_bash", [])
            if isinstance(cmds, str):
                cmds = [cmds]
            if not cmds:
                return SkillResult(success=False, output="no commands")
            results = batch_bash(cmds, max_workers=3)
            lines = []
            for r in results:
                mark = "✓" if r.success else "✗"
                body = r.stdout.strip() if r.success else (r.stderr.strip() or r.stdout.strip())
                lines.append(f"{mark} {r.command}\n{body}")
            return SkillResult(success=True, output="\n".join(lines))

        elif action == "symbol_search":
            q = _get("query") or _get("symbol_search", "")
            if not q:
                return SkillResult(success=False, output="no query")
            results = batch_symbol_search([q], project_root=project_root)
            matches = results.get(q, [])
            if matches:
                out = "\n".join([f"• {m.file_path}:{m.line}: {m.context}" for m in matches[:30]])
                if len(matches) > 30:
                    out += f"\n... +{len(matches)-30}"
                return SkillResult(success=True, output=out)
            return SkillResult(success=False, output=f"not found: {q}")

        elif action == "read_file":
            fp = _get("file_path") or _get("read_file", "")
            if not fp:
                return SkillResult(success=False, output="no file_path")
            chunks = smart_read_file(fp)
            if not chunks:
                return SkillResult(success=False, output="empty or missing")
            parts = [f"[L{ch.start_line}-{ch.end_line}] {ch.function_name or ch.class_name or ''}\n{ch.content}" for ch in chunks]
            return SkillResult(success=True, output="\n\n".join(parts))

        elif action == "grep":
            gp = p if isinstance(p, dict) else {}
            pat = gp.get("pattern") or kwargs.get("pattern", "")
            fp = gp.get("file_path") or gp.get("path") or kwargs.get("file_path", "")
            ctx = gp.get("context_lines") or gp.get("context", 3)
            if not pat or not fp:
                return SkillResult(success=False, output="need pattern + file_path")
            matches = smart_grep(pat, fp, context_lines=ctx)
            if matches:
                out = "\n".join([f"• {m.file_path}:{m.line}: {m.content.strip()}" for m in matches[:50]])
                if len(matches) > 50:
                    out += f"\n... +{len(matches)-50}"
                return SkillResult(success=True, output=out)
            return SkillResult(success=False, output="no matches")

        elif action == "find_def":
            sym = _get("symbol") or _get("find_def", "")
            if not sym:
                return SkillResult(success=False, output="no symbol")
            locs = find_definition(sym, project_root=project_root)
            if locs:
                return SkillResult(success=True, output="\n".join([f"• {loc.file_path}:{loc.line} ({loc.symbol_type})" for loc in locs]))
            return SkillResult(success=False, output=f"not found: {sym}")

        elif action == "find_ref":
            sym = _get("symbol") or _get("find_ref", "")
            if not sym:
                return SkillResult(success=False, output="no symbol")
            locs = find_references(sym, project_root=project_root)
            if locs:
                out = "\n".join([f"• {loc.file_path}:{loc.line} [{loc.ref_type}] {loc.context.strip()}" for loc in locs[:30]])
                if len(locs) > 30:
                    out += f"\n... +{len(locs)-30}"
                return SkillResult(success=True, output=out)
            return SkillResult(success=False, output=f"not found: {sym}")

        elif action == "diagnose":
            fp = _get("file_path") or ""
            err = _get("error_message") or ""
            if not fp and not err:
                return SkillResult(success=False, output="need file_path or error_message")
            errors = diagnose_error(file_path=fp, error_message=err)
            if errors:
                return SkillResult(success=True, output="\n".join([f"[{e.severity}] {e.error_type}: {e.message}  {e.file_path}:{e.line}  fix: {e.suggestion or '-'}" for e in errors]))
            return SkillResult(success=True, output="no errors")

        elif action == "fix_imports":
            fp = _get("file_path") or _get("fix_imports", "")
            if not fp:
                return SkillResult(success=False, output="no file_path")
            issues = fix_imports(fp, project_root=project_root)
            if issues:
                return SkillResult(success=True, output="\n".join([f"[{iss.issue_type}] {iss.import_name} @ {iss.file_path}:{iss.line}  fix: {iss.suggestion or '-'}" for iss in issues]))
            return SkillResult(success=True, output="no import issues")

        elif action == "diff_lines":
            dp = p if isinstance(p, dict) else {}
            ch = dp.get("commit_hash") or kwargs.get("commit_hash")
            fpat = dp.get("file_pattern") or kwargs.get("file_pattern", "*.py")
            wd = dp.get("workdir") or kwargs.get("workdir", project_root)
            diff = git_diff_lines(commit_hash=ch, file_pattern=fpat, workdir=wd)
            if diff:
                out = ""
                for file, lines in list(diff.items())[:20]:
                    out += f"\n{file}:"
                    for line in lines[:10]:
                        out += f"\n  {line.change_type} L{line.line}: {line.content[:60]}"
                return SkillResult(success=True, output=out)
            return SkillResult(success=False, output="no changes or no git")

        elif action == "summarize":
            sp = p if isinstance(p, dict) else {}
            fp = sp.get("file_path") or kwargs.get("file_path")
            if fp:
                fs = summarize_file(fp)
                out = f"{fs.file_path} {fs.total_lines}L complexity={fs.complexity_score}"
                if fs.functions:
                    out += "\nfuncs: " + ", ".join([getattr(f, 'name', str(f)) for f in fs.functions[:20]])
                if fs.classes:
                    out += "\nclasses: " + ", ".join([getattr(c, 'name', str(c)) for c in fs.classes[:20]])
                return SkillResult(success=True, output=out)
            root = sp.get("project_root") or kwargs.get("project_root", project_root)
            maxf = sp.get("max_files") or kwargs.get("max_files", 20)
            result = summarize_project(root, max_files=maxf)
            return SkillResult(success=True, output=json.dumps(result, ensure_ascii=False, default=str)[:3000])

        elif action == "key_files":
            kp = p if isinstance(p, dict) else {}
            root = kp.get("project_root") or kwargs.get("project_root", project_root)
            maxf = kp.get("max_files") or kwargs.get("max_files", 20)
            files = key_files(root, max_files=maxf)
            if files:
                return SkillResult(success=True, output="\n".join([f"{i+1}. {f.file_path} score={f.importance_score:.2f}" for i, f in enumerate(files)]))
            return SkillResult(success=False, output="no Python files")

        elif action == "module_map":
            mp = p if isinstance(p, dict) else {}
            root = mp.get("project_root") or kwargs.get("project_root", project_root)
            fmt = mp.get("output_format") or kwargs.get("output_format", "dict")
            result = module_map(root, output_format=fmt)
            if fmt == "graphviz":
                return SkillResult(success=True, output=result)
            elif fmt == "json":
                return SkillResult(success=True, output=json.dumps(result, ensure_ascii=False, default=str)[:3000])
            modules = result.get("modules", result) if isinstance(result, dict) else {}
            out = "\n".join([f"• {m} ({info.get('file_path', '?')}) deps={len(info.get('imports',[]))}" for m, info in list(modules.items())[:50]])
            return SkillResult(success=True, output=out)

        elif action == "snapshot":
            sp = p if isinstance(p, dict) else {}
            root = sp.get("project_root") or kwargs.get("project_root", project_root)
            op = sp.get("output_path") or kwargs.get("output_path") or kwargs.get("output_file")
            snap = create_project_snapshot(root)
            if op:
                with open(op, 'w', encoding='utf-8') as f:
                    json.dump(snap, f, ensure_ascii=False, default=str)
                return SkillResult(success=True, output=f"snapshot saved: {op}")
            return SkillResult(success=True, output=json.dumps(snap, ensure_ascii=False, default=str)[:3000])

        return SkillResult(success=False, output=f"unknown action: {action}")
