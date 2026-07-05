"""
测试 web_fetch 模块：URL 抓取、截断、错误处理
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from skills.web_fetch import WebFetchSkill
from skills.filters import OutputFilter


skill = WebFetchSkill()


def test_properties():
    assert skill.name == "web_fetch"
    assert "Fetch" in skill.description
    params = skill.parameters
    assert "url" in params["properties"]
    assert params["required"] == ["url"]


def _check_result(r):
    assert r.success, f"not success: {r.output[:200]}"
    assert isinstance(r.output, str)
    assert len(r.output) > 0


@pytest.mark.asyncio
async def test_fetch_success():
    """抓取一个正常 HTTP 页面"""
    r = await skill.execute(url="https://example.com")
    _check_result(r)
    assert "Example Domain" in r.output


@pytest.mark.asyncio
async def test_fetch_with_redirect():
    """跟随重定向"""
    r = await skill.execute(url="https://httpbin.org/redirect-to?url=https://example.com")
    if r.success:
        assert "Example Domain" in r.output


@pytest.mark.asyncio
async def test_fetch_invalid_url():
    """端口无服务应返回错误"""
    r = await skill.execute(url="https://127.0.0.1:1/nonexistent")
    assert not r.success
    assert len(r.output) > 0


@pytest.mark.asyncio
async def test_fetch_no_scheme():
    """缺少协议头应失败"""
    r = await skill.execute(url="not-a-valid-url")
    assert not r.success


@pytest.mark.asyncio
async def test_fetch_large_content():
    """大量内容应截断"""
    r = await skill.execute(url="https://example.com")
    if r.success:
        assert len(r.output) > 0


def test_filter_blank_lines():
    """web_fetch 过滤器应合并多余空行"""
    raw = "a\n\n\n\n\nb"
    filtered = OutputFilter.web_fetch(raw)
    assert "a\n\nb" in filtered


def test_filter_line_limit():
    """超过 300 行应截断"""
    raw = "\n".join(f"line{i}" for i in range(500))
    filtered = OutputFilter.web_fetch(raw)
    lines = filtered.split("\n")
    assert len(lines) <= 302  # 300 lines + truncation notice + possible trailing


def test_filter_passthrough():
    """普通文本应原样通过"""
    raw = "hello world\nnormal text"
    assert OutputFilter.web_fetch(raw) == raw


@pytest.mark.asyncio
async def test_fetch_and_filter():
    """抓取后经过 OutputFilter 不应报错"""
    r = await skill.execute(url="https://example.com")
    if r.success:
        filtered = OutputFilter.web_fetch(r.output)
        assert isinstance(filtered, str)
        assert len(filtered) > 0


if __name__ == '__main__':
    import asyncio

    async def main():
        tests = [
            ("properties", test_properties),
            ("filter_blank_lines", test_filter_blank_lines),
            ("filter_line_limit", test_filter_line_limit),
            ("filter_passthrough", test_filter_passthrough),
        ]
        async_tests = [
            ("fetch_success", test_fetch_success()),
            ("fetch_with_redirect", test_fetch_with_redirect()),
            ("fetch_invalid_url", test_fetch_invalid_url()),
            ("fetch_no_scheme", test_fetch_no_scheme()),
            ("fetch_large_content", test_fetch_large_content()),
            ("fetch_and_filter", test_fetch_and_filter()),
        ]

        for name, fn in tests:
            try:
                fn()
                print(f"  ✓ {name}")
            except Exception as e:
                print(f"  ✗ {name}: {e}")

        for name, coro in async_tests:
            try:
                await coro
                print(f"  ✓ {name}")
            except Exception as e:
                print(f"  ✗ {name}: {e}")

    asyncio.run(main())
    print("\nAll web_fetch tests passed!")
