import json
from datetime import datetime
from pathlib import Path

from models import Message, ToolDefinition


class SessionLogger:
    def __init__(self, log_dir: str = ".dekacode/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        self.session_id = now.strftime("%Y%m%d_%H%M%S")
        self._path = self.log_dir / f"session_{self.session_id}.log"
        self._file = open(self._path, "w", encoding="utf-8")
        self._turn_count = 0
        self._call_count = 0
        self._write(f"Session {self.session_id}  started at {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._write("=" * 60 + "\n\n")

    def _write(self, text: str) -> None:
        self._file.write(text)
        self._file.flush()

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def log_turn_start(self, user_input: str, model: str) -> None:
        self._turn_count += 1
        self._call_count = 0
        self._write(f"{'─' * 80}\n")
        self._write(f"  Turn {self._turn_count}  │  model: {model}  │  user: {user_input[:200]}\n")
        self._write(f"{'─' * 80}\n\n")

    def log_request(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        model: str,
        max_tokens: int | None,
    ) -> None:
        self._call_count += 1
        self._write(f"─── Request {self._call_count} @ {self._ts()} ───────────────────────────────────────────────\n")
        self._write("[MODEL INPUT]\n")
        body = {
            "model": model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = [t.model_dump(exclude_none=True) for t in tools]
        self._write(json.dumps(body, ensure_ascii=False, indent=2) + "\n\n")

    def log_response(self, response: dict, elapsed: float, usage_text: str) -> None:
        self._write(f"─── Response {self._call_count} (elapsed: {elapsed:.1f}s) ─────────────────────────────────────\n")
        self._write("[MODEL OUTPUT]\n")
        self._write(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
        self._write(f"[{usage_text}]\n\n")

    def log_turn_summary(self, summary: dict) -> None:
        self._write(f"  Turn summary: {json.dumps(summary, ensure_ascii=False)}\n\n")

    def close(self) -> None:
        if self._file.closed:
            return
        self._write(f"Session ended at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._file.close()

    @property
    def path(self) -> str:
        return str(self._path)
