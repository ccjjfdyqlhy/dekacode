#!/usr/bin/env python3
"""对照组：当前无 keepalive 行为仿真。

模拟多轮对话中服务端 prefix cache 因轮间间隙过期，
导致每轮第一请求命中率低的场景。
"""

import textwrap
from dataclasses import dataclass, field

# ── 价格常量（与 token_counter.py 一致）──
FLASH_INPUT_CACHE_HIT = 0.02   # ¥/1M tokens
FLASH_INPUT_CACHE_MISS = 1.0   # ¥/1M tokens
FLASH_OUTPUT = 2.0              # ¥/1M tokens

# ── 仿真参数 ──
SYSTEM_TOKENS = 2000
PREFIX_TOKENS = 1700  # compact_map
NEW_USER_MSG_TOKENS = 80
ASSISTANT_OUTPUT_TOKENS = 2000
TOOL_RESULT_TOKENS_PER_CALL = 600
TOOL_LOOP_ITERATIONS = 3  # 每轮包含 1 次思考 + 2 次工具循环

CACHE_TTL_SEC = 60
IDLE_GAP_BETWEEN_TURNS = 90  # 轮间用户阅读+打字间隙

NUM_TURNS = 5


@dataclass
class SimRequest:
    turn: int
    iter: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost: float
    timestamp: float
    gap_from_prev: float
    note: str = ""


def sim_control() -> list[SimRequest]:
    """运行对照仿真，返回所有请求记录。"""
    requests: list[SimRequest] = []
    now = 0.0
    history_tokens = 0  # 当前 history 区总 token 数
    cache_expire_at = 0.0  # 缓存过期时间戳

    for turn in range(1, NUM_TURNS + 1):
        # ── 轮间间隙（第二轮起）──
        if turn > 1:
            now += IDLE_GAP_BETWEEN_TURNS

        # ── 第一请求：新用户消息 ──
        new_history = (NEW_USER_MSG_TOKENS
                       + ASSISTANT_OUTPUT_TOKENS
                       + TOOL_RESULT_TOKENS_PER_CALL * (TOOL_LOOP_ITERATIONS - 1))

        input_tok = SYSTEM_TOKENS + PREFIX_TOKENS + history_tokens + NEW_USER_MSG_TOKENS
        output_tok = ASSISTANT_OUTPUT_TOKENS

        gap = now - (requests[-1].timestamp if requests else -999)
        cache_expired = gap > CACHE_TTL_SEC

        if cache_expired:
            # 只有 system + prefix 还可能存活（全局稳定前缀）
            cached = SYSTEM_TOKENS + PREFIX_TOKENS
            note = f"cache expired (gap={gap:.0f}s > TTL={CACHE_TTL_SEC}s)"
        else:
            cached = min(input_tok, requests[-1].input_tokens if requests else 0)
            note = "cache warm"

        miss = input_tok - cached
        cost = (cached * FLASH_INPUT_CACHE_HIT
                + miss * FLASH_INPUT_CACHE_MISS
                + output_tok * FLASH_OUTPUT) / 1_000_000

        req1 = SimRequest(
            turn=turn, iter=1,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cached_tokens=cached,
            cost=cost,
            timestamp=now,
            gap_from_prev=max(0, gap),
            note=note,
        )
        requests.append(req1)
        cache_expire_at = now + CACHE_TTL_SEC

        # ── 后续工具循环迭代（毫秒级间隔，缓存保持热）──
        for it in range(2, TOOL_LOOP_ITERATIONS + 1):
            now += 0.5  # 工具执行+API往返时间
            prev = requests[-1]
            input_tok = prev.input_tokens + TOOL_RESULT_TOKENS_PER_CALL
            output_tok = ASSISTANT_OUTPUT_TOKENS

            gap = now - prev.timestamp
            # 缓存未过期（gap ≪ TTL）
            cached = min(input_tok, prev.input_tokens)
            miss = input_tok - cached
            cost = (cached * FLASH_INPUT_CACHE_HIT
                    + miss * FLASH_INPUT_CACHE_MISS
                    + output_tok * FLASH_OUTPUT) / 1_000_000

            req = SimRequest(
                turn=turn, iter=it,
                input_tokens=input_tok,
                output_tokens=output_tok,
                cached_tokens=cached,
                cost=cost,
                timestamp=now,
                gap_from_prev=gap,
                note="tool loop (cache hot)",
            )
            requests.append(req)
            cache_expire_at = now + CACHE_TTL_SEC

        # 更新历史 token 数供下一轮使用
        history_tokens += (NEW_USER_MSG_TOKENS
                           + ASSISTANT_OUTPUT_TOKENS
                           + TOOL_RESULT_TOKENS_PER_CALL * (TOOL_LOOP_ITERATIONS - 1))

    return requests


def fmt_cost(yuan: float) -> str:
    return f"¥{yuan:.4f}"


def print_results(requests: list[SimRequest], title: str):
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")
    print(f"  参数: TTL={CACHE_TTL_SEC}s  轮间隙={IDLE_GAP_BETWEEN_TURNS}s  轮数={NUM_TURNS}")
    print(f"  价格: hit ¥{FLASH_INPUT_CACHE_HIT}/M  miss ¥{FLASH_INPUT_CACHE_MISS}/M  out ¥{FLASH_OUTPUT}/M")
    print()

    header = f"{'轮':>3} {'次':>3} {'输入tok':>9} {'输出tok':>9} {'缓存tok':>9} {'命中率':>7} {'成本':>10} {'间隔s':>6}  备注"
    print(header)
    print("-" * 80)

    total_cost = 0.0
    total_in = 0
    total_cache = 0

    for r in requests:
        hit_pct = r.cached_tokens / r.input_tokens * 100 if r.input_tokens else 0
        print(f"{r.turn:>3} {r.iter:>3} {r.input_tokens:>9} {r.output_tokens:>9} "
              f"{r.cached_tokens:>9} {hit_pct:>6.1f}% {fmt_cost(r.cost):>10} "
              f"{r.gap_from_prev:>5.0f}s  {r.note}")
        total_cost += r.cost
        total_in += r.input_tokens
        total_cache += r.cached_tokens

    # 汇总
    total_miss = total_in - total_cache
    overall_pct = total_cache / total_in * 100 if total_in else 0
    sep = "-" * 80
    print(sep)
    print(f"{'合计':>7} {total_in:>9} {sum(r.output_tokens for r in requests):>9} "
          f"{total_cache:>9} {overall_pct:>6.1f}% {fmt_cost(total_cost):>10}")
    print()

    # 每轮首请求统计
    print("  ── 每轮首请求命中率变化 ──")
    prev_first_hit = None
    for r in requests:
        if r.iter == 1:
            hp = r.cached_tokens / r.input_tokens * 100
            arrow = ""
            if prev_first_hit is not None:
                diff = hp - prev_first_hit
                arrow = f"  (较前轮首请求 {'↑' if diff > 0 else '↓'} {abs(diff):.1f}pp)"
            prev_first_hit = hp
            print(f"    轮{r.turn} 首请求: 命中率 {hp:.1f}%  |  缓存 {r.cached_tokens}/{r.input_tokens}  |  成本 {fmt_cost(r.cost)}{arrow}")

    print(f"\n  ── 总结 ──")
    print(f"  总成本: {fmt_cost(total_cost)}")
    print(f"  总输入: {total_in} tokens (缓存 {total_cache}, 未命中 {total_miss})")
    print(f"  综合命中率: {overall_pct:.1f}%")

    # 计算理想情况（100%命中所有历史）的成本对比
    all_ideal = 0.0
    for r in requests:
        ideal_cached = r.input_tokens
        ideal_miss = 0
        ideal_cost = (ideal_cached * FLASH_INPUT_CACHE_HIT
                      + ideal_miss * FLASH_INPUT_CACHE_MISS
                      + r.output_tokens * FLASH_OUTPUT) / 1_000_000
        all_ideal += ideal_cost
    print(f"  理想成本 (100%全命中): {fmt_cost(all_ideal)}")
    print(f"  浪费: {fmt_cost(total_cost - all_ideal)} ({(total_cost/all_ideal - 1)*100:.1f}% 额外)")


def main():
    requests = sim_control()
    print_results(requests, "对照组：无 Keepalive（当前行为）")


if __name__ == "__main__":
    main()
