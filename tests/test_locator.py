"""
测试快速定位模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from skills.core.locator import (
    find_definition,
    find_references,
    locate_symbol,
    find_class_methods,
    find_all_symbols,
    SymbolLocation
)


def test_find_definition():
    """测试查找定义"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def my_function():
    pass

class MyClass:
    def my_method(self):
        pass
""")
        temp_path = f.name

    try:
        # 查找函数定义
        locations = find_definition("my_function", project_root=os.path.dirname(temp_path))

        assert len(locations) > 0
        assert any(l.symbol_type == 'function' for l in locations)
    finally:
        os.unlink(temp_path)


def test_find_references():
    """测试查找引用"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def test_func():
    pass

x = test_func()
y = test_func
""")
        temp_path = f.name

    try:
        references = find_references(
            "test_func",
            project_root=os.path.dirname(temp_path)
        )

        assert len(references) >= 2  # 定义 + 调用 + 赋值
    finally:
        os.unlink(temp_path)


def test_locate_symbol():
    """测试定位符号"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def locate_test():
    pass

x = locate_test()
""")
        temp_path = f.name

    try:
        result = locate_symbol(
            "locate_test",
            project_root=os.path.dirname(temp_path),
            find_type="both"
        )

        assert 'symbol' in result
        assert result['symbol'] == 'locate_test'
        assert 'definitions' in result
        assert 'references' in result
    finally:
        os.unlink(temp_path)


def test_find_class_methods():
    """测试查找类方法"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
class TestClass:
    def method1(self):
        pass

    def method2(self):
        pass
""")
        temp_path = f.name

    try:
        methods = find_class_methods(
            "TestClass",
            project_root=os.path.dirname(temp_path)
        )

        assert len(methods) == 2
        method_names = [m['name'] for m in methods]
        assert 'method1' in method_names
        assert 'method2' in method_names
    finally:
        os.unlink(temp_path)


def test_find_all_symbols():
    """测试查找所有符号"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
        f.write("""
def func1():
    pass

def func2():
    pass

class Class1:
    pass

var1 = 1
""")
        temp_path = f.name

    try:
        symbols = find_all_symbols(project_root=os.path.dirname(temp_path))

        assert 'functions' in symbols
        assert 'classes' in symbols
        assert 'variables' in symbols
        assert len(symbols['functions']) >= 2
        assert len(symbols['classes']) >= 1
    finally:
        os.unlink(temp_path)


if __name__ == '__main__':
    test_find_definition()
    test_find_references()
    test_locate_symbol()
    test_find_class_methods()
    test_find_all_symbols()
    print("All locator tests passed!")