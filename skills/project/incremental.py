"""
增量更新模块
- git_diff_lines: 获取git diff的变更行
- file_delta: 文件差异分析
- incremental_graph: 增量更新调用图
"""

import subprocess
import os
import re
import ast
from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import hashlib


@dataclass
class DiffLine:
    """diff行"""
    file_path: str
    line: int
    change_type: str  # 'added', 'removed', 'modified'
    old_line: Optional[int] = None
    content: str = ""


@dataclass
class FileDelta:
    """文件差异"""
    file_path: str
    added_lines: Set[int]
    removed_lines: Set[int]
    modified_lines: Set[int]
    hunks: List[Dict[str, Any]]


def git_diff_lines(
    commit_hash: Optional[str] = None,
    file_pattern: str = "*.py",
    workdir: str = "."
) -> Dict[str, List[DiffLine]]:
    """
    获取git diff的变更行

    Args:
        commit_hash: 对比的commit hash(默认对比working tree)
        file_pattern: 文件匹配模式
        workdir: 工作目录

    Returns:
        文件路径到diff行的映射
    """
    if not os.path.exists(os.path.join(workdir, '.git')):
        return {}

    # 构建git diff命令
    if commit_hash:
        cmd = f"git diff {commit_hash} HEAD"
    else:
        cmd = "git diff"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return {}

        diff_output = result.stdout
    except:
        return {}

    # 解析diff输出
    return _parse_diff_output(diff_output, workdir, file_pattern)


def _parse_diff_output(
    diff_output: str,
    workdir: str,
    file_pattern: str
) -> Dict[str, List[DiffLine]]:
    """解析diff输出"""
    result = {}
    current_file = None
    old_start = 0
    new_start = 0

    lines = diff_output.split('\n')
    i = 0

    while i < len(lines):
        line = lines[i]

        # 文件头
        if line.startswith('diff --git'):
            match = re.search(r'b/(.+)$', line)
            if match:
                current_file = match.group(1)
                # 应用文件模式过滤
                if not _matches_pattern(current_file, file_pattern):
                    current_file = None
                else:
                    result[current_file] = []
                    old_start = 0
                    new_start = 0

        # hunk头
        elif line.startswith('@@') and current_file:
            match = re.search(r'-(\d+),?\d*\s+\+(\d+),?\d*', line)
            if match:
                old_start = int(match.group(1))
                new_start = int(match.group(2))

        # 添加行
        elif line.startswith('+') and not line.startswith('++') and current_file:
            result[current_file].append(DiffLine(
                file_path=os.path.join(workdir, current_file),
                line=new_start,
                change_type='added',
                content=line[1:]
            ))
            new_start += 1

        # 删除行
        elif line.startswith('-') and not line.startswith('--') and current_file:
            result[current_file].append(DiffLine(
                file_path=os.path.join(workdir, current_file),
                line=old_start,
                change_type='removed',
                content=line[1:]
            ))
            old_start += 1

        # 上下文行
        elif line.startswith(' ') and current_file:
            new_start += 1
            old_start += 1

        i += 1

    return result


def _matches_pattern(file_path: str, pattern: str) -> bool:
    """匹配文件模式"""
    import fnmatch
    return fnmatch.fnmatch(os.path.basename(file_path), pattern)


def file_delta(
    old_path: str,
    new_path: str
) -> FileDelta:
    """
    文件差异分析

    Args:
        old_path: 旧文件路径
        new_path: 新文件路径

    Returns:
        文件差异
    """
    added_lines = set()
    removed_lines = set()
    modified_lines = set()
    hunks = []

    if not os.path.exists(old_path) and os.path.exists(new_path):
        # 新文件
        with open(new_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        added_lines.update(range(1, len(lines) + 1))

    elif os.path.exists(old_path) and not os.path.exists(new_path):
        # 删除文件
        with open(old_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        removed_lines.update(range(1, len(lines) + 1))

    elif os.path.exists(old_path) and os.path.exists(new_path):
        # 对比两个文件
        with open(old_path, 'r', encoding='utf-8', errors='ignore') as f:
            old_lines = f.readlines()
        with open(new_path, 'r', encoding='utf-8', errors='ignore') as f:
            new_lines = f.readlines()

        # 计算hash
        old_hash = _compute_file_hash(old_path)
        new_hash = _compute_file_hash(new_path)

        if old_hash == new_hash:
            # 无变化
            pass
        else:
            # 简单逐行对比
            max_len = max(len(old_lines), len(new_lines))

            for i in range(max_len):
                old_line = old_lines[i] if i < len(old_lines) else None
                new_line = new_lines[i] if i < len(new_lines) else None

                if old_line is None:
                    added_lines.add(i + 1)
                elif new_line is None:
                    removed_lines.add(i + 1)
                elif old_line != new_line:
                    modified_lines.add(i + 1)

    return FileDelta(
        file_path=new_path,
        added_lines=added_lines,
        removed_lines=removed_lines,
        modified_lines=modified_lines,
        hunks=hunks
    )


def _compute_file_hash(file_path: str) -> str:
    """计算文件hash"""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass
class SymbolChange:
    """符号变更"""
    symbol: str
    change_type: str  # 'added', 'removed', 'modified'
    file_path: str
    old_line: Optional[int]
    new_line: Optional[int]


def incremental_graph(
    old_root: str,
    new_root: str,
    symbol_index: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    增量更新调用图

    Args:
        old_root: 旧版本项目根目录
        new_root: 新版本项目根目录
        symbol_index: 现有符号索引(可选)

    Returns:
        更新信息
    """
    # 获取diff
    if os.path.exists(os.path.join(new_root, '.git')):
        diff_lines = git_diff_lines(workdir=new_root)
    else:
        # 如果没有git,直接对比目录
        diff_lines = _compare_directories(old_root, new_root)

    # 分析符号变更
    symbol_changes = []

    for file_path, lines in diff_lines.items():
        # 转换为绝对路径
        abs_file_path = file_path if os.path.isabs(file_path) else os.path.join(new_root, file_path)

        # 确保文件存在
        if not os.path.exists(abs_file_path):
            continue

        # 读取文件内容
        with open(abs_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # 解析AST,提取符号
        try:
            tree = ast.parse(content)
            symbols = _extract_symbols_from_ast(tree)
        except:
            symbols = {}

        # 分析变更的行
        added_lines = [l.line for l in lines if l.change_type == 'added']
        removed_lines = [l.line for l in lines if l.change_type == 'removed']

        # 判断哪些符号受影响
        for symbol, info in symbols.items():
            symbol_line = info.get('line', 0)

            # 检查是否在变更行附近
            for line in added_lines + removed_lines:
                if abs(symbol_line - line) <= 5:  # 附近5行内
                    change_type = 'added' if symbol_line in added_lines else 'modified'
                    if symbol_line in removed_lines:
                        change_type = 'removed'

                    symbol_changes.append(SymbolChange(
                        symbol=symbol,
                        change_type=change_type,
                        file_path=file_path,
                        old_line=line if line in removed_lines else None,
                        new_line=line if line in added_lines else None
                    ))
                    break

    # 统计变更
    summary = {
        'total_files_changed': len(diff_lines),
        'total_lines_added': sum(1 for lines in diff_lines.values()
                               for l in lines if l.change_type == 'added'),
        'total_lines_removed': sum(1 for lines in diff_lines.values()
                                 for l in lines if l.change_type == 'removed'),
        'symbols_changed': len(symbol_changes),
        'changed_files': list(diff_lines.keys()),
        'symbol_changes': [
            {
                'symbol': c.symbol,
                'type': c.change_type,
                'file': c.file_path,
                'line': c.new_line or c.old_line
            }
            for c in symbol_changes
        ]
    }

    return summary


def _compare_directories(old_root: str, new_root: str) -> Dict[str, List[DiffLine]]:
    """对比两个目录"""
    diff_lines = {}

    # 查找所有Python文件
    for root, dirs, files in os.walk(new_root):
        for filename in files:
            if filename.endswith('.py'):
                new_path = os.path.join(root, filename)
                rel_path = os.path.relpath(new_path, new_root)
                old_path = os.path.join(old_root, rel_path)

                delta = file_delta(old_path, new_path)

                # 转换为DiffLine列表
                lines = []
                for line in delta.added_lines:
                    lines.append(DiffLine(
                        file_path=new_path,
                        line=line,
                        change_type='added'
                    ))
                for line in delta.removed_lines:
                    lines.append(DiffLine(
                        file_path=new_path,
                        line=line,
                        change_type='removed'
                    ))
                for line in delta.modified_lines:
                    lines.append(DiffLine(
                        file_path=new_path,
                        line=line,
                        change_type='modified'
                    ))

                if lines:
                    diff_lines[rel_path] = lines

    return diff_lines


def _extract_symbols_from_ast(tree: ast.AST) -> Dict[str, Dict[str, Any]]:
    """从AST提取符号"""
    symbols = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            symbols[node.name] = {
                'type': 'function',
                'line': node.lineno,
                'docstring': ast.get_docstring(node)
            }
        elif isinstance(node, ast.ClassDef):
            symbols[node.name] = {
                'type': 'class',
                'line': node.lineno,
                'docstring': ast.get_docstring(node)
            }

    return symbols


def get_changed_files(
    since_commit: Optional[str] = None,
    workdir: str = ".",
    file_pattern: str = "*.py"
) -> List[str]:
    """
    获取变更文件列表

    Args:
        since_commit: 起始commit
        workdir: 工作目录
        file_pattern: 文件匹配模式

    Returns:
        变更文件路径列表
    """
    diff_lines = git_diff_lines(since_commit, file_pattern, workdir)
    return list(diff_lines.keys())


def get_file_change_summary(
    file_path: str,
    since_commit: Optional[str] = None,
    workdir: str = "."
) -> Dict[str, Any]:
    """
    获取单个文件的变更摘要

    Args:
        file_path: 文件路径
        since_commit: 起始commit
        workdir: 工作目录

    Returns:
        变更摘要
    """
    diff_lines = git_diff_lines(since_commit, "*.py", workdir)

    rel_path = os.path.relpath(file_path, workdir)
    file_diffs = diff_lines.get(rel_path, [])

    added = [l for l in file_diffs if l.change_type == 'added']
    removed = [l for l in file_diffs if l.change_type == 'removed']

    return {
        'file_path': file_path,
        'total_changes': len(file_diffs),
        'lines_added': len(added),
        'lines_removed': len(removed),
        'added_lines': [l.line for l in added],
        'removed_lines': [l.line for l in removed]
    }