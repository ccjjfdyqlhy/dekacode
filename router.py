from dataclasses import dataclass, field
from datetime import datetime


PEAK_HOUR_RANGES = ((9, 12), (14, 18))


def in_peak_hours() -> bool:
    h = datetime.now().hour
    for start, end in PEAK_HOUR_RANGES:
        if start <= h < end:
            return True
    return False


@dataclass
class ModelConfig:
    flash_model: str = "deepseek-v4-flash"
    pro_model: str = "deepseek-v4-pro"
    flash_api_key: str = ""
    flash_base_url: str = ""
    pro_api_key: str = ""
    pro_base_url: str = ""
    auto_downgrade_on_peak: bool = True
    downgrade_after_retries: int = 3


@dataclass
class ModelRouter:
    config: ModelConfig = field(default_factory=ModelConfig)
    current_model: str = "flash"
    manual_override: str | None = None

    def select(self, task_type: str = "") -> str:
        if self.manual_override:
            return self.manual_override

        peak = in_peak_hours()
        cheap_tasks = ("search", "summary", "simple_edit", "list", "glob", "grep")

        if task_type in cheap_tasks:
            return "flash"

        if peak and self.config.auto_downgrade_on_peak:
            return "flash"

        return self.current_model

    def switch(self, mode: str) -> str:
        if mode == "flash":
            self.manual_override = "flash"
            self.current_model = "flash"
        elif mode == "pro":
            self.manual_override = "pro"
            self.current_model = "pro"
        elif mode == "auto":
            self.manual_override = None
            self.current_model = "flash"
        return self.current_model

    def get_model_name(self, mode: str) -> str:
        if mode == "pro":
            return self.config.pro_model
        return self.config.flash_model

    def get_model_config(self, mode: str) -> dict:
        if mode == "pro":
            return {
                "model": self.config.pro_model,
                "api_key": self.config.pro_api_key,
                "base_url": self.config.pro_base_url,
            }
        return {
            "model": self.config.flash_model,
            "api_key": self.config.flash_api_key,
            "base_url": self.config.flash_base_url,
        }
