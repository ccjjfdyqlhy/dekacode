"""
测试智能缓存模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
from skills.core.cache import (
    cached_file,
    cached_result,
    FileCache,
    ResultCache,
    clear_file_cache,
    clear_result_cache,
    get_cache_stats
)


def test_file_cache():
    """测试文件缓存"""
    cache = FileCache(max_size_mb=1, ttl_seconds=60)

    # 设置缓存
    cache.set("/tmp/test.txt", "Hello World")

    # 获取缓存
    result = cache.get("/tmp/test.txt")
    assert result == "Hello World"

    # 测试统计
    stats = cache.stats()
    assert stats['entries'] == 1


def test_file_cache_eviction():
    """测试缓存淘汰"""
    cache = FileCache(max_size_mb=0.001, ttl_seconds=60)  # 很小的缓存

    # 添加大量数据
    for i in range(100):
        cache.set(f"/tmp/test{i}.txt", f"Content {i}" * 100)

    # 应该淘汰大部分
    stats = cache.stats()
    assert stats['entries'] < 50


@cached_file(max_size_mb=10, ttl_seconds=60)
def read_file_cached(path):
    """测试文件缓存装饰器"""
    with open(path, 'r') as f:
        return f.read()


def test_cached_file_decorator():
    """测试文件缓存装饰器"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        # 第一次读取
        content1 = read_file_cached(temp_path)
        assert content1 == "Test content"

        # 第二次读取(从缓存)
        content2 = read_file_cached(temp_path)
        assert content2 == "Test content"

        # 测试缓存统计
        stats = get_cache_stats()
        assert 'file_cache' in stats
    finally:
        os.unlink(temp_path)


@cached_result()
def expensive_computation(x, y):
    """测试结果缓存装饰器"""
    return x ** y


def test_cached_result_decorator():
    """测试结果缓存装饰器"""
    # 第一次调用
    result1 = expensive_computation(2, 10)
    assert result1 == 1024

    # 第二次调用(从缓存)
    result2 = expensive_computation(2, 10)
    assert result2 == 1024


def test_result_cache():
    """测试结果缓存"""
    cache = ResultCache(cache_dir="/tmp/test_cache")

    # 设置缓存
    cache.set("test_func", (1, 2), {}, "result")

    # 获取缓存
    result = cache.get("test_func", (1, 2), {})
    assert result == "result"


def test_clear_caches():
    """测试清空缓存"""
    # 使用一些缓存
    expensive_computation(2, 10)

    # 清空
    clear_result_cache()
    clear_file_cache()

    stats = get_cache_stats()
    assert stats['file_cache']['entries'] == 0


if __name__ == '__main__':
    test_file_cache()
    test_file_cache_eviction()
    test_cached_file_decorator()
    test_cached_result_decorator()
    test_result_cache()
    test_clear_caches()
    print("All cache tests passed!")