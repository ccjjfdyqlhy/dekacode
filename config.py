import os
from pathlib import Path

from pydantic_settings import BaseSettings

_DEKACODE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    provider: str = "openai"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "local-model"

    flash_model: str = "deepseek-v4-flash"
    flash_api_key: str = ""
    flash_base_url: str = ""

    pro_model: str = "deepseek-v4-pro"
    pro_api_key: str = ""
    pro_base_url: str = ""

    auto_downgrade_on_peak: bool = True
    default_model: str = "flash"
    log_dir: str = ".opencode_logs"
    max_session_cost: float = 0.0

    model_config = {
        "env_file": _DEKACODE_DIR / ".env",
        "env_file_encoding": "utf-8",
    }
