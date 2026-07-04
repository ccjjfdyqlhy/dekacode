import asyncio

from context import ContextManager
from models import Message
from utils import LLMClient

KEEPALIVE_INTERVAL = 30
KEEPALIVE_MAX_TOKENS = 1
KEEPALIVE_TEMPERATURE = 0.0


class CacheWarmer:
    """在等待用户输入期间发送低开销 keepalive 请求，保持服务端 prefix cache 活跃。"""

    def __init__(self, client: LLMClient):
        self._client = client
        self._task: asyncio.Task | None = None
        self._ctx: ContextManager | None = None
        self._model_mode: str = "flash"
        self._interval: float = KEEPALIVE_INTERVAL

    def set_context(self, ctx: ContextManager, model_mode: str) -> None:
        self._ctx = ctx
        self._model_mode = model_mode

    def clear_context(self) -> None:
        self._ctx = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            if self._ctx is not None:
                try:
                    msgs = self._ctx.build_request()
                    msgs.append(Message(role="user", content="."))
                    await self._client.chat(
                        messages=msgs,
                        tools=None,
                        model_mode=self._model_mode,
                        max_tokens=KEEPALIVE_MAX_TOKENS,
                        temperature=KEEPALIVE_TEMPERATURE,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            await asyncio.sleep(self._interval)
