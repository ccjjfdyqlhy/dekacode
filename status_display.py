import asyncio
import time

from rich.console import Console


class StatusDisplay:
    """状态显示：已提交行无进度条（显示 description），仅活跃行有进度条。"""

    def __init__(self):
        self._ticker_task: asyncio.Task | None = None
        self._label = ""
        self._detail = ""
        self._description = ""
        self._token_str = ""
        self._turn_start = 0.0
        self._turn_estimated = 0.0
        self._console = Console()

    @staticmethod
    def _progress_bar(elapsed: float, estimated: float) -> str:
        if estimated <= 0:
            return ""
        pct = min(elapsed / estimated * 100, 100)
        if pct >= 99.9:
            return f"[green]━" * 20 + "[/] [bold]100%[/]"
        filled = int(pct / 5)
        bar = "━" * filled + ("╸" + "━" * (19 - filled) if filled < 20 else "━" * 20)
        return f"[green]{bar}[/] [bold]{pct:.0f}%[/]"

    _PAST_TENSE = {
        "Thinking": "Thought",
        "Bashing": "Bashed",
        "Reading": "Read",
        "Writing": "Wrote",
        "Globbing": "Globbed",
        "Grepping": "Grepped",
        "Fetching": "Fetched",
        "Searching": "Searched",
        "Tracing": "Traced",
        "Checking": "Checked",
        "Batching": "Batched",
        "Listing": "Listed",
        "Diffing": "Diffed",
        "Analyzing": "Analyzed",
        "Resolving": "Resolved",
        "Prefetching": "Prefetched",
        "Streaming": "Streamed",
        "GitHubbing": "GitHub done",
        "Executing gather batch": "Gather batch done",
        "Gathering info (phase 1/2)": "Info gathered",
        "Planning execution (phase 2/2)": "Execution planned",
        "Gathering info": "Info gathered",
        "Planning execution": "Execution planned",
    }

    def _past_label(self) -> str:
        return self._PAST_TENSE.get(self._label, self._label)

    def _commit_line(self, finished: bool = False) -> str:
        """已提交的历史行：无进度条，有 description 则显示描述。"""
        elapsed = time.time() - self._turn_start
        parts = ["  "]
        if not finished:
            chars = "▸▹►"
            idx = int(elapsed * 5) % 3
            parts.append(f"[bold cyan]{chars[idx]}[/] ")
        else:
            parts.append("[bold green]✓[/] ")
        label = self._past_label() if finished else self._label
        parts.append(f"[bold]{label}[/]")
        if self._description:
            parts.append(f"  [dim]{self._description}[/]")
        elif self._detail:
            parts.append(f"  [dim]{self._detail}[/]")
        parts.append(f"  [dim]{elapsed:.1f}s[/]")
        if self._token_str:
            parts.append("  [dim]│[/]  ")
            parts.append(self._token_str)
        return "".join(parts)

    def _live_str(self) -> str:
        """活跃行：有进度条和剩余时间，无 description。"""
        elapsed = time.time() - self._turn_start
        parts = ["  "]

        chars = "▸▹►"
        idx = int(elapsed * 5) % 3
        parts.append(f"[bold cyan]{chars[idx]}[/] ")

        parts.append(f"[bold]{self._label}[/]")
        if self._description:
            parts.append(f"  [dim]{self._description}[/]")
        elif self._detail:
            parts.append(f"  [dim]{self._detail}[/]")

        bar = self._progress_bar(elapsed, self._turn_estimated) if self._turn_estimated > 0 else ""
        if bar:
            parts.append(f"  {bar}")

        parts.append(f"  [dim]{elapsed:.1f}s[/]")

        if self._turn_estimated > elapsed:
            remaining = self._turn_estimated - elapsed
            parts.append(f"[dim]/ {remaining:.0f}s[/]")

        if self._token_str:
            parts.append("  [dim]│[/]  ")
            parts.append(self._token_str)

        return "".join(parts)

    def _draw(self) -> None:
        self._console.print(self._live_str(), end="\r\033[K")

    def token(self, text: str) -> None:
        self._token_str = text
        self._draw()

    async def begin(self) -> None:
        await self._stop_ticker()
        self._label = ""
        self._detail = ""
        self._description = ""
        self._token_str = ""
        self._turn_estimated = 0.0
        self._turn_start = 0.0

    async def status(self, label: str, detail: str = "",
                     description: str = "",
                     turn_estimated: float | None = None) -> None:
        await self._stop_ticker()
        self._label = label
        self._detail = detail
        self._description = description
        if turn_estimated is not None:
            self._turn_estimated = turn_estimated
        if self._turn_start == 0:
            self._turn_start = time.time()
        self._draw()
        self._ticker_task = asyncio.create_task(self._ticker())

    async def end(self) -> None:
        await self._stop_ticker()
        if self._label:
            self._console.print(self._commit_line(finished=True))
        self._label = ""
        self._detail = ""
        self._description = ""
        self._token_str = ""
        self._turn_estimated = 0.0
        self._turn_start = 0.0

    async def _stop_ticker(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except asyncio.CancelledError:
                pass
            self._ticker_task = None
            if self._label:
                self._console.print(self._commit_line(finished=False) + "\033[K")

    async def _ticker(self) -> None:
        try:
            while True:
                self._draw()
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
