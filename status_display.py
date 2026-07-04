import asyncio
import time

from rich.console import Console
from rich.live import Live
from rich.text import Text


class StatusDisplay:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._label = ""
        self._start = 0.0
        self._console = Console()
        self._live: Live | None = None

    def _make_renderable(self, frozen: bool = False) -> Text:
        elapsed = time.time() - self._start
        if frozen:
            spinner = "▸"
        else:
            chars = "▸▹►"
            idx = int(elapsed * 5) % len(chars)
            spinner = chars[idx]
        text = Text()
        text.append("  ", style="")
        text.append(spinner, style="bold cyan")
        text.append(" ")
        text.append(self._label, style="bold")
        text.append("  ", style="")
        text.append(f"({elapsed:.1f}s)", style="dim")
        return text

    async def _ticker(self) -> None:
        self._start = time.time()
        self._live = Live(
            self._make_renderable(),
            console=self._console,
            refresh_per_second=10,
            transient=False,
        )
        self._live.start()
        try:
            while True:
                self._live.update(self._make_renderable())
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            self._live.update(self._make_renderable(frozen=True))
            self._live.refresh()
        finally:
            self._live.stop()

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
            self._live = None
