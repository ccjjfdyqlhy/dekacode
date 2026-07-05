"""
智能分块模块
- smart_read_file: 智能读取文件(按语义边界分块)
- stream_file: 流式读取文件
- smart_grep: 智能grep(带上下文)
"""

import re
import os
from typing import List, Optional, Callable, Iterator, Tuple, Any
from dataclasses import dataclass


@dataclass
class FileChunk:
    """文件分块"""
    content: str
    start_line: int
    end_line: int
    is_function: bool = False
    is_class: bool = False
    function_name: Optional[str] = None
    class_name: Optional[str] = None


def smart_read_file(
    file_path: str,
    chunk_size: int = 500,
    respect_boundaries: bool = True
) -> List[FileChunk]:
    """
    智能读取文件,按语义边界分块

    Args:
        file_path: 文件路径
        chunk_size: 目标块大小(行数)
        respect_boundaries: 是否尊重语义边界(函数/类)

    Returns:
        文件分块列表
    """
    if not os.path.exists(file_path):
        return []

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    if not respect_boundaries:
        # 简单按行数分块
        chunks = []
        for i in range(0, len(lines), chunk_size):
            chunk = FileChunk(
                content=''.join(lines[i:i + chunk_size]),
                start_line=i + 1,
                end_line=min(i + chunk_size, len(lines))
            )
            chunks.append(chunk)
        return chunks

    # 按语义边界分块
    chunks = []
    current_chunk_lines = []
    current_start = 1
    current_indent_level = 0
    in_function = False
    in_class = False
    function_name = None
    class_name = None

    for line_num, line in enumerate(lines, 1):
        current_chunk_lines.append(line)

        # 检测函数/类定义
        stripped = line.strip()
        if stripped.startswith('def ') and ':' in line:
            in_function = True
            match = re.search(r'def\s+(\w+)', line)
            function_name = match.group(1) if match else None
        elif stripped.startswith('class ') and ':' in line:
            in_class = True
            match = re.search(r'class\s+(\w+)', line)
            class_name = match.group(1) if match else None

        # 检测缩进变化
        indent = len(line) - len(line.lstrip())
        if stripped and not stripped.startswith('#'):
            if indent == 0 and current_indent_level > 0:
                # 返回到顶层,可能结束函数/类
                in_function = False
                in_class = False
                function_name = None
                class_name = None
            current_indent_level = indent

        # 分块条件
        if len(current_chunk_lines) >= chunk_size and indent == 0:
            # 在顶层边界分块
            chunk = FileChunk(
                content=''.join(current_chunk_lines),
                start_line=current_start,
                end_line=line_num,
                is_function=in_function,
                is_class=in_class,
                function_name=function_name,
                class_name=class_name
            )
            chunks.append(chunk)
            current_chunk_lines = []
            current_start = line_num + 1

    # 添加剩余部分
    if current_chunk_lines:
        chunk = FileChunk(
            content=''.join(current_chunk_lines),
            start_line=current_start,
            end_line=len(lines),
            is_function=in_function,
            is_class=in_class,
            function_name=function_name,
            class_name=class_name
        )
        chunks.append(chunk)

    return chunks


def stream_file(
    file_path: str,
    chunk_lines: int = 100,
    start_line: int = 1,
    end_line: Optional[int] = None,
    filter_func: Optional[Callable[[str], bool]] = None
) -> Iterator[str]:
    """
    流式读取文件

    Args:
        file_path: 文件路径
        chunk_lines: 每次读取的行数
        start_line: 起始行(1-based)
        end_line: 结束行(1-based)
        filter_func: 行过滤函数(返回True则保留)

    Yields:
        文件内容块
    """
    if not os.path.exists(file_path):
        return

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        current_line = 0
        buffer = []

        for line in f:
            current_line += 1
            if current_line < start_line:
                continue
            if end_line and current_line > end_line:
                break

            # 应用过滤器
            if filter_func and not filter_func(line):
                continue

            buffer.append(line)

            # 达到块大小则yield
            if len(buffer) >= chunk_lines:
                yield ''.join(buffer)
                buffer = []

        # yield剩余内容
        if buffer:
            yield ''.join(buffer)


@dataclass
class GrepMatch:
    """Grep匹配结果"""
    file_path: str
    line: int
    content: str
    before: List[str]
    after: List[str]
    match_start: int
    match_end: int


def smart_grep(
    pattern: str,
    file_path: str,
    context_lines: int = 3,
    case_sensitive: bool = False,
    regex: bool = True
) -> List[GrepMatch]:
    """
    智能grep,带上下文

    Args:
        pattern: 搜索模式
        file_path: 文件路径
        context_lines: 上下文行数
        case_sensitive: 是否区分大小写
        regex: 是否使用正则表达式

    Returns:
        匹配结果列表
    """
    if not os.path.exists(file_path):
        return []

    matches = []

    # 编译正则
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        try:
            compiled_pattern = re.compile(pattern, flags)
        except re.error:
            compiled_pattern = None
    else:
        compiled_pattern = None

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for line_num, line in enumerate(lines, 1):
        match = None
        if regex and compiled_pattern:
            match_obj = compiled_pattern.search(line)
            if match_obj:
                match = (match_obj.start(), match_obj.end())
        else:
            search_pattern = pattern if case_sensitive else pattern.lower()
            search_line = line if case_sensitive else line.lower()
            pos = search_line.find(search_pattern)
            if pos >= 0:
                match = (pos, pos + len(pattern))

        if match:
            start_idx, end_idx = match

            # 获取上下文
            before_start = max(0, line_num - context_lines - 1)
            before = lines[before_start:line_num - 1]

            after_end = min(len(lines), line_num + context_lines)
            after = lines[line_num:after_end]

            match_result = GrepMatch(
                file_path=file_path,
                line=line_num,
                content=line.rstrip(),
                before=[b.rstrip() for b in before],
                after=[a.rstrip() for a in after],
                match_start=start_idx,
                match_end=end_idx
            )
            matches.append(match_result)

    return matches


def smart_grep_multi(
    pattern: str,
    file_paths: List[str],
    context_lines: int = 3,
    case_sensitive: bool = False,
    regex: bool = True
) -> List[GrepMatch]:
    """
    多文件智能grep

    Args:
        pattern: 搜索模式
        file_paths: 文件路径列表
        context_lines: 上下文行数
        case_sensitive: 是否区分大小写
        regex: 是否使用正则表达式

    Returns:
        匹配结果列表
    """
    all_matches = []
    for file_path in file_paths:
        matches = smart_grep(
            pattern, file_path, context_lines, case_sensitive, regex
        )
        all_matches.extend(matches)
    return all_matches


def grep_context_stream(
    pattern: str,
    file_path: str,
    context_lines: int = 3,
    case_sensitive: bool = False,
    regex: bool = True
) -> Iterator[GrepMatch]:
    """
    流式grep(适用于大文件)

    Args:
        pattern: 搜索模式
        file_path: 文件路径
        context_lines: 上下文行数
        case_sensitive: 是否区分大小写
        regex: 是否使用正则表达式

    Yields:
        匹配结果
    """
    if not os.path.exists(file_path):
        return

    # 编译正则
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        try:
            compiled_pattern = re.compile(pattern, flags)
        except re.error:
            compiled_pattern = None
    else:
        compiled_pattern = None

    # 使用滑动窗口
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        line_buffer = []
        line_numbers = []

        for line_num, line in enumerate(f, 1):
            line_numbers.append(line_num)
            line_buffer.append(line)

            # 保持buffer大小
            max_buffer = context_lines * 2 + 1
            if len(line_buffer) > max_buffer:
                line_buffer.pop(0)
                line_numbers.pop(0)

            # 检查中间行是否匹配
            middle_idx = context_lines
            if middle_idx < len(line_buffer):
                middle_line = line_buffer[middle_idx]
                middle_line_num = line_numbers[middle_idx]

                match = None
                if regex and compiled_pattern:
                    match_obj = compiled_pattern.search(middle_line)
                    if match_obj:
                        match = (match_obj.start(), match_obj.end())
                else:
                    search_pattern = pattern if case_sensitive else pattern.lower()
                    search_line = middle_line if case_sensitive else middle_line.lower()
                    pos = search_line.find(search_pattern)
                    if pos >= 0:
                        match = (pos, pos + len(pattern))

                if match:
                    start_idx, end_idx = match

                    before = [line_buffer[i].rstrip() for i in range(middle_idx)]
                    after = [line_buffer[i].rstrip() for i in range(middle_idx + 1, len(line_buffer))]

                    yield GrepMatch(
                        file_path=file_path,
                        line=middle_line_num,
                        content=middle_line.rstrip(),
                        before=before,
                        after=after,
                        match_start=start_idx,
                        match_end=end_idx
                    )