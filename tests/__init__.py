"""
测试运行器
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入所有测试模块
from tests import test_batch
from tests import test_cache
from tests import test_chunk
from tests import test_locator
from tests import test_diagnose
from tests import test_incremental
from tests import test_summary
from tests import test_snapshot


def run_all_tests():
    """运行所有测试"""
    tests = [
        ("Batch", test_batch),
        ("Cache", test_cache),
        ("Chunk", test_chunk),
        ("Locator", test_locator),
        ("Diagnose", test_diagnose),
        ("Incremental", test_incremental),
        ("Summary", test_summary),
        ("Snapshot", test_snapshot),
    ]

    failed = []
    passed = []

    for name, module in tests:
        print(f"\n{'='*50}")
        print(f"Running {name} tests...")
        print(f"{'='*50}")

        try:
            # 查找所有test_函数并执行
            test_functions = [
                getattr(module, func_name)
                for func_name in dir(module)
                if func_name.startswith('test_') and callable(getattr(module, func_name))
            ]

            for test_func in test_functions:
                try:
                    test_func()
                    print(f"✓ {test_func.__name__}")
                    passed.append(f"{name}.{test_func.__name__}")
                except Exception as e:
                    print(f"✗ {test_func.__name__}: {e}")
                    failed.append(f"{name}.{test_func.__name__}")

        except Exception as e:
            print(f"✗ Failed to load {name} tests: {e}")
            failed.append(name)

    # 打印总结
    print(f"\n{'='*50}")
    print("Test Summary")
    print(f"{'='*50}")
    print(f"Passed: {len(passed)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print(f"\nFailed tests:")
        for test in failed:
            print(f"  - {test}")
        return 1
    else:
        print("\n✓ All tests passed!")
        return 0


if __name__ == '__main__':
    sys.exit(run_all_tests())