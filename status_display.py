import asyncio
import time


class StatusDisplay:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._label = ""
        self._start = 0.0

    async def _ticker(self) -> None:
        self._start = time.time()
        try:
            while True:
                elapsed = time.time() - self._start
                self._draw(self._label, elapsed)
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            self._freeze()

    def _draw(self, label: str, elapsed: float) -> None:
        chars = "▸▹►"
        idx = int(elapsed * 5) % len(chars)
        spinner = chars[idx]
        print(f"\r  {spinner} {label}  ({elapsed:.1f}s)  \033[K", end="", flush=True)

    def _freeze(self) -> None:
        elapsed = time.time() - self._start
        print(f"\r  ▸ {self._label}  ({elapsed:.1f}s)  \033[K")

    async def status(self, label: str) -> None:
        await self.done()
        self._label = label
        self._task = asyncio.create_task(self._ticker())

    async def done(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
