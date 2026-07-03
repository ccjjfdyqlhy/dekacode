import json
import os
from datetime import datetime
from pathlib import Path


class SessionLogger:
    def __init__(self, log_dir: str = ".opencode_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.records: list[dict] = []
        self.start_time = datetime.now()

    def log_turn(self, turn_data: dict) -> None:
        self.records.append(turn_data)

    def save(self) -> dict:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        data = {
            "session_id": self.session_id,
            "started_at": self.start_time.isoformat(),
            "duration_seconds": elapsed,
            "peak_hours": self._in_peak(),
            "total_turns": len(self.records),
            "records": self.records,
        }

        if self.records:
            data["total_input_tokens"] = sum(r.get("input_tokens", 0) for r in self.records)
            data["total_output_tokens"] = sum(r.get("output_tokens", 0) for r in self.records)
            data["total_cost"] = sum(r.get("cost", 0.0) for r in self.records)
            hit = sum(r.get("cache_hit_input", 0) for r in self.records)
            total_in = data["total_input_tokens"]
            data["cache_hit_rate"] = hit / total_in if total_in > 0 else 0

        fpath = self.log_dir / f"session_{self.session_id}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return data

    def _in_peak(self) -> bool:
        h = datetime.now().hour
        for start, end in ((9, 12), (14, 18)):
            if start <= h < end:
                return True
        return False
