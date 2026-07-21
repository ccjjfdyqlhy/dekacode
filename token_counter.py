from dataclasses import dataclass, field
from datetime import datetime


FLASH_INPUT_CACHE_HIT = 0.02
FLASH_INPUT_CACHE_MISS = 1.0
FLASH_OUTPUT = 2.0
PRO_INPUT_CACHE_HIT = 0.025
PRO_INPUT_CACHE_MISS = 3.0
PRO_OUTPUT = 6.0

PEAK_HOUR_RANGES = ((9, 12), (14, 18))


def _in_peak_hours() -> bool:
    now = datetime.now()
    h = now.hour
    for start, end in PEAK_HOUR_RANGES:
        if start <= h < end:
            return True
    return False


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


@dataclass
class UsageRecord:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_input: int = 0
    cache_miss_input: int = 0
    cost: float = 0.0
    peak_hours: bool = False
    elapsed: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class TokenCounter:
    records: list[UsageRecord] = field(default_factory=list)
    session_cost: float = 0.0

    def record(self, response: dict, model: str = "flash", elapsed: float = 0.0) -> UsageRecord:
        usage = response.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) if isinstance(usage.get("prompt_tokens_details"), dict) else 0

        miss_input = prompt_tokens - cached_tokens
        peak = _in_peak_hours()
        peak_mult = 2.0 if peak else 1.0

        if model == "pro":
            cost = (
                cached_tokens * PRO_INPUT_CACHE_HIT
                + miss_input * PRO_INPUT_CACHE_MISS
                + completion_tokens * PRO_OUTPUT
            ) * peak_mult / 1_000_000
        else:
            cost = (
                cached_tokens * FLASH_INPUT_CACHE_HIT
                + miss_input * FLASH_INPUT_CACHE_MISS
                + completion_tokens * FLASH_OUTPUT
            ) * peak_mult / 1_000_000

        rec = UsageRecord(
            model=model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cache_hit_input=cached_tokens,
            cache_miss_input=miss_input,
            cost=cost,
            peak_hours=peak,
            elapsed=elapsed,
        )
        self.records.append(rec)
        self.session_cost += cost
        return rec

    def display(self, rec: UsageRecord) -> str:
        if rec.input_tokens == 0 and rec.output_tokens == 0:
            time_tag = f"[magenta]{rec.elapsed:.1f}s[/]" if rec.elapsed else ""
            return time_tag
        peak_tag = " [red]⚡[/]" if rec.peak_hours else ""
        hit_pct = (rec.cache_hit_input / rec.input_tokens * 100) if rec.input_tokens > 0 else 0
        time_tag = f" [magenta]{rec.elapsed:.1f}s[/]" if rec.elapsed else ""
        return (
            f"  [yellow]↑[/] {fmt_tokens(rec.input_tokens)} [dim]in[/] "
            f"[dim](cache [/]{fmt_tokens(rec.cache_hit_input)}/{hit_pct:.0f}%[dim])[/] "
            f"[cyan]↓[/] {fmt_tokens(rec.output_tokens)} [dim]out[/] "
            f"[dim]│[/] [bold yellow]¥{rec.cost:.4f}[/]{peak_tag}{time_tag}"
        )

    def session_summary(self) -> str:
        total_in = sum(r.input_tokens for r in self.records)
        total_out = sum(r.output_tokens for r in self.records)
        total_cache = sum(r.cache_hit_input for r in self.records)
        total_elapsed = sum(r.elapsed for r in self.records)
        time_tag = f"  [magenta]{total_elapsed:.1f}s[/]" if total_elapsed else ""
        if total_in == 0 and total_out == 0:
            return f"  [dim]Usage not supported[/]{time_tag}"
        return (
            f"  [yellow]∑[/] {fmt_tokens(total_in)} [dim]in[/] "
            f"[cyan]↓[/] {fmt_tokens(total_out)} [dim]out[/] "
            f"[dim]cache [/]{fmt_tokens(total_cache)}/{fmt_tokens(total_in-total_cache)} "
            f"[dim]│[/] [bold yellow]¥{self.session_cost:.4f}[/]{time_tag}"
        )
