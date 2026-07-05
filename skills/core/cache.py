"""
智能缓存模块
- cached_file: 文件内容缓存
- cached_result: 工具结果缓存
"""

import hashlib
import pickle
import os
import json
from typing import Any, Optional, Callable, TypeVar, Dict
from functools import wraps
from dataclasses import dataclass
import time
from collections import OrderedDict


T = TypeVar('T')


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    timestamp: float
    size: int


class FileCache:
    """文件内容缓存"""

    def __init__(self, max_size_mb: int = 100, ttl_seconds: int = 3600):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.ttl_seconds = ttl_seconds
        self._current_size = 0

    def _get_file_key(self, file_path: str) -> str:
        """生成文件缓存键"""
        # 包含文件路径和修改时间
        try:
            stat = os.stat(file_path)
            mtime = stat.st_mtime
            size = stat.st_size
            key_data = f"{file_path}:{mtime}:{size}"
        except:
            key_data = file_path
        return hashlib.md5(key_data.encode()).hexdigest()

    def _evict_if_needed(self):
        """缓存淘汰(LRU)"""
        now = time.time()
        to_remove = []

        # 清理过期条目
        for key, entry in self._cache.items():
            if now - entry.timestamp > self.ttl_seconds:
                to_remove.append(key)

        for key in to_remove:
            self._remove_entry(key)

        # 清理超大小条目
        while self._current_size > self.max_size_bytes and self._cache:
            oldest_key = next(iter(self._cache))
            self._remove_entry(oldest_key)

    def _remove_entry(self, key: str):
        """移除缓存条目"""
        if key in self._cache:
            entry = self._cache[key]
            self._current_size -= entry.size
            del self._cache[key]

    def get(self, file_path: str) -> Optional[str]:
        """获取文件内容"""
        key = self._get_file_key(file_path)
        if key in self._cache:
            entry = self._cache[key]
            # 检查是否过期
            if time.time() - entry.timestamp <= self.ttl_seconds:
                # 更新LRU
                self._cache.move_to_end(key)
                return entry.value
            else:
                self._remove_entry(key)
        return None

    def set(self, file_path: str, content: str):
        """设置文件内容缓存"""
        key = self._get_file_key(file_path)
        size = len(content.encode('utf-8'))

        # 如果已存在，先删除
        if key in self._cache:
            self._remove_entry(key)

        # 添加新条目
        self._cache[key] = CacheEntry(
            key=key,
            value=content,
            timestamp=time.time(),
            size=size
        )
        self._current_size += size

        # 淘汰
        self._evict_if_needed()

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._current_size = 0

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            'entries': len(self._cache),
            'size_bytes': self._current_size,
            'size_mb': self._current_size / 1024 / 1024,
            'max_size_mb': self.max_size_bytes / 1024 / 1024,
            'ttl_seconds': self.ttl_seconds
        }


# 全局文件缓存实例
_file_cache = FileCache()


def cached_file(max_size_mb: int = 100, ttl_seconds: int = 3600):
    """
    文件内容缓存装饰器

    Args:
        max_size_mb: 最大缓存大小(MB)
        ttl_seconds: 缓存生存时间(秒)

    Example:
        @cached_file()
        def read_file_cached(path: str) -> str:
            with open(path) as f:
                return f.read()
    """
    global _file_cache
    if _file_cache.max_size_bytes != max_size_mb * 1024 * 1024:
        _file_cache = FileCache(max_size_mb, ttl_seconds)

    def decorator(func: Callable[[str], str]) -> Callable[[str], str]:
        @wraps(func)
        def wrapper(file_path: str, *args, **kwargs) -> str:
            # 尝试从缓存获取
            cached = _file_cache.get(file_path)
            if cached is not None:
                return cached

            # 执行原函数
            result = func(file_path, *args, **kwargs)

            # 存入缓存
            _file_cache.set(file_path, result)

            return result
        return wrapper
    return decorator


class ResultCache:
    """工具结果缓存(持久化到磁盘)"""

    def __init__(self, cache_dir: str = ".cache/results"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._memory_cache: Dict[str, Any] = {}

    def _get_cache_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """生成缓存键"""
        key_data = {
            'func': func_name,
            'args': str(args),
            'kwargs': str(sorted(kwargs.items()))
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{key}.pkl")

    def get(self, func_name: str, args: tuple, kwargs: dict) -> Optional[Any]:
        """获取缓存结果"""
        key = self._get_cache_key(func_name, args, kwargs)

        # 先查内存缓存
        if key in self._memory_cache:
            return self._memory_cache[key]

        # 再查磁盘缓存
        cache_path = self._get_cache_path(key)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    result = pickle.load(f)
                    self._memory_cache[key] = result
                    return result
            except:
                pass

        return None

    def set(self, func_name: str, args: tuple, kwargs: dict, result: Any):
        """设置缓存结果"""
        key = self._get_cache_key(func_name, args, kwargs)

        # 存入内存缓存
        self._memory_cache[key] = result

        # 存入磁盘缓存
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(result, f)
        except:
            pass

    def clear(self):
        """清空缓存"""
        self._memory_cache.clear()
        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.pkl'):
                os.remove(os.path.join(self.cache_dir, filename))

    def clear_func(self, func_name: str):
        """清空特定函数的缓存"""
        # 清空内存缓存
        keys_to_remove = [k for k in self._memory_cache.keys() if k.startswith(func_name)]
        for key in keys_to_remove:
            del self._memory_cache[key]


# 全局结果缓存实例
_result_cache = ResultCache()


def cached_result(cache_dir: str = ".cache/results", ttl_seconds: Optional[int] = None):
    """
    工具结果缓存装饰器

    Args:
        cache_dir: 缓存目录
        ttl_seconds: 缓存生存时间(秒)

    Example:
        @cached_result()
        def expensive_computation(x: int, y: int) -> int:
            return x ** y
    """
    global _result_cache
    if _result_cache.cache_dir != cache_dir:
        _result_cache = ResultCache(cache_dir)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # 尝试从缓存获取
            cached = _result_cache.get(func.__name__, args, kwargs)
            if cached is not None:
                return cached

            # 执行原函数
            result = func(*args, **kwargs)

            # 存入缓存
            _result_cache.set(func.__name__, args, kwargs, result)

            return result
        return wrapper
    return decorator


# 便捷函数
def clear_file_cache():
    """清空文件缓存"""
    global _file_cache
    _file_cache.clear()


def clear_result_cache():
    """清空结果缓存"""
    global _result_cache
    _result_cache.clear()


def get_cache_stats() -> Dict[str, Any]:
    """获取缓存统计信息"""
    global _file_cache, _result_cache
    return {
        'file_cache': _file_cache.stats(),
        'result_cache': {
            'cache_dir': _result_cache.cache_dir,
            'memory_entries': len(_result_cache._memory_cache)
        }
    }