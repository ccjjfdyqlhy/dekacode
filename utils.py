import httpx

from config import Settings
from models import Message, ToolDefinition


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._setup_providers()

    def _setup_providers(self) -> None:
        if self.settings.provider == "lmstudio":
            self._providers = {
                "flash": {
                    "base_url": self.settings.lmstudio_base_url.rstrip("/"),
                    "api_key": "",
                    "model": self.settings.lmstudio_model,
                },
                "pro": {
                    "base_url": self.settings.lmstudio_base_url.rstrip("/"),
                    "api_key": "",
                    "model": self.settings.lmstudio_model,
                },
            }
        else:
            self._providers = {
                "flash": {
                    "base_url": (self.settings.flash_base_url or self.settings.openai_base_url).rstrip("/"),
                    "api_key": self.settings.flash_api_key or self.settings.openai_api_key,
                    "model": self.settings.flash_model or self.settings.openai_model,
                },
                "pro": {
                    "base_url": (self.settings.pro_base_url or self.settings.openai_base_url).rstrip("/"),
                    "api_key": self.settings.pro_api_key or self.settings.openai_api_key,
                    "model": self.settings.pro_model or self.settings.openai_model,
                },
            }

        self.model = self._providers["flash"]["model"]
        self.base_url = self._providers["flash"]["base_url"]
        self.api_key = self._providers["flash"]["api_key"]

    def switch_model(self, mode: str) -> str:
        cfg = self._providers.get(mode, self._providers["flash"])
        self.model = cfg["model"]
        self.base_url = cfg["base_url"]
        self.api_key = cfg["api_key"]
        return self.model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        model_mode: str = "flash",
    ) -> dict:
        if model_mode != "flash":
            self.switch_model(model_mode)

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            body["tools"] = [t.model_dump(exclude_none=True) for t in tools]
            body["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            if resp.status_code == 401:
                raise PermissionError("Authentication failed — check your API key")
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                error_body = resp.text
                raise RuntimeError(
                    f"HTTP {resp.status_code}: {error_body[:2000]}"
                ) from e
            return resp.json()


