import json
from pathlib import Path


class DurationPredictor:
    """预测 API 请求耗时：elapsed = w1 * nc_k + w2 * out_k + w3 * c_k + b
    nc_k = non-cached input / 1000
    out_k = output / 1000
    c_k   = total input / 1000   （复杂度特征：输入总量越大任务越复杂）
    """

    def __init__(self, w1: float = 0.0, w2: float = 0.0, w3: float = 0.0, b: float = 2.0, n: int = 0):
        self.w1 = w1   # s / k non-cached input tokens
        self.w2 = w2   # s / k output tokens
        self.w3 = w3   # s / k total input tokens (complexity)
        self.b = b     # base overhead (seconds)
        self.n = n

    def predict(self, input_tokens: int, cache_hit_input: int, output_est: int) -> float:
        non_cached = max(input_tokens - cache_hit_input, 0)
        if self.n < 2:
            return 60.0
        nc_k = non_cached / 1000
        out_k = output_est / 1000
        c_k = input_tokens / 1000
        result = self.w1 * nc_k + self.w2 * out_k + self.w3 * c_k + self.b
        return max(1, min(300, result))

    def add(self, input_tokens: int, cache_hit_input: int, output_tokens: int, elapsed: float) -> None:
        non_cached = max(input_tokens - cache_hit_input, 0)
        nc_k = non_cached / 1000
        out_k = output_tokens / 1000
        c_k = input_tokens / 1000
        pred = self.w1 * nc_k + self.w2 * out_k + self.w3 * c_k + self.b
        error = elapsed - pred
        lr = 0.005 / (1 + self.n * 0.02)
        dw = max(-1, min(1, lr * error))
        self.w1 += max(-0.5, min(0.5, dw * nc_k))
        self.w2 += max(-0.5, min(0.5, dw * out_k))
        self.w3 += max(-0.5, min(0.5, dw * c_k))
        self.b += max(-2, min(2, dw))
        self.n += 1

    def to_dict(self) -> dict:
        return {"w1": self.w1, "w2": self.w2, "w3": self.w3, "b": self.b, "n": self.n}

    @classmethod
    def from_dict(cls, data: dict) -> "DurationPredictor":
        return cls(
            w1=data.get("w1", 0.0), w2=data.get("w2", 0.0),
            w3=data.get("w3", 0.0), b=data.get("b", 2.0), n=data.get("n", 0),
        )

    @staticmethod
    def _state_dir() -> Path:
        """返回 dekacode 安装目录下的 state/，用于全局持久化。"""
        p = Path(__file__).parent / "state"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def _state_path() -> Path:
        return DurationPredictor._state_dir() / "predictor.json"

    def save(self) -> None:
        path = self._state_path()
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls) -> "DurationPredictor":
        path = cls._state_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls.from_dict(data)
            except Exception:
                pass
        return cls()
