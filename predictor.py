"""基于 OLS 的请求耗时预测器，数据持久化到 chat_store。"""


class DurationPredictor:
    """预测 API 请求耗时：elapsed = w1 * nc_k + w2 * out_k + b
    特征以千 token 为单位，确保权重在合理数值范围。
    """

    def __init__(self, w1: float = 0.0, w2: float = 0.0, b: float = 2.0, n: int = 0):
        self.w1 = w1   # s / k non-cached input tokens
        self.w2 = w2   # s / k output tokens
        self.b = b     # base overhead (seconds)
        self.n = n

    def predict(self, input_tokens: int, cache_hit_input: int, output_est: int) -> float:
        non_cached = max(input_tokens - cache_hit_input, 0)
        if self.n < 2:
            return 60.0
        result = self.w1 * (non_cached / 1000) + self.w2 * (output_est / 1000) + self.b
        return max(1, min(300, result))

    def add(self, input_tokens: int, cache_hit_input: int, output_tokens: int, elapsed: float) -> None:
        non_cached = max(input_tokens - cache_hit_input, 0)
        nc_k = non_cached / 1000
        out_k = output_tokens / 1000
        pred = self.w1 * nc_k + self.w2 * out_k + self.b
        error = elapsed - pred
        lr = 0.005 / (1 + self.n * 0.02)
        dw = max(-1, min(1, lr * error))
        self.w1 += max(-0.5, min(0.5, dw * nc_k))
        self.w2 += max(-0.5, min(0.5, dw * out_k))
        self.b += max(-2, min(2, dw))
        self.n += 1

    def to_dict(self) -> dict:
        return {"w1": self.w1, "w2": self.w2, "b": self.b, "n": self.n}

    @classmethod
    def from_dict(cls, data: dict) -> "DurationPredictor":
        return cls(w1=data.get("w1", 0.0), w2=data.get("w2", 0.0),
                   b=data.get("b", 2.0), n=data.get("n", 0))
