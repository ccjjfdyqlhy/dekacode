#!/usr/bin/env python3
"""对照实验：Control（无 Keepalive） vs P0（Keepalive 缓存续期）。

直接引用两个仿真的核心逻辑，输出合并对比表。
"""

import sys
import os

# 引入两个仿真模块
sys.path.insert(0, os.path.dirname(__file__))
from cache_sim_control import (
    sim_control, SYSTEM_TOKENS, PREFIX_TOKENS, NEW_USER_MSG_TOKENS,
    ASSISTANT_OUTPUT_TOKENS, TOOL_RESULT_TOKENS_PER_CALL, TOOL_LOOP_ITERATIONS,
    CACHE_TTL_SEC, IDLE_GAP_BETWEEN_TURNS, NUM_TURNS, FLASH_INPUT_CACHE_HIT,
    FLASH_INPUT_CACHE_MISS, FLASH_OUTPUT,
)
from cache_sim_p0 import sim_p0, KEEPALIVE_INTERVAL


def fmt(y: float) -> str:
    return f"¥{y:.4f}"


def _cost_fmt(y):
    return f"¥{y:.4f}"

def _pct_fmt(y):
    return f"{y:.1f}%"

def _int_fmt(y):
    return f"{int(y):,}"

def main():
    control_reqs = sim_control()
    p0_reqs = sim_p0()

    def stats(reqs):
        total_cost = sum(r.cost for r in reqs)
        total_user_cost = sum(r.cost for r in reqs if getattr(r, 'kind', 'user') == 'user')
        total_in = sum(r.input_tokens for r in reqs)
        total_cache = sum(r.cached_tokens for r in reqs)

        first_hits = []
        first_costs = []
        loop_hits = []
        for r in reqs:
            kind = getattr(r, 'kind', 'user')
            if kind != 'user':
                continue
            hp = r.cached_tokens / r.input_tokens * 100 if r.input_tokens else 0
            if r.iter == 1:
                first_hits.append(hp)
                first_costs.append(r.cost)
            else:
                loop_hits.append(hp)

        ka_cost = total_cost - total_user_cost
        ka_count = sum(1 for r in reqs if getattr(r, 'kind', None) == 'keepalive')

        return {
            "total_cost": total_cost,
            "total_user_cost": total_user_cost,
            "total_in": total_in,
            "total_cache": total_cache,
            "total_miss": total_in - total_cache,
            "overall_hit": total_cache / total_in * 100 if total_in else 0,
            "first_avg_hit": (sum(first_hits) / len(first_hits)) if first_hits else 0,
            "first_avg_cost": (sum(first_costs) / len(first_costs)) if first_costs else 0,
            "loop_avg_hit": (sum(loop_hits) / len(loop_hits)) if loop_hits else 0,
            "ka_cost": ka_cost,
            "ka_count": ka_count,
            "first_hits": first_hits,
        }

    cs = stats(control_reqs)
    ps = stats(p0_reqs)

    print("=" * 80)
    print("  缓存策略对比实验")
    print("=" * 80)
    print(f"  参数: TTL={CACHE_TTL_SEC}s  轮间隙={IDLE_GAP_BETWEEN_TURNS}s  "
          f"轮数={NUM_TURNS}  每轮工具循环={TOOL_LOOP_ITERATIONS}次")
    print(f"  Keepalive间隔={KEEPALIVE_INTERVAL}s  "
          f"价格: hit ¥{FLASH_INPUT_CACHE_HIT}/M  miss ¥{FLASH_INPUT_CACHE_MISS}/M")
    print()

    def row(label, c_val, p_val, fmt_c=_cost_fmt, fmt_p=None, better="lower"):
        if fmt_p is None:
            fmt_p = fmt_c
        cv = fmt_c(c_val)
        pv = fmt_p(p_val)
        if isinstance(c_val, (int, float)) and c_val != 0:
            chg = (p_val - c_val) / abs(c_val) * 100
            if better == "lower":
                arrow = "↓" if p_val < c_val else "↑"
            else:
                arrow = "↑" if p_val > c_val else "↓"
            chg_str = f"{arrow} {abs(chg):.1f}%"
        else:
            chg_str = "-"
        print(f"  {label:<28} {cv:>20} {pv:>20} {chg_str:>15}")

    row("总成本", cs["total_cost"], ps["total_cost"])
    row("用户请求成本", cs["total_user_cost"], ps["total_user_cost"])
    row("Keepalive 成本", 0, ps["ka_cost"])
    row("综合命中率", cs["overall_hit"], ps["overall_hit"], fmt_c=_pct_fmt, better="higher")
    row("首请求平均命中率", cs["first_avg_hit"], ps["first_avg_hit"], fmt_c=_pct_fmt, better="higher")
    row("首请求平均成本", cs["first_avg_cost"], ps["first_avg_cost"])
    row("工具循环平均命中率", cs["loop_avg_hit"], ps["loop_avg_hit"], fmt_c=_pct_fmt, better="higher")
    row("总输入 (tokens)", cs["total_in"], ps["total_in"], fmt_c=_int_fmt, fmt_p=_int_fmt)
    row("缓存命中 (tokens)", cs["total_cache"], ps["total_cache"], fmt_c=_int_fmt, fmt_p=_int_fmt, better="higher")
    row("缓存未命中 (tokens)", cs["total_miss"], ps["total_miss"], fmt_c=_int_fmt, fmt_p=_int_fmt)
    row("Keepalive 请求数", 0, ps["ka_count"], fmt_c=_int_fmt, fmt_p=_int_fmt)

    print()
    print("  ── 每轮首请求命中率趋势 ──")
    print(f"  {'轮次':<6} {'CONTROL':>15} {'P0':>15}")
    print(f"  {'-'*6} {'-'*15} {'-'*15}")
    for i in range(NUM_TURNS):
        c_hit = cs["first_hits"][i] if i < len(cs["first_hits"]) else 0
        p_hit = ps["first_hits"][i] if i < len(ps["first_hits"]) else 0
        print(f"  {i+1:<6} {c_hit:>14.1f}% {p_hit:>14.1f}%")

    avg_impr = ps["first_avg_hit"] - cs["first_avg_hit"]
    cost_saved = cs["total_cost"] - ps["total_cost"]
    print(f"\n  ── 结论 ──")
    print(f"  首请求平均命中率: {cs['first_avg_hit']:.1f}% → {ps['first_avg_hit']:.1f}% (↑{avg_impr:.1f}pp)")
    print(f"  总成本: {_cost_fmt(cs['total_cost'])} → {_cost_fmt(ps['total_cost'])} (节省 {_cost_fmt(cost_saved)})")
    print(f"  成本降幅: {(cost_saved) / cs['total_cost'] * 100:.1f}%")
    print(f"  Keepalive 开销: {_cost_fmt(ps['ka_cost'])} ({ps['ka_cost']/ps['total_cost']*100:.1f}% of total)")
    if ps['ka_cost'] > 0:
        roi = cost_saved / ps['ka_cost']
        print(f"  ROI: 每 ¥1 keepalive 投入，节省 ¥{roi:.1f} 用户请求成本")
    print()


if __name__ == "__main__":
    main()
