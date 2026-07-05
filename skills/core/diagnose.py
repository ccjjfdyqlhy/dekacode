"""
错误诊断模块
- diagnose_error: 诊断错误
- fix_imports: 修复import问题
"""

import re
import ast
import os
import sys
from typing import List, Dict, Optional, Tuple, Any, Set
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ErrorInfo:
    """错误信息"""
    file_path: str
    line: int
    column: int
    error_type: str
    message: str
    suggestion: Optional[str] = None
    severity: str = "error"  # error, warning, info


@dataclass
class ImportIssue:
    """Import问题"""
    file_path: str
    line: int
    import_name: str
    issue_type: str  # 'missing', 'unused', 'wrong_name', 'circular'
    suggestion: Optional[str] = None


def diagnose_error(
    file_path: str,
    error_message: Optional[str] = None
) -> List[ErrorInfo]:
    """
    诊断错误

    Args:
        file_path: 文件路径
        error_message: 错误信息(可选)

    Returns:
        错误信息列表
    """
    errors = []

    if not os.path.exists(file_path):
        errors.append(ErrorInfo(
            file_path=file_path,
            line=0,
            column=0,
            error_type='FileNotFound',
            message=f'File not found: {file_path}',
            suggestion='Check file path'
        ))
        return errors

    # 读取文件内容
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except:
        errors.append(ErrorInfo(
            file_path=file_path,
            line=0,
            column=0,
            error_type='ReadError',
            message='Failed to read file',
            suggestion='Check file permissions'
        ))
        return errors

    # Python语法检查
    if file_path.endswith('.py'):
        try:
            ast.parse(content)
        except SyntaxError as e:
            errors.append(ErrorInfo(
                file_path=file_path,
                line=e.lineno or 0,
                column=e.offset or 0,
                error_type='SyntaxError',
                message=str(e),
                suggestion='Check syntax around this line'
            ))

    # 分析提供的错误信息
    if error_message:
        parsed = _parse_error_message(error_message, file_path, content)
        if parsed:
            errors.append(parsed)

    # 常见问题检测
    common_errors = _detect_common_errors(file_path, content)
    errors.extend(common_errors)

    return errors


def _parse_error_message(
    error_message: str,
    file_path: str,
    content: str
) -> Optional[ErrorInfo]:
    """解析错误信息"""
    lines = content.split('\n')

    # NameError
    match = re.search(r"NameError: name '(\w+)' is not defined", error_message)
    if match:
        name = match.group(1)
        line_num = _find_line_with_name(lines, name)
        return ErrorInfo(
            file_path=file_path,
            line=line_num,
            column=0,
            error_type='NameError',
            message=f"Name '{name}' is not defined",
            suggestion=f"Define '{name}' or import it"
        )

    # AttributeError
    match = re.search(r"AttributeError: '(\w+)' object has no attribute '(\w+)'", error_message)
    if match:
        obj_type, attr = match.groups()
        line_num = _find_line_with_attr(lines, attr)
        return ErrorInfo(
            file_path=file_path,
            line=line_num,
            column=0,
            error_type='AttributeError',
            message=f"'{obj_type}' has no attribute '{attr}'",
            suggestion=f"Check attribute name or define method '{attr}'"
        )

    # ImportError
    match = re.search(r"(ImportError|ModuleNotFoundError): No module named '([^']+)'", error_message)
    if match:
        module_name = match.group(2)
        line_num = _find_import_line(lines, module_name)
        return ErrorInfo(
            file_path=file_path,
            line=line_num,
            column=0,
            error_type='ImportError',
            message=f"No module named '{module_name}'",
            suggestion=f"Install module or check import path"
        )

    # TypeError
    match = re.search(r"TypeError: ([^+]+)", error_message)
    if match:
        return ErrorInfo(
            file_path=file_path,
            line=0,
            column=0,
            error_type='TypeError',
            message=match.group(1),
            suggestion='Check argument types'
        )

    return None


def _find_line_with_name(lines: List[str], name: str) -> int:
    """查找包含名称的行"""
    for i, line in enumerate(lines, 1):
        if re.search(rf'\b{re.escape(name)}\b', line):
            return i
    return 0


def _find_line_with_attr(lines: List[str], attr: str) -> int:
    """查找包含属性访问的行"""
    for i, line in enumerate(lines, 1):
        if re.search(rf'\.\s*{re.escape(attr)}\b', line):
            return i
    return 0


def _find_import_line(lines: List[str], module_name: str) -> int:
    """查找import语句行"""
    for i, line in enumerate(lines, 1):
        if re.search(rf'\bimport\b.*{re.escape(module_name)}', line):
            return i
    return 0


def _detect_common_errors(file_path: str, content: str) -> List[ErrorInfo]:
    """检测常见错误"""
    errors = []
    lines = content.split('\n')

    # 检测未使用的import
    try:
        tree = ast.parse(content)
        imported_names = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)

        # 简单检测(可能误报)
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)

        unused = imported_names - used_names
        for name in unused:
            line_num = _find_import_line(lines, name)
            errors.append(ErrorInfo(
                file_path=file_path,
                line=line_num,
                column=0,
                error_type='UnusedImport',
                message=f"Unused import: {name}",
                suggestion='Remove unused import',
                severity='warning'
            ))
    except:
        pass

    # 检测混合缩进
    indent_types = set()
    for line in lines:
        if line.strip() and not line.startswith('#'):
            if line.startswith(' '):
                indent_types.add('space')
            elif line.startswith('\t'):
                indent_types.add('tab')

    if len(indent_types) > 1:
        errors.append(ErrorInfo(
            file_path=file_path,
            line=1,
            column=0,
            error_type='MixedIndentation',
            message='Mixed spaces and tabs',
            suggestion='Use consistent indentation (prefer spaces)',
            severity='warning'
        ))

    return errors


def fix_imports(
    file_path: str,
    project_root: str = ".",
    auto_fix: bool = False
) -> List[ImportIssue]:
    """
    修复import问题

    Args:
        file_path: 文件路径
        project_root: 项目根目录
        auto_fix: 是否自动修复

    Returns:
        Import问题列表
    """
    issues = []

    if not os.path.exists(file_path):
        return issues

    # 扫描项目,找到所有可导入的模块
    available_modules = _scan_available_modules(project_root)

    # 分析文件
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        lines = content.split('\n')

    # 检测import问题
    missing_imports = []
    import_map = {}  # line -> import statement

    try:
        tree = ast.parse(content)
        used_names = set()

        # 收集使用的名称
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # 处理 module.name 形式
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        # 检查每个import
        for i, node in enumerate(ast.walk(tree)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_name = alias.asname or alias.name
                    import_map[node.lineno] = lines[node.lineno - 1]

                    # 检查模块是否存在
                    if alias.name not in available_modules:
                        issues.append(ImportIssue(
                            file_path=file_path,
                            line=node.lineno,
                            import_name=alias.name,
                            issue_type='missing',
                            suggestion=f"Module '{alias.name}' not found"
                        ))

            elif isinstance(node, ast.ImportFrom):
                import_map[node.lineno] = lines[node.lineno - 1]
                module = node.module or ''

                for alias in node.names:
                    import_name = alias.asname or alias.name

                    # 检查模块是否存在
                    if module and module not in available_modules:
                        issues.append(ImportIssue(
                            file_path=file_path,
                            line=node.lineno,
                            import_name=module,
                            issue_type='missing',
                            suggestion=f"Module '{module}' not found"
                        ))

        # 检测未导入但使用的名称
        for name in used_names:
            if name not in available_modules:
                continue

            # 检查是否已导入
            already_imported = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if name == (alias.asname or alias.name):
                            already_imported = True
                            break
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if name == (alias.asname or alias.name):
                            already_imported = True
                            break
                if already_imported:
                    break

            if not already_imported:
                missing_imports.append(name)
                issues.append(ImportIssue(
                    file_path=file_path,
                    line=1,
                    import_name=name,
                    issue_type='missing',
                    suggestion=f"Add: from {name} import * or import {name}"
                ))

    except SyntaxError:
        pass

    # 自动修复
    if auto_fix and missing_imports:
        fixed_content = _add_imports(content, missing_imports)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)

    return issues


def _scan_available_modules(project_root: str) -> Set[str]:
    """扫描项目中可用的模块"""
    modules = set()

    # 标准库模块
    modules.update(sys.stdlib_module_names if hasattr(sys, 'stdlib_module_names') else set())

    # 项目模块
    for root, dirs, files in os.walk(project_root):
        # 跳过隐藏目录和缓存目录
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for filename in files:
            if filename.endswith('.py') and filename != '__init__.py':
                module_name = filename[:-3]
                modules.add(module_name)

        # 包目录
        if '__init__.py' in files:
            rel_path = os.path.relpath(root, project_root)
            module_name = rel_path.replace(os.sep, '.')
            modules.add(module_name)

    return modules


def _add_imports(content: str, imports: List[str]) -> str:
    """添加import语句"""
    lines = content.split('\n')

    # 找到第一个非导入行
    insert_pos = 0
    for i, line in enumerate(lines):
        if not line.startswith('import') and not line.startswith('from'):
            if line.strip() and not line.startswith('#'):
                insert_pos = i
                break
            elif line.startswith('"""') or line.startswith("'''"):
                insert_pos = i
                break

    # 生成import语句
    new_imports = []
    for imp in imports:
        # 尝试智能import
        if '.' in imp:
            new_imports.append(f'from {imp.rsplit(".", 1)[0]} import {imp.split(".")[-1]}')
        else:
            new_imports.append(f'import {imp}')

    # 插入
    if new_imports:
        lines[insert_pos:insert_pos] = new_imports

    return '\n'.join(lines)


def check_syntax(file_path: str) -> List[ErrorInfo]:
    """
    检查语法错误

    Args:
        file_path: 文件路径

    Returns:
        语法错误列表
    """
    errors = []

    if not os.path.exists(file_path):
        return errors

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        ast.parse(content)
    except SyntaxError as e:
        errors.append(ErrorInfo(
            file_path=file_path,
            line=e.lineno or 0,
            column=e.offset or 0,
            error_type='SyntaxError',
            message=str(e),
            suggestion='Check syntax'
        ))
    except Exception as e:
        errors.append(ErrorInfo(
            file_path=file_path,
            line=0,
            column=0,
            error_type='ParseError',
            message=str(e),
            suggestion='Check file encoding'
        ))

    return errors


def quick_diagnose(file_path: str) -> str:
    """
    快速诊断(返回简要报告)

    Args:
        file_path: 文件路径

    Returns:
        诊断报告
    """
    errors = diagnose_error(file_path)
    import_issues = fix_imports(file_path, auto_fix=False)

    report = []
    report.append(f"诊断报告: {file_path}")
    report.append("-" * 50)

    if not errors and not import_issues:
        report.append("✓ 未发现问题")
    else:
        if errors:
            report.append(f"\n错误: {len(errors)}")
            for err in errors[:5]:  # 只显示前5个
                report.append(f"  [{err.severity}] {err.error_type} at line {err.line}: {err.message}")
                if err.suggestion:
                    report.append(f"    建议: {err.suggestion}")

        if import_issues:
            report.append(f"\nImport问题: {len(import_issues)}")
            for issue in import_issues[:5]:
                report.append(f"  [{issue.issue_type}] {issue.import_name} at line {issue.line}")
                if issue.suggestion:
                    report.append(f"    建议: {issue.suggestion}")

    return '\n'.join(report)