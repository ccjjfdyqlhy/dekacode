"""
批量并行执行模块
- batch_bash: 并行执行多条bash命令
- batch_symbol_search: 并行搜索多个符号
"""

import asyncio
import subprocess
import concurrent.futures
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
import os


@dataclass
class BashResult:
    """Bash命令执行结果"""
    command: str
    returncode: int
    stdout: str
    stderr: str
    success: bool


def batch_bash(
    commands: List[str],
    max_workers: int = 4,
    workdir: Optional[str] = None,
    timeout: Optional[int] = None
) -> List[BashResult]:
    """
    并行执行多条bash命令

    Args:
        commands: 命令列表
        max_workers: 最大并发数
        workdir: 工作目录
        timeout: 单个命令超时时间(秒)

    Returns:
        执行结果列表(与输入顺序一致)
    """
    def _run_command(cmd: str) -> BashResult:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return BashResult(
                command=cmd,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                success=result.returncode == 0
            )
        except subprocess.TimeoutExpired:
            return BashResult(
                command=cmd,
                returncode=-1,
                stdout="",
                stderr=f"Timeout after {timeout}s",
                success=False
            )
        except Exception as e:
            return BashResult(
                command=cmd,
                returncode=-1,
                stdout="",
                stderr=str(e),
                success=False
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_command, cmd): cmd for cmd in commands}
        results = []
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # 按输入顺序返回结果
    result_map = {r.command: r for r in results}
    return [result_map[cmd] for cmd in commands]


async def _async_run_command(
    cmd: str,
    workdir: Optional[str],
    timeout: Optional[int]
) -> BashResult:
    """异步执行单个命令"""
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout
        )
        return BashResult(
            command=cmd,
            returncode=process.returncode,
            stdout=stdout.decode('utf-8', errors='replace'),
            stderr=stderr.decode('utf-8', errors='replace'),
            success=process.returncode == 0
        )
    except asyncio.TimeoutError:
        try:
            process.kill()
        except:
            pass
        return BashResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=f"Timeout after {timeout}s",
            success=False
        )
    except Exception as e:
        return BashResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=str(e),
            success=False
        )


async def batch_bash_async(
    commands: List[str],
    max_concurrent: int = 4,
    workdir: Optional[str] = None,
    timeout: Optional[int] = None
) -> List[BashResult]:
    """
    异步并行执行多条bash命令

    Args:
        commands: 命令列表
        max_concurrent: 最大并发数
        workdir: 工作目录
        timeout: 单个命令超时时间(秒)

    Returns:
        执行结果列表(与输入顺序一致)
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _run_with_semaphore(cmd: str) -> BashResult:
        async with semaphore:
            return await _async_run_command(cmd, workdir, timeout)

    tasks = [_run_with_semaphore(cmd) for cmd in commands]
    results = await asyncio.gather(*tasks)

    return results


# Symbol search batch processing
@dataclass
class SymbolMatch:
    """符号匹配结果"""
    file_path: str
    symbol: str
    line: int
    context: str


def batch_symbol_search(
    symbols: List[str],
    project_root: str = ".",
    file_pattern: str = "*.py",
    max_workers: int = 4
) -> Dict[str, List[SymbolMatch]]:
    """
    并行搜索多个符号

    Args:
        symbols: 符号名列表
        project_root: 项目根目录
        file_pattern: 文件匹配模式
        max_workers: 最大并发数

    Returns:
        符号到匹配结果的映射
    """
    import fnmatch
    import os
    import re

    def _find_files() -> List[str]:
        files = []
        for root, _, filenames in os.walk(project_root):
            for filename in fnmatch.filter(filenames, file_pattern):
                files.append(os.path.join(root, filename))
        return files

    def _search_file(file_path: str) -> Dict[str, List[SymbolMatch]]:
        """在单个文件中搜索所有符号"""
        matches = {sym: [] for sym in symbols}
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                for line_num, line in enumerate(lines, 1):
                    for symbol in symbols:
                        # 匹配函数定义、类定义、变量引用等
                        patterns = [
                            rf'\bdef\s+{symbol}\s*\(',
                            rf'\bclass\s+{symbol}\s*[:\(]',
                            rf'\b{symbol}\s*[=\(]',
                            rf'\b{symbol}\b'
                        ]
                        for pattern in patterns:
                            if re.search(pattern, line):
                                matches[symbol].append(SymbolMatch(
                                    file_path=file_path,
                                    symbol=symbol,
                                    line=line_num,
                                    context=line.strip()
                                ))
                                break
        except Exception:
            pass
        return matches

    # 查找所有文件
    files = _find_files()

    # 并行搜索
    results = {sym: [] for sym in symbols}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(_search_file, f): f for f in files}
        for future in concurrent.futures.as_completed(future_to_file):
            file_matches = future.result()
            for symbol in symbols:
                results[symbol].extend(file_matches[symbol])

    return results


# Convenience function for batch processing
def batch_process(
    items: List[Any],
    process_func: Callable[[Any], Any],
    max_workers: int = 4
) -> List[Any]:
    """
    通用批量处理函数

    Args:
        items: 待处理项列表
        process_func: 处理函数
        max_workers: 最大并发数

    Returns:
        处理结果列表(与输入顺序一致)
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_func, item): i for i, item in enumerate(items)}
        results = [None] * len(items)
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    return results