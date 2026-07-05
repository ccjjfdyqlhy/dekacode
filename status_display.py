import asyncio
import time

from rich.console import Console


class StatusDisplay:
    """状态显示：切换时留痕（无进度条），活跃行实时更新（带进度条），结束打印 100%。"""

    def __init__(self):
        self._ticker_task: asyncio.Task | None = None
        self._label = ""
        self._detail = ""
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

    def _status_line(self, finished: bool = False) -> str:
        """状态标签行：▸ Label  detail  elapsed（无进度条）"""
        elapsed = time.time() - self._turn_start
        parts = ["  "]
        if not finished:
            chars = "▸▹►"
            idx = int(elapsed * 5) % 3
            parts.append(f"[bold cyan]{chars[idx]}[/] ")
        else:
            parts.append("[bold green]✓[/] ")
        parts.append(f"[bold]{self._label}[/]")
        if self._detail:
            parts.append(f"  [dim]{self._detail}[/]")
        parts.append(f"  [dim]{elapsed:.1f}s[/]")
        return "".join(parts)

    def _live_str(self) -> str:
        """活跃行：▸ Label  detail  ━━━45%  elapsed/rem  │ tokens"""
        elapsed = time.time() - self._turn_start
        parts = ["  "]

        # 统一使用 ▸▹► 动画
        chars = "▸▹►"
        idx = int(elapsed * 5) % 3
        parts.append(f"[bold cyan]{chars[idx]}[/] ")

        parts.append(f"[bold]{self._label}[/]")
        if self._detail:
            parts.append(f"  [dim]{self._detail}[/]")

        # 进度条
        bar = self._progress_bar(elapsed, self._turn_estimated) if self._turn_estimated > 0 else ""
        if bar:
            parts.append(f"  {bar}")

        parts.append(f"  [dim]{elapsed:.1f}s[/]")

        # 剩余时间
        if self._turn_estimated > elapsed:
            remaining = self._turn_estimated - elapsed
            parts.append(f"[dim]/ {remaining:.0f}s[/]")

        if self._token_str:
            parts.append("  [dim]│[/]  ")
            parts.append(self._token_str)

        return "".join(parts)

    def _draw(self) -> None:
        self._console.print(self._live_str(), end="\r")

    def token(self, text: str) -> None:
        self._token_str = text
        self._draw()

    async def begin(self) -> None:
        await self._stop_ticker()
        self._label = ""
        self._detail = ""
        self._token_str = ""
        self._turn_estimated = 0.0
        self._turn_start = 0.0

    async def status(self, label: str, detail: str = "",
                     turn_estimated: float | None = None) -> None:
        """通用状态（包括 Thinking 和各种工具执行）"""
        await self._stop_ticker()
        self._label = label
        self._detail = detail
        if turn_estimated is not None:
            self._turn_estimated = turn_estimated
        if self._turn_start == 0:
            self._turn_start = time.time()
        self._draw()
        self._ticker_task = asyncio.create_task(self._ticker())

    async def end(self) -> None:
        """停止 ticker，打印最终 100% 行，清空状态。"""
        await self._stop_ticker()
        if self._label:
            elapsed = time.time() - self._turn_start
            bar = self._progress_bar(elapsed, self._turn_estimated)
            line = f"  [bold green]✓[/] [bold]{self._label}[/]"
            if self._detail:
                line += f"  [dim]{self._detail}[/]"
            if bar:
                line += f"  {bar}"
            line += f"  [dim]{elapsed:.1f}s[/]"
            if self._token_str:
                line += f"  [dim]│[/]  {self._token_str}"
            self._console.print(line)
        self._label = ""
        self._detail = ""
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
                self._console.print(self._status_line(finished=False))

    async def _ticker(self) -> None:
        try:
            while True:
                self._draw()
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
