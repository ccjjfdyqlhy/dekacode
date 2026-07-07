import asyncio
import json
import os
import re
import sys
import time

VERSION = "V0.2.4"

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings

from chat_store import ChatStore
from config import Settings
from context import ContextManager, SpeculativePrefetcher
from models import Function, Message, ToolCall
from prompt_engine import PromptEngine
from router import ModelRouter, in_peak_hours
from session_logger import SessionLogger
from skill import SkillRegistry
from skills.filters import OutputFilter
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from code_graph.placeholders import PlaceholderResolver
from status_display import StatusDisplay
from token_counter import TokenCounter, fmt_tokens
from utils import LLMClient
from cache_warmer import CacheWarmer
from predictor import DurationPredictor

_FILE_REF_RE = re.compile(r"([\w./\\-]+\.py)")

MAX_CONVERSATION_HISTORY = 1000


def _get_tool_detail(name: str, args: dict) -> str:
    if name == "read_file":
        path = args.get("filePath", "")
        offset = args.get("offset")
        limit = args.get("limit")
        if offset and limit:
            return f"{path}:{offset}-{limit}"
        return path or "?"
    elif name == "write_file":
        path = args.get("filePath", "")
        content = args.get("content", "")
        lines = content.count("\n")
        return f"{path}  +{lines} lines"
    elif name == "glob":
        return args.get("pattern", "?")
    elif name == "grep":
        return f"/{args.get('pattern', '?')}/"
    elif name == "bash":
        return ""
    elif name == "web_fetch":
        return args.get("url", "?")
    elif name == "symbol_search":
        return args.get("query", "?")
    elif name == "callers":
        return args.get("symbol", "?")
    elif name == "read_symbol":
        return args.get("symbol", "?")
    elif name == "py_check":
        return args.get("file_path", "?")
    elif name == "edit_file":
        return args.get("filePath", "?")
    elif name == "read_files":
        paths = args.get("paths", [])
        return f"{len(paths)} files" if paths else ""
    elif name == "grep_context":
        return f"/{args.get('pattern', '?')}/"
    elif name == "list_dir":
        return args.get("path", ".")
    elif name == "diff_file":
        return args.get("filePath", "(full)")
    elif name == "ast_summary":
        return args.get("file_path", "?")
    return ""


def _compact_history(ctx: ContextManager, loaded_len: int = 0, chat_store=None) -> int:
    if chat_store and chat_store.get_no_compress():
        return loaded_len
    total = len(ctx.history)
    if total <= MAX_CONVERSATION_HISTORY:
        return loaded_len
    if loaded_len > 0 and total <= loaded_len + 20:
        return loaded_len
    keep_first = 10
    keep_last = min(200, MAX_CONVERSATION_HISTORY - keep_first - 1)
    if keep_last < 1:
        ctx.history = ctx.history[-MAX_CONVERSATION_HISTORY:]
        return 0
    removed = ctx.history[keep_first:-keep_last]
    if chat_store and chat_store.session_id and removed:
        chat_store.save_compressed_chunk(removed)
    compressed = Message(role="system", content="[Earlier history compressed — scrollback preserved above]")
    ctx.history = ctx.history[:keep_first] + [compressed] + ctx.history[-(keep_last):]
    return 0


_ESSENTIAL_TOOLS = {"read_file", "write_file", "edit_file", "read_files", "bash", "glob", "grep", "grep_context", "list_dir", "dekacode"}
_SYMBOL_TOOLS = {"symbol_search", "callers", "read_symbol"}
_CHECK_TOOLS = {"py_check", "ast_summary"}
_GIT_TOOLS = {"diff_file"}
_WEB_TOOLS = {"web_fetch"}
_GITHUB_TOOLS = {"github"}

_TOOL_KEYWORDS: list[tuple[set[str], set[str]]] = [
    (_SYMBOL_TOOLS, {"symbol", "function", "class", "caller", "callee", "define", "refer"}),
    (_CHECK_TOOLS, {"syntax", "check", "parse", "ast", "compile"}),
    (_GIT_TOOLS, {"git", "diff", "commit", "staged", "unstaged"}),
    (_WEB_TOOLS, {"url", "http", "fetch", "web", "api"}),
    (_GITHUB_TOOLS, {"github", "issue", "pull", "pr", "workflow"}),
]

def _filter_tool_defs(registry: SkillRegistry, user_input: str) -> list:
    active: set[str] = set(_ESSENTIAL_TOOLS)
    user_lower = user_input.lower()
    for tools, keywords in _TOOL_KEYWORDS:
        if any(kw in user_lower for kw in keywords):
            active.update(tools)
    return [td for td in registry.get_tool_definitions() if td.function["name"] in active]

def _setup_registry(graph=None, settings=None) -> SkillRegistry:
    from skills.web_fetch import WebFetchSkill
    from skills.bash import BashSkill
    from skills.file_ops import (
        ReadFileSkill,
        WriteFileSkill,
        GlobSkill,
        GrepSkill,
        EditFileSkill,
        ReadFilesSkill,
        GrepContextSkill,
        ListDirSkill,
    )
    from skills.git_ops import DiffFileSkill
    from skills.py_check import PyCheckSkill, AstSummarySkill
    from skills.dekacode import DekaCodeSkill
    from skills.github_ops import GitHubSkill

    registry = SkillRegistry()
    registry.register(WebFetchSkill())
    registry.register(BashSkill())
    registry.register(ReadFileSkill())
    registry.register(WriteFileSkill())
    registry.register(GlobSkill())
    registry.register(GrepSkill())
    registry.register(EditFileSkill())
    registry.register(ReadFilesSkill())
    registry.register(GrepContextSkill())
    registry.register(ListDirSkill())
    registry.register(DiffFileSkill())

    if graph:
        from skills.symbol_search import SymbolSearchSkill, CallersSkill, ReadSymbolSkill
        registry.register(SymbolSearchSkill(graph))
        registry.register(CallersSkill(graph))
        registry.register(ReadSymbolSkill(graph))

    registry.register(PyCheckSkill())
    registry.register(AstSummarySkill())

    # DekaCode工具集线器: 整合core/project模块的全部代码分析能力
    # (batch_bash, symbol_search, find_def, find_ref, diagnose, fix_imports,
    #  diff_lines, summarize, key_files, module_map, snapshot 等)
    registry.register(DekaCodeSkill())

    token = settings.github_token if settings else ""
    base_url = settings.github_base_url if settings else "https://api.github.com"
    registry.register(GitHubSkill(token=token, base_url=base_url))

    return registry


_IMPORTED_FILES: set[str] = set()

def _attach_imports(ctx: ContextManager, user_input: str) -> None:
    from code_graph.imports import ImportResolver
    from models import Message
    matches = _FILE_REF_RE.findall(user_input)
    if not matches:
        return
    resolver = ImportResolver(".")
    blocks: list[str] = []
    for fpath in set(matches):
        if fpath in _IMPORTED_FILES:
            continue
        _IMPORTED_FILES.add(fpath)
        sigs = resolver.resolve(fpath)
        if sigs:
            lines = "\n".join(s.to_prompt_block() for s in sigs)
            blocks.append(f"# imports from {fpath}\n{lines}")
    if blocks:
        attachment = "\n\n".join(blocks)
        ctx.history.append(Message(role="system", content=f"# Resolved imports\n{attachment}"))


def _build_graph(project_root: str):
    from code_graph.builder import GraphBuilder
    from code_graph.cache import GraphCache
    cache = GraphCache(project_root)
    from rich.console import Console as _RC
    _rc = _RC()
    if cache.is_fresh():
        graph = cache.load()
        if graph:
            _rc.print(Text.assemble(
                ("  Call graph:", "dim"),
                (f" {graph.total_symbols()} symbols, ", "green"),
                (f"{len(graph.files)} files", "green"),
                (" (cached)", "dim"),
            ))
            return graph
    _rc.print("  [yellow]⟳[/] Building call graph (full scan)...")
    t0 = time.time()
    builder = GraphBuilder(project_root)
    graph = builder.build()
    cache.save(graph)
    _rc.print(Text.assemble(
        ("  ✓ ", "green"),
        (f"{graph.total_symbols()} symbols, {len(graph.files)} files", "green"),
        (f" in {time.time()-t0:.1f}s", "dim"),
    ))
    return graph


async def run_agent_loop(settings: Settings) -> None:
    client = LLMClient(settings)
    warmer = CacheWarmer(client)
    project_root = os.getcwd()

    from rich.console import Console as _RichConsole
    _console = _RichConsole()
    _console.clear()
    _console.print(Text.assemble(
        ("\n  ━ Dekacode ", "bold cyan"),
        (VERSION, "yellow"),
        (" @ ", "dim"),
        (project_root, "green"),
        (" activated", "bold cyan"),
    ))

    graph = _build_graph(project_root)
    registry = _setup_registry(graph, settings)

    prompt_engine = PromptEngine()
    prompt_engine.load_all()
    tool_lines = prompt_engine.build_tool_descriptions(registry)
    system_prompt = prompt_engine.build_system_prompt(tool_lines)
    ctx = ContextManager(system_prompt)
    token_counter = TokenCounter()
    prefetcher = SpeculativePrefetcher(graph)
    logger = SessionLogger(log_dir=settings.log_dir)
    chat_store = ChatStore(project_root)

    predictor = DurationPredictor.load()

    compact_map = graph.to_compact_map()
    ctx.set_prefix_attachment(f"# Project structure\n{compact_map[:800]}")
    _prefix_stable_len = 1 + len(ctx.prefix)  # system + prefix（不包含 history/draft）
    _prefix_hash = hash(str(ctx.build_request()[:_prefix_stable_len]))
    _console.print(f"  [dim]prefix hash: {_prefix_hash}[/]")

    from router import ModelConfig
    router_config = ModelConfig(
        auto_downgrade_on_peak=settings.auto_downgrade_on_peak,
        flash_model=settings.flash_model or settings.openai_model,
        pro_model=settings.pro_model or settings.openai_model,
        flash_api_key=settings.flash_api_key or settings.openai_api_key,
        pro_api_key=settings.pro_api_key or settings.openai_api_key,
        flash_base_url=settings.flash_base_url or settings.openai_base_url,
        pro_base_url=settings.pro_base_url or settings.openai_base_url,
    )
    router = ModelRouter(config=router_config)

    model_mode = router.select()
    client.switch_model(model_mode)
    current_model_name = client.model

    turn_start_idx = 0

    _console.print(Text.assemble(
        ("  Code Agent ready", "bold green"),
        ("  provider=", "dim"), (settings.provider, "yellow"),
        ("  model=", "dim"), (current_model_name, "cyan"),
        ("  mode=", "dim"), (model_mode, "magenta"),
        ("  peak=", "dim"), ("⚠", "red") if in_peak_hours() else ("✓", "green"),
    ))
    _console.print(Text.assemble(
        ("  Commands: ", "dim"),
        *[pair for cmd in ["cost", "report", "stats", "prompts", "graph", "sessions", "resume", "save", "load", "flash", "pro", "mode", "nocompress", "help"]
        for pair in [(f"/{cmd}", "cyan"), (" ", "dim")]],
    ))
    _console.print("  [dim]Type /resume to continue last session, or just type a message to start fresh.[/]")
    _console.print("  [dim]Type your message and start building now.\n  '/exit' or  ^C to quit.[/]\n")

    from code_graph.watcher import FileWatcher
    file_watcher = FileWatcher(project_root)

    from code_graph.cache import GraphCache
    graph_cache = GraphCache(project_root)

    from code_graph.builder import GraphBuilder

    def _rebuild_graph_if_dirty() -> None:
        nonlocal graph
        changed = file_watcher.get_changed_files()
        if not changed:
            return
        for fpath in changed:
            graph_cache.mark_dirty(fpath)
        if changed:
            _console.print(f"  [yellow]⟳[/] {len(changed)} file(s) modified, rebuilding call graph...")
            t0 = time.time()
            builder = GraphBuilder(project_root)
            graph = builder.build()
            graph_cache.save(graph)
            _console.print(Text.assemble(
                ("  ✓ Rebuilt in ", "green"),
                (f"{time.time()-t0:.1f}s", "dim"),
                (f"  ({graph.total_symbols()} symbols)", "green"),
            ))

    _clean_exit = False
    _turn_number = 0
    _loaded_history_len = 0
    _last_saved_len = 0
    _last_user_input = ""
    _history_snapshots: list[int] = []
    _last_turn_elapsed = 0.0
    _kb = KeyBindings()

    @_kb.add('escape', 'enter')
    def _insert_newline(event):
        event.current_buffer.insert_text('\n')

    @_kb.add('enter')
    def _submit(event):
        event.current_buffer.validate_and_handle()

    @_kb.add('up')
    def _move_up(event):
        buf = event.current_buffer
        if buf.document.cursor_position_row > 0:
            buf.cursor_up(1)

    @_kb.add('down')
    def _move_down(event):
        buf = event.current_buffer
        if buf.document.cursor_position_row < buf.document.line_count - 1:
            buf.cursor_down(1)

    @_kb.add('home')
    def _scroll_bottom(event):
        pass

    _prompt_session = PromptSession(multiline=True, key_bindings=_kb, mouse_support=False)
    display = StatusDisplay()

    def _save_all(final: bool = False) -> None:
        nonlocal _last_saved_len, _turn_number
        unsaved = ctx.history[_last_saved_len:]
        if unsaved and (final or not _clean_exit):
            chat_store.save_messages(unsaved)
            _last_saved_len = len(ctx.history)
        if token_counter.records and (final or not _clean_exit):
            pending = token_counter.records[turn_start_idx:]
            if pending:
                chat_store.save_usage(
                    turn=_turn_number, model=model_mode,
                    input_tokens=sum(r.input_tokens for r in pending),
                    output_tokens=sum(r.output_tokens for r in pending),
                    cache_hit_input=sum(r.cache_hit_input for r in pending),
                    cost=sum(r.cost for r in pending),
                )
        if token_counter.records:
            _console.print(token_counter.session_summary())
        predictor.save()
        logger.close()
        _console.print(f"  [dim]log: {logger.path}[/]")

    _tool_status_map = {
        "bash": "Bashing", "read_file": "Reading", "write_file": "Writing",
        "edit_file": "Editing", "read_files": "Reading", "grep_context": "Grepping",
        "list_dir": "Listing", "glob": "Globbing", "grep": "Grepping",
        "diff_file": "Diffing", "ast_summary": "Analyzing",
        "web_fetch": "Fetching", "symbol_search": "Searching", "callers": "Tracing",
        "read_symbol": "Reading", "py_check": "Checking",
        "github": "GitHubbing",
        "_prefetch": "Prefetching", "_placeholder": "Resolving",
    }

    def _render_hist(hist: list) -> None:
        for m in hist:
            if m.role == "user" and m.content:
                _console.print(f"\n  > {m.content}")
            elif m.role == "assistant" and m.content:
                _console.print(Markdown(m.content))
            elif m.role == "tool":
                label = _tool_status_map.get(m.name or "", "Working")
                _console.print(f"  [dim]▸ {label}[/]")

    def _load_session(sid: str) -> bool:
        nonlocal _last_saved_len, _loaded_history_len
        hist = chat_store.load_messages(sid)
        if not hist:
            return False
        chat_store.set_session(sid)
        ctx.history = hist
        _loaded_history_len = len(hist)
        _last_saved_len = len(hist)
        usage = chat_store.load_usage(sid)
        total_cost = sum(u["cost"] for u in usage)
        total_in = sum(u["input_tokens"] for u in usage)
        no_compress_flag = " NOCOMPRESS" if chat_store.get_no_compress(sid) else ""
        _console.print(Text.assemble(
            ("  Loaded ", "green"),
            (sid, "cyan"),
            (f"  {len(hist)} msgs", "yellow"),
            (f"  ¥{total_cost:.4f}", "bold yellow"),
            (f"  {int(total_in/1000)}K in", "cyan"),
            (no_compress_flag, "bold green") if no_compress_flag else ("", ""),
        ))
        _render_hist(hist)
        return True

    warmer.set_context(ctx, model_mode)

    try:
        while True:
            warmer.start()
            try:
                user_input = (await _prompt_session.prompt_async("\n > ")).strip()
            except (EOFError, KeyboardInterrupt):
                await warmer.stop()
                print()
                _clean_exit = True
                break
            await warmer.stop()

            if user_input.lower() in ("exit", "quit", "/exit"):
                _clean_exit = True
                break

            if not user_input:
                continue

            if user_input == "/retry":
                if not _last_user_input:
                    _console.print("  [dim]No previous input to retry.[/]")
                    continue
                user_input = _last_user_input
                _console.print("  [yellow]↻ Retrying last input[/]")

            if user_input == "/undo":
                if _history_snapshots:
                    prev_len = _history_snapshots.pop()
                    ctx.history = ctx.history[:prev_len]
                    _last_saved_len = min(_last_saved_len, prev_len)
                    _console.print("  [green]✓ Undone last turn[/]")
                else:
                    _console.print("  [dim]Nothing to undo.[/]")
                continue

            is_cmd = user_input.startswith("/")
            if is_cmd:
                if user_input == "/cost":
                    if token_counter.records:
                        _console.print(token_counter.session_summary())
                    else:
                        _console.print("  [dim]No API calls yet.[/]")

                elif user_input == "/stats":
                    total = ctx.total_messages()
                    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                    table.add_column("Key", style="bold", no_wrap=True)
                    table.add_column("Value")
                    table.add_row("Context", f"[cyan]system=1[/] [cyan]prefix={len(ctx.prefix)}[/] [cyan]history={len(ctx.history)}[/] [cyan]draft={len(ctx.draft)}[/] [dim]total={total}[/]")
                    table.add_row("API calls", f"[yellow]{len(token_counter.records)}[/]")
                    table.add_row("Graph", f"[green]{graph.total_symbols()}[/] [dim]symbols,[/] [green]{len(graph.files)}[/] [dim]files[/]")
                    table.add_row("Model", f"[magenta]{model_mode}[/] [dim]({current_model_name})[/]")
                    _console.print(table)

                elif user_input == "/report":
                    from token_counter import FLASH_INPUT_CACHE_MISS, FLASH_OUTPUT, PRO_INPUT_CACHE_MISS, PRO_OUTPUT
                    rows = chat_store.load_all_usage()
                    if not rows:
                        _console.print("  [dim]No historical data yet.[/]")
                    else:
                        total_in = sum(r["input_tokens"] for r in rows)
                        total_out = sum(r["output_tokens"] for r in rows)
                        total_cache = sum(r["cache_hit_input"] for r in rows)
                        total_cost = sum(r["cost"] for r in rows)
                        total_tok = total_in + total_out

                        eff_price = (total_cost / total_tok * 1_000_000) if total_tok else 0
                        flash_ref = (total_in * FLASH_INPUT_CACHE_MISS + total_out * FLASH_OUTPUT) / 1_000_000
                        pro_ref = (total_in * PRO_INPUT_CACHE_MISS + total_out * PRO_OUTPUT) / 1_000_000
                        flash_save = flash_ref - total_cost
                        pro_save = pro_ref - total_cost
                        flash_pct = (flash_save / flash_ref * 100) if flash_ref else 0
                        pro_pct = (pro_save / pro_ref * 100) if pro_ref else 0

                        table = Table(box=box.SIMPLE, header_style="bold cyan")
                        table.add_column("Metric", style="bold")
                        table.add_column("Value", justify="right")
                        table.add_row("Sessions", str(len(set(r["session_id"] for r in rows))))
                        table.add_row("API calls", str(len(rows)))
                        table.add_row("Total tokens", fmt_tokens(total_tok))
                        table.add_row("  input", f"{fmt_tokens(total_in)}  (cache hit {fmt_tokens(total_cache)} / {total_cache/total_in*100:.0f}%)")
                        table.add_row("  output", fmt_tokens(total_out))
                        table.add_row("Total cost", f"¥{total_cost:.4f}")
                        table.add_row("", "")
                        table.add_row("Effective ¥/1M tok", f"[bold yellow]¥{eff_price:.4f}[/]")
                        table.add_row("", "")
                        table.add_row("Flash reference", f"¥{flash_ref:.4f}  (would cost at ¥{FLASH_INPUT_CACHE_MISS:.1f}/M in + ¥{FLASH_OUTPUT:.1f}/M out)")
                        table.add_row("  vs Flash saved", f"[green]¥{flash_save:.4f}  ({flash_pct:.0f}% cheaper)[/]")
                        table.add_row("", "")
                        table.add_row("Pro reference", f"¥{pro_ref:.4f}  (would cost at ¥{PRO_INPUT_CACHE_MISS:.1f}/M in + ¥{PRO_OUTPUT:.1f}/M out)")
                        table.add_row("  vs Pro saved", f"[green]¥{pro_save:.4f}  ({pro_pct:.0f}% cheaper)[/]")
                        _console.print(table)

                elif user_input == "/graph":
                    _console.print(Syntax(graph.to_compact_map()[:3000], "python", word_wrap=True))

                elif user_input == "/sessions":
                    all_sessions = chat_store.list_sessions(limit=20)
                    if not all_sessions:
                        _console.print("  [dim]No saved sessions[/]")
                    else:
                        table = Table(box=box.SIMPLE, header_style="bold cyan")
                        table.add_column("", style="green")
                        table.add_column("ID", style="cyan", no_wrap=True)
                        table.add_column("Msgs", justify="right")
                        table.add_column("Cost", style="yellow")
                        table.add_column("Tokens", style="cyan")
                        table.add_column("Summary", style="dim")
                        for s in all_sessions:
                            cur = "←" if s["id"] == chat_store.session_id else ""
                            summary = s["summary"][:60] if s["summary"] else "(no summary)"
                            cost = f"¥{s['total_cost']:.4f}" if s['total_cost'] > 0 else ""
                            tokens = fmt_tokens(s['total_input']) if s['total_input'] > 0 else ""
                            table.add_row(cur, s["id"], str(s["message_count"]), cost, tokens, summary)
                        _console.print(table)

                elif user_input == "/resume":
                    recent = chat_store.list_sessions(limit=1)
                    if not recent:
                        _console.print("  [dim]No previous session[/]")
                    else:
                        _load_session(recent[0]["id"])

                elif user_input == "/save":
                    if not chat_store.session_id:
                        chat_store.create_session()
                    _save_all(final=True)
                    _console.print(Text.assemble(
                        ("  ✓ Saved  ", "green"),
                        (chat_store.session_id or "", "cyan"),
                    ))

                elif user_input.startswith("/load "):
                    sid = user_input[6:].strip()
                    if not _load_session(sid):
                        _console.print(f"  [red]Session '{sid}' not found or empty[/]")

                elif user_input == "/flash":
                    model_mode = router.switch("flash")
                    current_model_name = client.switch_model("flash")
                    _console.print(Text.assemble(
                        ("  Flash ", "cyan"), ("▸ ", "dim"), (current_model_name, "bold"),
                    ))

                elif user_input == "/pro":
                    model_mode = router.switch("pro")
                    current_model_name = client.switch_model("pro")
                    _console.print(Text.assemble(
                        ("  Pro ", "magenta"), ("▸ ", "dim"), (current_model_name, "bold"),
                    ))

                elif user_input == "/mode":
                    model_mode = router.switch("auto")
                    peak = in_peak_hours()
                    model_mode = "flash"
                    current_model_name = client.switch_model("flash")
                    _console.print(Text.assemble(
                        ("  Auto ", "green"),
                        ("▸ ", "dim"),
                        (current_model_name, "bold"),
                        ("  ", ""),
                        ("peak", "red") if peak else ("ok", "green"),
                    ))

                elif user_input == "/nocompress":
                    if chat_store.session_id:
                        current = chat_store.get_no_compress()
                        chat_store.set_no_compress(not current)
                        status = "ON" if not current else "OFF"
                        if current:  # was ON, turning OFF
                            pass
                        else:  # was OFF, turning ON — restore compressed chunks
                            chunks = chat_store.load_compressed_chunks()
                            if chunks:
                                new_hist = []
                                for m in ctx.history:
                                    if m.role == "system" and m.content == "[Earlier history compressed — scrollback preserved above]":
                                        for chunk in chunks:
                                            new_hist.extend(chunk)
                                    else:
                                        new_hist.append(m)
                                ctx.history = new_hist
                                _loaded_history_len = len(ctx.history)
                                chat_store.clear_compressed_chunks()
                                _console.print(f"  [dim]Restored {len(chunks)} compressed chunk(s) ({sum(len(c) for c in chunks)} msgs)[/]")
                        _console.print(Text.assemble(
                            ("  No-compress: ", "bold"),
                            (status, "green" if not current else "dim"),
                        ))
                    else:
                        _console.print("  [dim]No active session.[/]")

                elif user_input == "/prompts":
                    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                    table.add_column("", style="green")
                    table.add_column("Prompt", style="bold")
                    table.add_column("Order", style="dim")
                    table.add_column("Description", style="dim")
                    for line in prompt_engine.summary().split("\n"):
                        flag = "✓" if "✓" in line else "✗"
                        rest = line.replace("[✓]", "").replace("[✗]", "").strip()
                        parts = rest.split("(order=")
                        title = parts[0].strip()
                        order = parts[1].rstrip(")") if len(parts) > 1 else ""
                        desc = ""
                        for frag in prompt_engine.fragments:
                            if frag.title == title:
                                desc = frag.description
                                break
                        table.add_row(flag, title, order, desc)
                    _console.print(table)

                elif user_input == "/help":
                    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                    table.add_column("Command", style="cyan", no_wrap=True)
                    table.add_column("Description", style="dim")
                    table.add_row("/retry", "Retry last input")
                    table.add_row("/undo", "Undo last turn")
                    table.add_row("/cost", "Show session token cost")
                    table.add_row("/report", "Show all-session cost report vs official pricing")
                    table.add_row("/stats", "Show context stats")
                    table.add_row("/prompts", "List enabled/disabled prompt fragments")
                    table.add_row("/graph", "Show project symbol map")
                    table.add_row("/sessions", "List saved chat sessions")
                    table.add_row("/resume", "Load most recent session")
                    table.add_row("/save", "Save current session now")
                    table.add_row("/load id", "Load a past session by ID")
                    table.add_row("/flash", "Switch to flash model (cheap)")
                    table.add_row("/pro", "Switch to pro model (powerful)")
                    table.add_row("/mode", "Auto model selection")
                    table.add_row("/nocompress", "Toggle no-compress mode for this session")
                    table.add_row("/exit", "Exit")
                    _console.print(table)

                elif user_input.startswith("/"):
                    _console.print(f"  [yellow]Unknown command:[/] {user_input}")

                continue

            _balance_before = await client.query_balance()

            _history_snapshots.append(len(ctx.history))
            _last_user_input = user_input

            if not chat_store.session_id:
                chat_store.create_session()
            _loaded_history_len = _compact_history(ctx, _loaded_history_len, chat_store)
            _last_saved_len = min(_last_saved_len, len(ctx.history))
            _attach_imports(ctx, user_input)
            ctx.add_user_message(user_input)
            _turn_elapsed = 0.0
            _turn_estimated = _last_turn_elapsed or 60.0
            logger.log_turn_start(user_input, model_mode)

            _rebuild_graph_if_dirty()
            turn_start_idx = len(token_counter.records)
            turn = 0
            model_mode = router.select()
            current_model_name = client.switch_model(model_mode)

            await display.begin()
            while turn < settings.max_tool_iterations:
                _rebuild_graph_if_dirty()
                if turn == 0:
                    cur_hash = hash(str(ctx.build_request()[:_prefix_stable_len]))
                    if cur_hash != _prefix_hash:
                        _console.print(f"  [red]⚠ Prefix hash changed: {_prefix_hash} -> {cur_hash} (cache lost!)[/]")
                        _prefix_hash = cur_hash
                tools = _filter_tool_defs(registry, user_input) if turn == 0 else registry.get_tool_definitions()
                request = ctx.build_request()
                output_limit = 16384
                logger.log_request(request, tools, model_mode, output_limit)
                prev_rec = token_counter.records[-1] if token_counter.records else None
                est_cache = prev_rec.cache_hit_input if prev_rec else 0
                est_out = prev_rec.output_tokens if prev_rec else 1024
                req_size = sum(len(m.content or "") for m in request)
                est_dur = predictor.predict(req_size, est_cache, est_out)
                # 每次迭代都用当前上下文规模更新预估：
                # 工具调用 → 上下文增长 → c_k(total_input/1000) 增大 → est_dur 增大
                _turn_estimated = max(_turn_estimated, _turn_elapsed + est_dur * 2)
                if chat_store and chat_store.get_no_compress() and req_size > 150000:
                    _console.print("  [yellow]⚠ Large context (no-compress ON) — may exceed model limit. Type /nocompress to disable.[/]")
                try:
                    await display.status("Thinking", turn_estimated=_turn_estimated)
                    t0 = time.time()
                    response = await client.chat(request, tools, model_mode=model_mode, max_tokens=output_limit)
                    elapsed = time.time() - t0
                except KeyboardInterrupt:
                    await display.end()
                    ctx.rollback_draft()
                    _console.print("  [yellow]⏹ Interrupted[/]")
                    break
                except asyncio.CancelledError:
                    ctx.rollback_draft()
                    break
                except Exception as e:
                    error_text = str(e)
                    ctx.rollback_draft()
                    _is_too_long = any(kw in error_text.lower() for kw in ("prompt 超长", "context length", "too large", "maximum context", "token limit", "1261"))
                    if _is_too_long:
                        await display.end()
                        _console.print("  [red]✗ Context too long for model[/]")
                        if chat_store and chat_store.get_no_compress():
                            chat_store.set_no_compress(False)
                            _loaded_history_len = 0
                            _console.print("  [yellow]  Auto-disabled no-compress. Type /retry to continue with compressed context.[/]")
                        else:
                            _console.print("  [yellow]  Reduce context size or use a model with larger window.[/]")
                        break
                    if "tool" in error_text and "tool_calls" in error_text:
                        retries = 10
                        ok = False
                        interrupted_retry = False
                        for attempt in range(retries):
                            _console.print(f"  [yellow]⟳ Tool role mismatch, retry {attempt+1}/{retries}...[/]")
                            try:
                                await display.status("Thinking", turn_estimated=_turn_estimated)
                                t0 = time.time()
                                response = await client.chat(request, tools, model_mode=model_mode, max_tokens=output_limit)
                                elapsed = time.time() - t0
                                ok = True
                                break
                            except KeyboardInterrupt:
                                await display.end()
                                ctx.rollback_draft()
                                _console.print("  [yellow]⏹ Interrupted[/]")
                                interrupted_retry = True
                                break
                            except Exception as e2:
                                error_text = str(e2)
                                ctx.rollback_draft()
                        if not ok:
                            await display.end()
                            if interrupted_retry:
                                _console.print("  [yellow]⏹ Interrupted[/]")
                            else:
                                _console.print(f"  [red]✗ API Error (retry failed after {retries} attempts):[/] {error_text}")
                            break
                    else:
                        await display.end()
                        _console.print(f"  [red]✗ API Error:[/] {e}")
                        break

                choices = response.get("choices")
                if not choices:
                    await display.end()
                    _console.print("  [red]✗ API Error: empty response[/]")
                    ctx.rollback_draft()
                    break

                rec = token_counter.record(response, model=model_mode, elapsed=elapsed)
                _turn_elapsed += elapsed
                if _turn_elapsed > _turn_estimated * 0.85:
                    _turn_estimated = _turn_elapsed * 2
                usage_text = token_counter.display(rec)
                display.token(usage_text)
                logger.log_response(response, elapsed, usage_text)
                predictor.add(rec.input_tokens, rec.cache_hit_input, rec.output_tokens, elapsed)
                predictor.save()

                if settings.max_session_cost > 0 and token_counter.session_cost > settings.max_session_cost:
                    await display.end()
                    _console.print(f"  [red]Budget exceeded:[/] ¥{token_counter.session_cost:.4f} > ¥{settings.max_session_cost:.4f}")
                    logger.close()
                    _clean_exit = True
                    return

                msg = choices[0].get("message", {})
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls")
                finish_reason = choices[0].get("finish_reason", "stop")

                if finish_reason == "length":
                    partial = Message(role="assistant", content=content or None)
                    ctx.add_assistant_message(partial)
                    ctx.add_user_message("continue")
                    _console.print(f"  [yellow]⟳ Response truncated, continuing...[/]")
                    continue

                assistant = Message(role="assistant", content=content or None)

                if tool_calls:
                    parsed = []
                    for tc in tool_calls:
                        func = Function(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        )
                        parsed.append(
                            ToolCall(
                                id=tc["id"],
                                type=tc.get("type", "function"),
                                function=func,
                            )
                        )
                    assistant.tool_calls = parsed
                    ctx.draft.append(assistant)

                    async def _exec_one(tc):
                        try:
                            args = json.loads(tc.function.arguments)
                            result = await registry.execute(tc.function.name, args)
                            return (tc, result.output if result.success else f"[Error] {result.output}")
                        except json.JSONDecodeError as e:
                            return (tc, f"[Parse Error] Invalid JSON arguments: {e}")
                        except Exception as e:
                            return (tc, f"[Error] Tool crashed: {type(e).__name__}: {e}")

                    if len(parsed) > 1:
                        await display.status("Batching", f"{len(parsed)} tool calls", description=content)
                    else:
                        t = parsed[0]
                        try:
                            a = json.loads(t.function.arguments)
                            lbl = {
                                "bash": "Bashing", "read_file": "Reading",
                                "write_file": "Writing", "glob": "Globbing",
                                "grep": "Grepping", "web_fetch": "Fetching",
                                "symbol_search": "Searching", "callers": "Tracing",
                                "read_symbol": "Reading", "py_check": "Checking",
                            }.get(t.function.name, "Working")
                            det = _get_tool_detail(t.function.name, a)
                            if t.function.name == "bash":
                                cmd = a.get("command", "")
                                if cmd.lstrip().startswith("grep"):
                                    lbl = "Grepping"
                            elif t.function.name == "github":
                                action = a.get("action", "")
                                _github_labels = {
                                    "issue_list": "Listing Issues", "issue_get": "Getting Issue",
                                    "issue_create": "Creating Issue", "issue_update": "Updating Issue",
                                    "issue_close": "Closing Issue", "issue_comment": "Commenting Issue",
                                    "pr_list": "Listing PRs", "pr_get": "Getting PR",
                                    "pr_create": "Creating PR", "pr_merge": "Merging PR",
                                    "pr_review": "Reviewing PR", "pr_add_comment": "Commenting PR",
                                    "pr_list_files": "Listing PR Files", "pr_get_diff": "Getting PR Diff",
                                    "workflow_list": "Listing Workflows", "workflow_runs": "Getting Workflow Runs",
                                    "workflow_trigger": "Triggering Workflow", "workflow_cancel": "Cancelling Workflow",
                                    "workflow_rerun": "Rerunning Workflow", "workflow_get_run": "Getting Workflow Run",
                                    "repo_info": "Getting Repo Info", "search_code": "Searching Code",
                                    "search_issues": "Searching Issues", "list_branches": "Listing Branches",
                                }
                                lbl = _github_labels.get(action, "GitHubbing")
                                det = action
                            await display.status(lbl, det, description=content)
                        except json.JSONDecodeError:
                            pass

                    try:
                        tool_results = await asyncio.gather(*[_exec_one(tc) for tc in parsed])
                    except KeyboardInterrupt:
                        await display.end()
                        ctx.rollback_draft()
                        _console.print("  [yellow]⏹ Interrupted during tool execution[/]")
                        break

                    for tc, result_text in tool_results:
                        if tc.function.name == "bash":
                            result_text = OutputFilter.bash(result_text)
                        elif tc.function.name == "grep":
                            result_text = OutputFilter.grep(result_text)
                        elif tc.function.name == "web_fetch":
                            result_text = OutputFilter.web_fetch(result_text)
                        undefined = prefetcher.analyze(result_text)
                        if undefined:
                            await display.status("Prefetching")
                            prefetched = prefetcher.prefetch(undefined[:5])
                            if prefetched:
                                result_text = result_text + f"\n\n# Auto-resolved undefined symbols\n{prefetched}"
                        ctx.add_tool_result(tc.id, tc.function.name, result_text)

                    ctx.commit_draft()
                    turn += 1
                else:
                    if content:
                        resolver = PlaceholderResolver(graph)
                        if resolver.has_placeholders(content):
                            cleaned, symbols = resolver.resolve(content)
                            if symbols:
                                if cleaned:
                                    assistant.content = cleaned
                                await display.status("Resolving")
                                try:
                                    fetched = resolver.fetch(symbols)
                                except KeyboardInterrupt:
                                    await display.end()
                                    _console.print("  [yellow]⏹ Interrupted[/]")
                                    break
                                if fetched:
                                    _console.print(Text.assemble(("  ⌘ Resolved ", "cyan"), (f"{len(symbols)} placeholders", "dim")))
                                    ctx.add_assistant_message(assistant)
                                    ctx.history.append(Message(role="system", content=f"# Resolved symbol definitions\n{fetched}"))
                                    continue

                    ctx.add_assistant_message(assistant)
                    if content:
                        await display.end()
                        _console.print(Markdown(content))
                        turn_total_in = sum(r.input_tokens for r in token_counter.records[turn_start_idx:])
                        turn_total_out = sum(r.output_tokens for r in token_counter.records[turn_start_idx:])
                        turn_total_cost = sum(r.cost for r in token_counter.records[turn_start_idx:])
                        _console.print(Text.assemble(
                            ("  ∑ ", "yellow"),
                            (f"{fmt_tokens(turn_total_in)} ", ""),
                            ("in  ", "dim"),
                            ("↓ ", "cyan"),
                            (f"{fmt_tokens(turn_total_out)} ", ""),
                            ("out  ", "dim"),
                            ("│ ", "dim"),
                            (f"¥{turn_total_cost:.4f}", "bold yellow"),
                            ("  │ ", "dim"),
                            (f"{_turn_elapsed:.1f}s", "magenta"),
                        ))
                        if token_counter.records:
                            last = token_counter.records[-1]
                            ctx_pct = last.input_tokens / 1_000_000 * 100
                            cache_pct = last.cache_hit_input / last.input_tokens * 100 if last.input_tokens > 0 else 0
                            out_pct = last.output_tokens / 128_000 * 100
                            _console.print(Text.assemble(
                                ("  Context ", "dim"),
                                (f"{ctx_pct:.1f}%", "cyan"),
                                ("  Cache ", "dim"),
                                (f"{cache_pct:.0f}%", "green"),
                                ("  Output ", "dim"),
                                (f"{out_pct:.1f}%", "yellow"),
                                ("  │ ", "dim"),
                                (f"{_turn_elapsed:.1f}s", "magenta"),
                            ))
                    else:
                        await display.end()
                    break
            else:
                await display.end()
                _console.print("  [yellow]⚠[/] Reached max tool iterations")
                ctx.rollback_draft()
                if turn > 0:
                    turn -= 1

            turn_records = token_counter.records[turn_start_idx:]
            summary_in = sum(r.input_tokens for r in turn_records)
            summary_out = sum(r.output_tokens for r in turn_records)
            summary_cache = sum(r.cache_hit_input for r in turn_records)
            summary_cost = sum(r.cost for r in turn_records)
            _last_turn_elapsed = _turn_elapsed
            _turn_number += 1

            _balance_after = await client.query_balance()
            if _balance_before and _balance_after:
                try:
                    bf = float(_balance_before["balance_infos"][0]["total_balance"])
                    af = float(_balance_after["balance_infos"][0]["total_balance"])
                    real_cost = bf - af
                    _console.print(Text.assemble(
                        ("  Real: ", "bold yellow"),
                        (f"¥{real_cost:.4f}  ", "bold yellow"),
                        ("(balance: ", "dim"),
                        (f"¥{bf:.2f}", "green"),
                        (" → ", "dim"),
                        (f"¥{af:.2f}", "cyan"),
                        (")", "dim"),
                    ))
                except (KeyError, IndexError, ValueError, TypeError):
                    pass

            unsaved = ctx.history[_last_saved_len:]
            if unsaved:
                chat_store.save_messages(unsaved)
                _last_saved_len = len(ctx.history)

            chat_store.save_usage(
                turn=_turn_number,
                model=model_mode,
                input_tokens=summary_in,
                output_tokens=summary_out,
                cache_hit_input=summary_cache,
                cost=summary_cost,
            )
            turn_start_idx = len(token_counter.records)
            logger.log_turn_summary({
                "turns": turn + 1,
                "model": model_mode,
                "input_tokens": summary_in,
                "output_tokens": summary_out,
                "cache_hit_input": summary_cache,
                "cost": summary_cost,
                "elapsed": round(_turn_elapsed, 1),
            })
            warmer.set_context(ctx, model_mode)

    except BaseException:
        raise
    finally:
        _save_all(final=True)
        if not _clean_exit:
            _console.print(Text.assemble(
                ("  ⚠ Crash  Chat saved (session: ", "red"),
                (chat_store.session_id or "none", "cyan"),
                (")", "red"),
            ))


def main() -> None:
    settings = Settings()
    if settings.provider == "openai" and not settings.openai_api_key:
        print(
            "Warning: OPENAI_API_KEY not set. "
            "Set it in .env or export it, or use provider=lmstudio."
        )
    asyncio.run(run_agent_loop(settings))


if __name__ == "__main__":
    main()
