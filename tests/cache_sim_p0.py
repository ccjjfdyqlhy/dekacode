#!/usr/bin/env python3
"""P0 方案：Keepalive 缓存续期仿真。

与对照组相同场景，但在轮间间隙发送 keepalive 请求
保持服务端 prefix cache 活跃，使下一轮第一请求也获得高命中率。
"""

from dataclasses import dataclass

# ── 价格常量（与 token_counter.py 一致）──
FLASH_INPUT_CACHE_HIT = 0.02   # ¥/1M tokens
FLASH_INPUT_CACHE_MISS = 1.0   # ¥/1M tokens
FLASH_OUTPUT = 2.0              # ¥/1M tokens

# ── 仿真参数（与对照组完全一致）──
SYSTEM_TOKENS = 2000
PREFIX_TOKENS = 1700
NEW_USER_MSG_TOKENS = 80
ASSISTANT_OUTPUT_TOKENS = 2000
TOOL_RESULT_TOKENS_PER_CALL = 600
TOOL_LOOP_ITERATIONS = 3

CACHE_TTL_SEC = 60
IDLE_GAP_BETWEEN_TURNS = 90  # 轮间用户阅读+打字间隙
KEEPALIVE_INTERVAL = 30       # keepalive 发送间隔
NUM_TURNS = 5


@dataclass
class Request:
    turn: int
    iter: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost: float
    timestamp: float
    gap_from_prev: float
    kind: str  # "user" | "keepalive"
    note: str = ""


def sim_p0() -> list[Request]:
    """运行 P0 keepalive 仿真，返回所有请求记录。"""
    requests: list[Request] = []
    now = 0.0
    history_tokens = 0
    cache_expire_at = 0.0

    for turn in range(1, NUM_TURNS + 1):
        # ── 轮间间隙 + keepalive 续期 ──
        if turn > 1:
            gap_remaining = IDLE_GAP_BETWEEN_TURNS
            while gap_remaining > 0:
                step = min(KEEPALIVE_INTERVAL, gap_remaining)
                now += step
                gap_remaining -= step

                # Keepalive request
                ka_input = SYSTEM_TOKENS + PREFIX_TOKENS + history_tokens
                ka_output = 1  # max_tokens=1

                prev = requests[-1]
                gap = now - prev.timestamp

                if gap > CACHE_TTL_SEC:
                    # 缓存已过期，keepalive 自身也是冷启动
                    cached = SYSTEM_TOKENS + PREFIX_TOKENS
                    note = f"KA cold (gap={gap:.0f}s)"
                else:
                    cached = min(ka_input, prev.input_tokens)
                    note = "KA warm"

                miss = ka_input - cached
                cost = (cached * FLASH_INPUT_CACHE_HIT
                        + miss * FLASH_INPUT_CACHE_MISS
                        + ka_output * FLASH_OUTPUT) / 1_000_000

                ka = Request(
                    turn=turn - 1, iter=0,
                    input_tokens=ka_input,
                    output_tokens=ka_output,
                    cached_tokens=cached,
                    cost=cost,
                    timestamp=now,
                    gap_from_prev=gap,
                    kind="keepalive",
                    note=note,
                )
                requests.append(ka)
                cache_expire_at = now + CACHE_TTL_SEC
        else:
            # 第一轮无间隙
            pass

        # ── 用户第一请求 ──
        input_tok = SYSTEM_TOKENS + PREFIX_TOKENS + history_tokens + NEW_USER_MSG_TOKENS
        output_tok = ASSISTANT_OUTPUT_TOKENS

        prev = requests[-1] if requests else None
        gap = now - (prev.timestamp if prev else -999)
        cache_expired = gap > CACHE_TTL_SEC

        if cache_expired:
            cached = SYSTEM_TOKENS + PREFIX_TOKENS
            note = f"cache expired (gap={gap:.0f}s > TTL)"
        else:
            cached = min(input_tok, prev.input_tokens if prev else 0)
            note = "cache warm (keepalive worked!)"

        miss = input_tok - cached
        cost = (cached * FLASH_INPUT_CACHE_HIT
                + miss * FLASH_INPUT_CACHE_MISS
                + output_tok * FLASH_OUTPUT) / 1_000_000

        req1 = Request(
            turn=turn, iter=1,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cached_tokens=cached,
            cost=cost,
            timestamp=now,
            gap_from_prev=max(0, gap),
            kind="user",
            note=note,
        )
        requests.append(req1)
        cache_expire_at = now + CACHE_TTL_SEC
        last_user_ts = now

        # ── 后续工具循环迭代 ──
        for it in range(2, TOOL_LOOP_ITERATIONS + 1):
            now += 0.5
            prev = requests[-1]
            input_tok = prev.input_tokens + TOOL_RESULT_TOKENS_PER_CALL
            output_tok = ASSISTANT_OUTPUT_TOKENS

            gap = now - prev.timestamp
            cached = min(input_tok, prev.input_tokens)
            miss = input_tok - cached
            cost = (cached * FLASH_INPUT_CACHE_HIT
                    + miss * FLASH_INPUT_CACHE_MISS
                    + output_tok * FLASH_OUTPUT) / 1_000_000

            req = Request(
                turn=turn, iter=it,
                input_tokens=input_tok,
                output_tokens=output_tok,
                cached_tokens=cached,
                cost=cost,
                timestamp=now,
                gap_from_prev=gap,
                kind="user",
                note="tool loop (cache hot)",
            )
            requests.append(req)
            cache_expire_at = now + CACHE_TTL_SEC

        # 更新历史
        history_tokens += (NEW_USER_MSG_TOKENS
                           + ASSISTANT_OUTPUT_TOKENS
                           + TOOL_RESULT_TOKENS_PER_CALL * (TOOL_LOOP_ITERATIONS - 1))

    return requests


def fmt_cost(yuan: float) -> str:
    return f"¥{yuan:.4f}"


def print_results(requests: list[Request]):
    print(f"\n{'=' * 85}")
    print(f"  P0 方案：Keepalive 缓存续期")
    print(f"{'=' * 85}")
    print(f"  参数: TTL={CACHE_TTL_SEC}s  轮间隙={IDLE_GAP_BETWEEN_TURNS}s "
          f"KA间隔={KEEPALIVE_INTERVAL}s  轮数={NUM_TURNS}")
    print(f"  价格: hit ¥{FLASH_INPUT_CACHE_HIT}/M  miss ¥{FLASH_INPUT_CACHE_MISS}/M  out ¥{FLASH_OUTPUT}/M")
    print()

    header = (f"{'轮':>3} {'次':>3} {'类型':>9} {'输入tok':>9} {'出tok':>9} "
              f"{'缓存tok':>9} {'命中率':>7} {'成本':>10} {'间隔s':>6}  备注")
    print(header)
    print("-" * 85)

    total_cost = 0.0
    total_in = 0
    total_cache = 0
    ka_cost = 0.0
    ka_count = 0

    for r in requests:
        hit_pct = r.cached_tokens / r.input_tokens * 100 if r.input_tokens else 0
        kind_tag = "KA" if r.kind == "keepalive" else "USER"
        print(f"{r.turn:>3} {r.iter:>3} {kind_tag:>9} {r.input_tokens:>9} "
              f"{r.output_tokens:>9} {r.cached_tokens:>9} {hit_pct:>6.1f}% "
              f"{fmt_cost(r.cost):>10} {r.gap_from_prev:>5.0f}s  {r.note}")
        total_cost += r.cost
        total_in += r.input_tokens
        total_cache += r.cached_tokens
        if r.kind == "keepalive":
            ka_cost += r.cost
            ka_count += 1

    total_miss = total_in - total_cache
    overall_pct = total_cache / total_in * 100 if total_in else 0
    sep = "-" * 85
    print(sep)
    print(f"{'合计':>7} {'':>9} {total_in:>9} {sum(r.output_tokens for r in requests):>9} "
          f"{total_cache:>9} {overall_pct:>6.1f}% {fmt_cost(total_cost):>10}")

    # 单独统计 keepalive
    print()
    print(f"  ── Keepalive 开销 ──")
    print(f"  请求数: {ka_count}")
    print(f"  总成本: {fmt_cost(ka_cost)}")
    print(f"  占总成本: {ka_cost/total_cost*100:.1f}%")

    # 每轮首请求统计
    print(f"\n  ── 每轮首请求命中率 ──")
    prev_pct = None
    for r in requests:
        if r.kind == "user" and r.iter == 1:
            hp = r.cached_tokens / r.input_tokens * 100
            arrow = ""
            if prev_pct is not None:
                diff = hp - prev_pct
                arrow = f"  (较前轮首请求 {'↑' if diff >= 0 else '↓'} {abs(diff):.1f}pp)"
            prev_pct = hp
            print(f"    轮{r.turn} 首请求: 命中率 {hp:.1f}%  |  缓存 {r.cached_tokens}/{r.input_tokens}  |  成本 {fmt_cost(r.cost)}{arrow}")

    # 理想对照
    all_ideal = 0.0
    for r in requests:
        if r.kind == "user":
            ideal_cached = r.input_tokens
            ideal_miss = 0
            ideal_cost = (ideal_cached * FLASH_INPUT_CACHE_HIT
                          + ideal_miss * FLASH_INPUT_CACHE_MISS
                          + r.output_tokens * FLASH_OUTPUT) / 1_000_000
            all_ideal += ideal_cost

    print(f"\n  ── 总结 ──")
    print(f"  总成本 (含KA): {fmt_cost(total_cost)}")
    total_user = sum(r.cost for r in requests if r.kind == "user")
    print(f"  用户请求成本: {fmt_cost(total_user)}")
    print(f"  Keepalive成本: {fmt_cost(ka_cost)}")
    print(f"  理想成本 (100%全命中, 用户请求): {fmt_cost(all_ideal)}")
    waste = total_user - all_ideal
    print(f"  用户请求浪费: {fmt_cost(waste)} ({(total_user/all_ideal - 1)*100:.1f}% 额外)")


def main():
    requests = sim_p0()
    print_results(requests)


if __name__ == "__main__":
    main()
