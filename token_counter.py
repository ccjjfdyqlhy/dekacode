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


@dataclass
class UsageRecord:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_input: int = 0
    cache_miss_input: int = 0
    cost: float = 0.0
    peak_hours: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class TokenCounter:
    records: list[UsageRecord] = field(default_factory=list)
    session_cost: float = 0.0

    def record(self, response: dict, model: str = "flash") -> UsageRecord:
        usage = response.get("usage", {})
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
        )
        self.records.append(rec)
        self.session_cost += cost
        return rec

    def display(self, rec: UsageRecord) -> str:
        peak_tag = " ⚡peak" if rec.peak_hours else ""
        hit_pct = (rec.cache_hit_input / rec.input_tokens * 100) if rec.input_tokens > 0 else 0
        return (
            f"[Tokens] ↑{rec.input_tokens} in "
            f"(cache:{rec.cache_hit_input}/{hit_pct:.0f}%) "
            f"| ↓{rec.output_tokens} out "
            f"| ¥{rec.cost:.4f}{peak_tag}"
        )

    def session_summary(self) -> str:
        total_in = sum(r.input_tokens for r in self.records)
        total_out = sum(r.output_tokens for r in self.records)
        total_cache = sum(r.cache_hit_input for r in self.records)
        return (
            f"[Session] ↑{total_in} in | ↓{total_out} out "
            f"| cache:{total_cache}/{total_in-total_cache} "
            f"| ¥{self.session_cost:.4f}"
        )
