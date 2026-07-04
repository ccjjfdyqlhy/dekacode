import asyncio
import time

from rich.console import Console


class StatusDisplay:
    def __init__(self):
        self._ticker_task: asyncio.Task | None = None
        self._label = ""
        self._detail = ""
        self._token_str = ""
        self._start = 0.0
        self._console = Console()

    def _render_str(self) -> str:
        parts = ["  "]
        if self._label:
            chars = "▸▹►"
            idx = int((time.time() - self._start) * 5) % 3
            parts.append(f"[bold cyan]{chars[idx]}[/] ")
            parts.append(f"[bold]{self._label}[/]")
            if self._detail:
                parts.append(f"  [dim]{self._detail}[/]")
            parts.append(f"  [dim]({time.time()-self._start:.1f}s)[/]")
        if self._token_str:
            if self._label:
                parts.append("  [dim]│[/]  ")
            parts.append(self._token_str)
        return "".join(parts)

    def _freeze_str(self) -> str:
        elapsed = time.time() - self._start
        parts = ["  "]
        if self._label:
            parts.append("[bold cyan]▸[/] ")
            parts.append(f"[bold]{self._label}[/]")
            if self._detail:
                parts.append(f"  [dim]{self._detail}[/]")
            parts.append(f"  [dim]({elapsed:.1f}s)[/]")
        if self._token_str:
            if self._label:
                parts.append("  [dim]│[/]  ")
            parts.append(self._token_str)
        return "".join(parts)

    def _draw(self) -> None:
        self._console.print(self._render_str(), end="\r")

    def _freeze_and_newline(self) -> None:
        self._console.print(self._freeze_str())

    async def begin(self) -> None:
        await self.end()

    async def end(self) -> None:
        await self._stop_ticker()
        self._label = ""
        self._detail = ""
        self._token_str = ""

    async def status(self, label: str, detail: str = "") -> None:
        await self._stop_ticker()
        self._label = label
        self._detail = detail
        self._start = time.time()
        self._draw()
        self._ticker_task = asyncio.create_task(self._ticker())

    def token(self, text: str) -> None:
        self._token_str = text
        self._draw()

    async def _stop_ticker(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except asyncio.CancelledError:
                pass
            self._ticker_task = None

    async def _ticker(self) -> None:
        try:
            while True:
                self._draw()
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            self._freeze_and_newline()
