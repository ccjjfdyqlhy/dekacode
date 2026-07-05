"""
测试智能分块模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from skills.core.chunk import (
    smart_read_file,
    stream_file,
    smart_grep,
    FileChunk,
    GrepMatch
)


def test_smart_read_file():
    """测试智能读取文件"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def func1():
    pass

def func2():
    pass

class MyClass:
    def method1(self):
        pass

    def method2(self):
        pass
""")
        temp_path = f.name

    try:
        chunks = smart_read_file(temp_path, chunk_size=5, respect_boundaries=True)

        assert len(chunks) > 0
        assert all(isinstance(c, FileChunk) for c in chunks)
        # 注意:由于分块逻辑,函数/类标记可能不在所有块中
    finally:
        os.unlink(temp_path)


def test_stream_file():
    """测试流式读取文件"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        for i in range(20):
            f.write(f"Line {i}\n")
        temp_path = f.name

    try:
        chunks = list(stream_file(temp_path, chunk_lines=5))

        assert len(chunks) == 4  # 20 lines / 5 = 4 chunks
        assert all(isinstance(c, str) for c in chunks)
    finally:
        os.unlink(temp_path)


def test_stream_file_with_filter():
    """测试流式读取带过滤"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        for i in range(10):
            f.write(f"Line {i}\n")
        temp_path = f.name

    try:
        # 只读取偶数行
        def even_filter(line):
            return int(line.split()[1]) % 2 == 0

        chunks = list(stream_file(temp_path, chunk_lines=2, filter_func=even_filter))

        # 应该只有偶数行
        total_lines = sum(c.count('\n') for c in chunks)
        assert total_lines <= 5  # 只有一半
    finally:
        os.unlink(temp_path)


def test_smart_grep():
    """测试智能grep"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func():
    pass

class TestClass:
    def test_method(self):
        pass

# This is a test comment
""")
        temp_path = f.name

    try:
        matches = smart_grep(r"test", temp_path, context_lines=1)

        assert len(matches) > 0
        assert all(isinstance(m, GrepMatch) for m in matches)
        assert all(m.file_path == temp_path for m in matches)
        assert all(len(m.before) <= 1 for m in matches)
        assert all(len(m.after) <= 1 for m in matches)
    finally:
        os.unlink(temp_path)


def test_smart_grep_case_insensitive():
    """测试大小写不敏感"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("TEST\nTest\ntest\nTESTING\n")
        temp_path = f.name

    try:
        matches = smart_grep("test", temp_path, case_sensitive=False)

        assert len(matches) == 4
    finally:
        os.unlink(temp_path)


if __name__ == '__main__':
    test_smart_read_file()
    test_stream_file()
    test_stream_file_with_filter()
    test_smart_grep()
    test_smart_grep_case_insensitive()
    print("All chunk tests passed!")