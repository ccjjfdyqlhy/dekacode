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
        return """DekaCode代码分析工具集
支持操作：
- batch_bash: 批量并行执行bash命令
- symbol_search: 批量符号搜索
- read_file: 智能读取文件(按语义分块)
- grep: 智能grep(带上下文)
- find_def: 查找符号定义位置
- find_ref: 查找符号引用位置
- diagnose: 诊断代码错误
- fix_imports: 检测import问题
- diff_lines: 获取git diff变更行
- summarize: 文件/项目摘要
- key_files: 识别关键文件
- module_map: 生成模块依赖图
- snapshot: 创建项目快照
"""

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
                    "description": "操作类型",
                },
                "batch_bash": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "批量执行的命令列表 (action=batch_bash时使用)",
                },
                "symbol_search": {
                    "type": "string",
                    "description": "搜索的符号名称 (action=symbol_search时使用)",
                },
                "read_file": {
                    "type": "string",
                    "description": "要读取的文件路径 (action=read_file时使用)",
                },
                "grep": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "file_path": {"type": "string"},
                        "context_lines": {"type": "integer"},
                    },
                    "description": "grep参数 (action=grep时使用)",
                },
                "find_def": {
                    "type": "string",
                    "description": "要查找定义的符号名 (action=find_def时使用)",
                },
                "find_ref": {
                    "type": "string",
                    "description": "要查找引用的符号名 (action=find_ref时使用)",
                },
                "diagnose": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "error_message": {"type": "string"},
                    },
                    "description": "诊断参数 (action=diagnose时使用)",
                },
                "fix_imports": {
                    "type": "string",
                    "description": "要检测的文件路径 (action=fix_imports时使用)",
                },
                "diff_lines": {
                    "type": "object",
                    "properties": {
                        "commit_hash": {"type": "string"},
                        "file_pattern": {"type": "string"},
                        "workdir": {"type": "string"},
                    },
                    "description": "diff参数 (action=diff_lines时使用)",
                },
                "summarize": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "project_root": {"type": "string"},
                        "max_files": {"type": "integer"},
                    },
                    "description": "摘要参数 (action=summarize时使用, 提供file_path则摘要单文件, 否则摘要整个项目)",
                },
                "key_files": {
                    "type": "object",
                    "properties": {
                        "project_root": {"type": "string"},
                        "max_files": {"type": "integer"},
                    },
                    "description": "关键文件参数 (action=key_files时使用)",
                },
                "module_map": {
                    "type": "object",
                    "properties": {
                        "project_root": {"type": "string"},
                        "output_format": {"type": "string", "enum": ["dict", "json", "graphviz"]},
                    },
                    "description": "模块图参数 (action=module_map时使用)",
                },
                "snapshot": {
                    "type": "object",
                    "properties": {
                        "project_root": {"type": "string"},
                        "output_path": {"type": "string"},
                    },
                    "description": "快照参数 (action=snapshot时使用)",
                },
                "project_root": {
                    "type": "string",
                    "description": "项目根目录 (默认当前目录)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, project_root: str = ".", **kwargs) -> SkillResult:
        try:
            # 导入模块(带错误处理)
            try:
                from skills.core import (
                    batch_bash, batch_symbol_search,
                    smart_read_file, smart_grep,
                    find_definition, find_references,
                    diagnose_error, fix_imports
                )
            except ImportError as e:
                return SkillResult(success=False, output=f"核心模块导入失败: {str(e)}")

            try:
                from skills.project import (
                    git_diff_lines, summarize_file, summarize_project,
                    key_files, module_map, create_project_snapshot
                )
            except ImportError as e:
                return SkillResult(success=False, output=f"项目模块导入失败: {str(e)}")

            project_root = project_root or "."

            # ---- batch_bash: 批量执行bash命令 ----
            if action == "batch_bash":
                commands = kwargs.get("batch_bash", [])
                if isinstance(commands, str):
                    commands = [commands]
                if not commands:
                    return SkillResult(success=False, output="未提供命令")
                results = batch_bash(commands, max_workers=3)
                lines = []
                for r in results:
                    mark = "✓" if r.success else "✗"
                    body = r.stdout.strip() if r.success else (r.stderr.strip() or r.stdout.strip())
                    lines.append(f"{mark} {r.command}\n{body}")
                return SkillResult(success=True, output="\n".join(lines))

            # ---- symbol_search: 批量符号搜索 ----
            elif action == "symbol_search":
                query_param = kwargs.get("symbol_search", "")
                query = query_param.get("symbol", "") if isinstance(query_param, dict) else query_param
                if not query:
                    return SkillResult(success=False, output="未提供搜索符号")
                results = batch_symbol_search([query], project_root=project_root)
                matches = results.get(query, [])
                if matches:
                    output = "\n".join([
                        f"• {m.file_path}:{m.line}: {m.context}"
                        for m in matches[:30]
                    ])
                    if len(matches) > 30:
                        output += f"\n... 共 {len(matches)} 处匹配"
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=False, output=f"未找到符号: {query}")

            # ---- read_file: 智能读取文件(按语义分块) ----
            elif action == "read_file":
                read_param = kwargs.get("read_file", "")
                file_path = read_param.get("file_path", "") if isinstance(read_param, dict) else read_param
                if not file_path:
                    return SkillResult(success=False, output="未提供文件路径")
                chunks = smart_read_file(file_path)
                if not chunks:
                    return SkillResult(success=False, output="文件为空或不存在")
                parts = []
                for ch in chunks:
                    header = f"[行 {ch.start_line}-{ch.end_line}]"
                    if ch.is_function and ch.function_name:
                        header += f" 函数: {ch.function_name}"
                    elif ch.is_class and ch.class_name:
                        header += f" 类: {ch.class_name}"
                    parts.append(f"{header}\n{ch.content}")
                return SkillResult(success=True, output="\n\n".join(parts))

            # ---- grep: 智能grep(带上下文) ----
            elif action == "grep":
                grep_params = kwargs.get("grep", {})
                pattern = grep_params.get("pattern", "")
                file_path = grep_params.get("file_path") or grep_params.get("path", "")
                context_lines = grep_params.get("context_lines", 3)
                if not pattern or not file_path:
                    return SkillResult(success=False, output="需要提供 pattern 和 file_path")
                matches = smart_grep(pattern, file_path, context_lines=context_lines)
                if matches:
                    output = "\n".join([
                        f"• {m.file_path}:{m.line}: {m.content.strip()}"
                        for m in matches[:50]
                    ])
                    if len(matches) > 50:
                        output += f"\n... 共 {len(matches)} 条匹配"
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=False, output="未找到匹配")

            # ---- find_def: 查找定义 ----
            elif action == "find_def":
                find_param = kwargs.get("find_def", "")
                symbol = find_param.get("symbol", "") if isinstance(find_param, dict) else find_param
                if not symbol:
                    return SkillResult(success=False, output="未提供符号名")
                locations = find_definition(symbol, project_root=project_root)
                if locations:
                    output = "\n".join([
                        f"• {loc.file_path}:{loc.line}  ({loc.symbol_type})"
                        for loc in locations
                    ])
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=False, output=f"未找到定义: {symbol}")

            # ---- find_ref: 查找引用 ----
            elif action == "find_ref":
                find_param = kwargs.get("find_ref", "")
                symbol = find_param.get("symbol", "") if isinstance(find_param, dict) else find_param
                if not symbol:
                    return SkillResult(success=False, output="未提供符号名")
                locations = find_references(symbol, project_root=project_root)
                if locations:
                    output = "\n".join([
                        f"• {loc.file_path}:{loc.line}  [{loc.ref_type}] {loc.context.strip()}"
                        for loc in locations[:30]
                    ])
                    if len(locations) > 30:
                        output += f"\n... 共 {len(locations)} 处引用"
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=False, output=f"未找到引用: {symbol}")

            # ---- diagnose: 诊断代码错误 ----
            elif action == "diagnose":
                diag_params = kwargs.get("diagnose", {})
                file_path = diag_params.get("file_path", "")
                error_message = diag_params.get("error_message")
                if not file_path and not error_message:
                    return SkillResult(success=False, output="需要提供 file_path 或 error_message")
                errors = diagnose_error(file_path=file_path, error_message=error_message)
                if errors:
                    output = "\n".join([
                        f"• [{e.severity}] {e.error_type}: {e.message}\n"
                        f"  位置: {e.file_path}:{e.line}\n"
                        f"  修复建议: {e.suggestion or '无'}"
                        for e in errors
                    ])
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=True, output="未检测到错误")

            # ---- fix_imports: 检测import问题 ----
            elif action == "fix_imports":
                fix_param = kwargs.get("fix_imports", "")
                file_path = fix_param.get("file_path", "") if isinstance(fix_param, dict) else fix_param
                if not file_path:
                    return SkillResult(success=False, output="未提供文件路径")
                issues = fix_imports(file_path, project_root=project_root)
                if issues:
                    output = "\n".join([
                        f"• [{iss.issue_type}] {iss.import_name}\n"
                        f"  位置: {iss.file_path}:{iss.line}\n"
                        f"  建议: {iss.suggestion or '无'}"
                        for iss in issues
                    ])
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=True, output="未检测到import问题")

            # ---- diff_lines: 获取git diff变更行 ----
            elif action == "diff_lines":
                diff_params = kwargs.get("diff_lines", {})
                commit_hash = diff_params.get("commit_hash")
                file_pattern = diff_params.get("file_pattern", "*.py")
                workdir = diff_params.get("workdir", project_root)
                diff = git_diff_lines(commit_hash=commit_hash, file_pattern=file_pattern, workdir=workdir)
                if diff:
                    output = ""
                    for file, lines in list(diff.items())[:20]:
                        output += f"\n{file}:\n"
                        for line in lines[:10]:
                            output += f"  {line.change_type:8} 行{line.line}: {line.content[:60]}\n"
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=False, output="无变更或无git仓库")

            # ---- summarize: 文件/项目摘要 ----
            elif action == "summarize":
                sum_params = kwargs.get("summarize", {})
                file_path = sum_params.get("file_path")
                if file_path:
                    fs = summarize_file(file_path)
                    output = f"文件: {fs.file_path}\n总行数: {fs.total_lines}\n复杂度: {fs.complexity_score}\n\n"
                    if fs.functions:
                        output += "函数:\n" + "\n".join([
                            f"  - {getattr(f, 'name', f)} (行{getattr(f, 'start_line', '?')})"
                            for f in fs.functions[:20]
                        ]) + "\n\n"
                    if fs.classes:
                        output += "类:\n" + "\n".join([
                            f"  - {getattr(c, 'name', c)}"
                            for c in fs.classes[:20]
                        ]) + "\n\n"
                    if fs.key_features:
                        output += "关键特性:\n" + "\n".join([
                            f"  - {feat}" for feat in fs.key_features
                        ])
                    return SkillResult(success=True, output=output)
                else:
                    root = sum_params.get("project_root", project_root)
                    max_files = sum_params.get("max_files", 20)
                    result = summarize_project(root, max_files=max_files)
                    return SkillResult(success=True, output=f"项目摘要:\n{json.dumps(result, ensure_ascii=False, indent=2, default=str)}")

            # ---- key_files: 识别关键文件 ----
            elif action == "key_files":
                kf_params = kwargs.get("key_files", {})
                root = kf_params.get("project_root", project_root)
                max_files = kf_params.get("max_files", 20)
                files = key_files(root, max_files=max_files)
                if files:
                    output = "关键文件:\n" + "\n".join([
                        f"{i+1}. {f.file_path}\n   重要性: {f.importance_score:.2f}\n   原因: {', '.join(f.reasons)}"
                        for i, f in enumerate(files)
                    ])
                    return SkillResult(success=True, output=output)
                else:
                    return SkillResult(success=False, output="未找到Python文件")

            # ---- module_map: 生成模块依赖图 ----
            elif action == "module_map":
                mm_params = kwargs.get("module_map", {})
                root = mm_params.get("project_root", project_root)
                fmt = mm_params.get("output_format", "dict")
                result = module_map(root, output_format=fmt)
                if fmt == "graphviz":
                    return SkillResult(success=True, output=f"Graphviz代码:\n{result}")
                elif fmt == "json":
                    return SkillResult(success=True, output=json.dumps(result, ensure_ascii=False, indent=2, default=str))
                else:
                    # dict 格式: {'modules': {name: {file_path, imports, imported_by, exports, metrics}}}
                    if isinstance(result, dict):
                        modules = result.get("modules", result) if "modules" in result else result
                        lines = []
                        count = 0
                        for mod, info in modules.items():
                            if count >= 50:
                                break
                            count += 1
                            if isinstance(info, dict):
                                imports = info.get("imports", [])
                                imported_by = info.get("imported_by", [])
                                lines.append(
                                    f"• {mod} ({info.get('file_path', '?')})\n"
                                    f"  依赖: {', '.join(imports[:10]) if imports else '(无)'}\n"
                                    f"  被引用: {', '.join(imported_by[:10]) if imported_by else '(无)'}"
                                )
                            else:
                                lines.append(f"• {mod} -> {info}")
                        output = "模块依赖图:\n" + "\n".join(lines)
                        total = len(modules)
                        if total > 50:
                            output += f"\n... 共 {total} 个模块(仅显示前50个)"
                        return SkillResult(success=True, output=output)
                    else:
                        return SkillResult(success=True, output=str(result))

            # ---- snapshot: 创建项目快照 ----
            elif action == "snapshot":
                snap_params = kwargs.get("snapshot", {})
                root = snap_params.get("project_root", project_root)
                output_path = snap_params.get("output_path") or snap_params.get("output_file")
                snapshot = create_project_snapshot(root)
                if output_path:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)
                    return SkillResult(success=True, output=f"快照已保存到: {output_path}")
                else:
                    output = f"项目快照 ({root}):\n\n"
                    output += json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)[:3000]
                    return SkillResult(success=True, output=output)

            else:
                return SkillResult(success=False, output=f"未知操作: {action}")

        except Exception as e:
            import traceback
            error = f"{str(e)}\n{traceback.format_exc()}"
            return SkillResult(success=False, output=error)
