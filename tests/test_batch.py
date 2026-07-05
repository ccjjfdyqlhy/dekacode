"""
测试批量并行模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from skills.core.batch import (
    batch_bash,
    batch_symbol_search,
    batch_process,
    BashResult,
    SymbolMatch
)


def test_batch_bash():
    """测试批量执行bash命令"""
    commands = [
        "echo 'hello'",
        "echo 'world'",
        "ls -la | head -5"
    ]

    results = batch_bash(commands, max_workers=2)

    assert len(results) == 3
    assert all(isinstance(r, BashResult) for r in results)
    assert results[0].success
    assert 'hello' in results[0].stdout
    assert 'world' in results[1].stdout


def test_batch_bash_timeout():
    """测试超时处理"""
    commands = [
        "echo 'quick'",
        "sleep 10"  # 会超时
    ]

    results = batch_bash(commands, timeout=1)

    assert len(results) == 2
    assert results[0].success
    assert not results[1].success  # 超时


def test_batch_symbol_search():
    """测试批量符号搜索"""
    symbols = ["test", "SymbolMatch"]

    results = batch_symbol_search(
        symbols,
        project_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        file_pattern="*.py"
    )

    assert isinstance(results, dict)
    assert "SymbolMatch" in results
    assert len(results["SymbolMatch"]) > 0


def test_batch_process():
    """测试通用批量处理"""
    def process_item(x):
        return x * 2

    items = [1, 2, 3, 4, 5]
    results = batch_process(items, process_func=process_item, max_workers=2)

    assert results == [2, 4, 6, 8, 10]


if __name__ == '__main__':
    test_batch_bash()
    test_batch_bash_timeout()
    test_batch_symbol_search()
    test_batch_process()
    print("All batch tests passed!")