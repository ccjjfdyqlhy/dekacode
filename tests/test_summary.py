"""
测试智能摘要模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from skills.project.summary import (
    summarize_file,
    summarize_session,
    diff_summary,
    summarize_project,
    FileSummary,
    SessionSummary,
    DiffSummary
)


def test_summarize_file():
    """测试文件摘要"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func1():
    '''Test function 1'''
    pass

def test_func2(x, y):
    '''Test function 2'''
    return x + y

class TestClass:
    def method1(self):
        pass

    def method2(self, x):
        return x * 2
""")
        temp_path = f.name

    try:
        summary = summarize_file(temp_path)

        assert isinstance(summary, FileSummary)
        assert summary.file_path == temp_path
        assert summary.total_lines > 0
        assert len(summary.functions) >= 2
        assert len(summary.classes) >= 1
        assert summary.complexity_score >= 0
    finally:
        os.unlink(temp_path)


def test_summarize_session():
    """测试会话摘要"""
    messages = [
        {"role": "user", "content": "创建一个Python类"},
        {"role": "assistant", "content": "好的,这是一个Python类示例"},
        {"role": "user", "content": "修改test方法"},
        {"role": "assistant", "content": "已修改test方法"}
    ]

    summary = summarize_session(messages)

    assert isinstance(summary, SessionSummary)
    assert summary.total_messages == 4
    assert summary.user_messages == 2
    assert summary.assistant_messages == 2
    assert len(summary.key_topics) >= 0
    assert len(summary.actions) >= 0


def test_diff_summary():
    """测试diff摘要"""
    from skills.project.incremental import DiffLine

    # 创建diff行
    diff_lines = [
        DiffLine(file_path="test.py", line=1, change_type="added", content="def new_func():"),
        DiffLine(file_path="test.py", line=2, change_type="added", content="    pass"),
        DiffLine(file_path="test.py", line=5, change_type="removed", content="def old_func():")
    ]

    summary = diff_summary("test.py", diff_lines)

    assert isinstance(summary, DiffSummary)
    assert summary.file_path == "test.py"
    assert summary.total_changes == 3
    assert summary.added_lines == 2
    assert summary.removed_lines == 1
    assert summary.impact_level in ['low', 'medium', 'high']


def test_diff_summary_empty():
    """测试空diff摘要"""
    summary = diff_summary("test.py", [])

    assert summary.total_changes == 0
    assert summary.impact_level == 'low'
    assert summary.summary == "无变更"


def test_summarize_project():
    """测试项目摘要"""
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建几个文件
        file1 = os.path.join(tmpdir, "file1.py")
        file2 = os.path.join(tmpdir, "file2.py")

        with open(file1, 'w') as f:
            f.write("def func1():\n    pass\n")

        with open(file2, 'w') as f:
            f.write("class Class1:\n    pass\n")

        summary = summarize_project(tmpdir, max_files=10)

        assert 'files_analyzed' in summary
        assert 'total_functions' in summary
        assert 'total_classes' in summary
        assert 'common_features' in summary


def test_summarize_file_with_features():
    """测试特征提取"""
    # 创建临时文件(包含各种特征)
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
import os
import sys
from dataclasses import dataclass

@dataclass
class TestClass:
    def method(self):
        try:
            result = self._process()
        except Exception as e:
            print(e)

    async def async_method(self):
        pass
""")
        temp_path = f.name

    try:
        summary = summarize_file(temp_path)

        assert len(summary.key_features) > 0
        assert any('dataclass' in f.lower() for f in summary.key_features)
        # 异步函数的检测
        assert any('async' in f.lower() for f in summary.key_features)
    finally:
        os.unlink(temp_path)


if __name__ == '__main__':
    test_summarize_file()
    test_summarize_session()
    test_diff_summary()
    test_diff_summary_empty()
    test_summarize_project()
    test_summarize_file_with_features()
    print("All summary tests passed!")