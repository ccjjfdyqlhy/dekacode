"""
测试错误诊断模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from skills.core.diagnose import (
    diagnose_error,
    fix_imports,
    check_syntax,
    quick_diagnose,
    ErrorInfo,
    ImportIssue
)


def test_diagnose_syntax_error():
    """测试语法错误诊断"""
    # 创建有语法错误的文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func(
    pass  # 缺少右括号
""")
        temp_path = f.name

    try:
        errors = diagnose_error(temp_path)

        assert len(errors) > 0
        assert any(e.error_type == 'SyntaxError' for e in errors)
    finally:
        os.unlink(temp_path)


def test_diagnose_nonexistent_file():
    """测试不存在的文件"""
    errors = diagnose_error("/nonexistent/file.py")

    assert len(errors) > 0
    assert errors[0].error_type == 'FileNotFound'


def test_diagnose_with_error_message():
    """测试解析错误信息"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
undefined_var = 1
x = undefined_name  # NameError
""")
        temp_path = f.name

    try:
        error_message = "NameError: name 'undefined_name' is not defined"
        errors = diagnose_error(temp_path, error_message)

        assert len(errors) > 0
        assert any(e.error_type == 'NameError' for e in errors)
    finally:
        os.unlink(temp_path)


def test_check_syntax():
    """测试语法检查"""
    # 创建正确的文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func():
    pass
""")
        temp_path = f.name

    try:
        errors = check_syntax(temp_path)
        assert len(errors) == 0  # 无语法错误
    finally:
        os.unlink(temp_path)


def test_check_syntax_invalid():
    """测试语法检查(错误)"""
    # 创建错误的文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("def test_func(\n")
        temp_path = f.name

    try:
        errors = check_syntax(temp_path)
        assert len(errors) > 0
        assert errors[0].error_type == 'SyntaxError'
    finally:
        os.unlink(temp_path)


def test_quick_diagnose():
    """测试快速诊断"""
    # 创建正常的文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func():
    pass
""")
        temp_path = f.name

    try:
        report = quick_diagnose(temp_path)

        assert isinstance(report, str)
        assert '诊断报告' in report
    finally:
        os.unlink(temp_path)


def test_fix_imports():
    """测试import修复"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
import os
import sys
import nonexistent_module  # 不存在的模块

def test_func():
    pass
""")
        temp_path = f.name

    try:
        issues = fix_imports(temp_path, auto_fix=False)

        # 应该检测到不存在的模块
        assert any(i.issue_type == 'missing' for i in issues)
    finally:
        os.unlink(temp_path)


def test_detect_mixed_indentation():
    """测试混合缩进检测"""
    # 创建混合缩进的文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func():
\tpass  # tab
    pass  # space
""")
        temp_path = f.name

    try:
        errors = diagnose_error(temp_path)

        # 应该检测到混合缩进
        assert any(e.error_type == 'MixedIndentation' for e in errors)
    finally:
        os.unlink(temp_path)


if __name__ == '__main__':
    test_diagnose_syntax_error()
    test_diagnose_nonexistent_file()
    test_diagnose_with_error_message()
    test_check_syntax()
    test_check_syntax_invalid()
    test_quick_diagnose()
    test_fix_imports()
    test_detect_mixed_indentation()
    print("All diagnose tests passed!")