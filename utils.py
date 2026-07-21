import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from config import Settings
from models import Message, ToolDefinition


@dataclass
class StreamChunk:
    delta_content: str | None = None
    delta_reasoning: str | None = None
    delta_tool_calls: list | None = None
    finish_reason: str | None = None
    usage: dict | None = None


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
                "openai": {
                    "base_url": self.settings.openai_base_url.rstrip("/"),
                    "api_key": self.settings.openai_api_key,
                    "model": self.settings.openai_model,
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
                "openai": {
                    "base_url": self.settings.openai_base_url.rstrip("/"),
                    "api_key": self.settings.openai_api_key,
                    "model": self.settings.openai_model,
                },
            }

        self.model = self._providers["flash"]["model"]
        self.base_url = self._providers["flash"]["base_url"]
        self.api_key = self._providers["flash"]["api_key"]

    def list_models(self) -> list[dict]:
        return [
            {"id": k, "label": k.capitalize(), "model": v["model"]}
            for k, v in self._providers.items()
        ]

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
        max_tokens: int | None = None,
        temperature: float | None = None,
        tool_choice: str | None = None,
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
            body["tool_choice"] = tool_choice or "auto"
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature

        max_retries = 3
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
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
                        if resp.status_code == 429 or resp.status_code >= 500:
                            if attempt < max_retries - 1:
                                wait = 2 ** attempt
                                last_error = RuntimeError(
                                    f"HTTP {resp.status_code} (retry {attempt+1}/{max_retries} in {wait}s): {error_body[:200]}"
                                )
                                await asyncio.sleep(wait)
                                continue
                            raise
                        raise RuntimeError(
                            f"HTTP {resp.status_code}: {error_body[:2000]}"
                        ) from e
                    return resp.json()
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    last_error = RuntimeError(
                        f"Connection error (retry {attempt+1}/{max_retries} in {wait}s): {e}"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        raise last_error or RuntimeError("API request failed after all retries")

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        model_mode: str = "flash",
        max_tokens: int | None = None,
        temperature: float | None = None,
        tool_choice: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
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
            "stream": True,
        }
        if tools:
            body["tools"] = [t.model_dump(exclude_none=True) for t in tools]
            body["tool_choice"] = tool_choice or "auto"
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature

        max_retries = 3
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    ) as resp:
                        if resp.status_code == 401:
                            raise PermissionError("Authentication failed — check your API key")
                        if resp.status_code != 200:
                            error_body = await resp.aread()
                            error_text = error_body.decode("utf-8", errors="replace")
                            if resp.status_code == 429 or resp.status_code >= 500:
                                if attempt < max_retries - 1:
                                    wait = 2 ** attempt
                                    last_error = RuntimeError(
                                        f"HTTP {resp.status_code} (retry {attempt+1}/{max_retries} in {wait}s): {error_text[:200]}"
                                    )
                                    await asyncio.sleep(wait)
                                    continue
                                raise RuntimeError(f"HTTP {resp.status_code}: {error_text[:2000]}")
                            raise RuntimeError(f"HTTP {resp.status_code}: {error_text[:2000]}")

                        tool_calls_buffer: dict[int, dict] = {}
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            choices = data.get("choices", [])
                            if not choices:
                                usage = data.get("usage")
                                if usage:
                                    yield StreamChunk(usage=usage)
                                continue

                            choice = choices[0]
                            delta = choice.get("delta", {})
                            finish_reason = choice.get("finish_reason")

                            delta_content = delta.get("content")
                            delta_reasoning = delta.get("reasoning_content")
                            delta_tool_calls_raw = delta.get("tool_calls")

                            if delta_tool_calls_raw:
                                for tc in delta_tool_calls_raw:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_calls_buffer:
                                        tool_calls_buffer[idx] = {
                                            "id": tc.get("id", ""),
                                            "type": tc.get("type", "function"),
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    buf = tool_calls_buffer[idx]
                                    if tc.get("id"):
                                        buf["id"] = tc["id"]
                                    func = tc.get("function", {})
                                    if func.get("name"):
                                        buf["function"]["name"] += func["name"]
                                    if func.get("arguments"):
                                        buf["function"]["arguments"] += func["arguments"]

                            yield StreamChunk(
                                delta_content=delta_content,
                                delta_reasoning=delta_reasoning,
                                finish_reason=finish_reason if finish_reason else None,
                            )

                        if tool_calls_buffer:
                            assembled = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())]
                            yield StreamChunk(delta_tool_calls=assembled)

                        return
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    last_error = RuntimeError(
                        f"Connection error (retry {attempt+1}/{max_retries} in {wait}s): {e}"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        raise last_error or RuntimeError("API request failed after all retries")

    async def query_balance(self) -> dict | None:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{domain}/user/balance",
                    headers=headers,
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None


