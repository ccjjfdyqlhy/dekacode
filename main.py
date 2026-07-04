import asyncio
import json
import os
import re
import sys
import time

VERSION = "V0.1"

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
from token_counter import TokenCounter
from utils import LLMClient

_FILE_REF_RE = re.compile(r"([\w./\\-]+\.py)")

MAX_CONVERSATION_HISTORY = 40


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
    return ""


def _trim_history(ctx: ContextManager) -> None:
    total = len(ctx.history)
    if total <= MAX_CONVERSATION_HISTORY:
        return
    keep = MAX_CONVERSATION_HISTORY
    ctx.history = ctx.history[-keep:]


def _setup_registry(graph=None) -> SkillRegistry:
    from skills.web_fetch import WebFetchSkill
    from skills.bash import BashSkill
    from skills.file_ops import (
        ReadFileSkill,
        WriteFileSkill,
        GlobSkill,
        GrepSkill,
    )

    registry = SkillRegistry()
    registry.register(WebFetchSkill())
    registry.register(BashSkill())
    registry.register(ReadFileSkill())
    registry.register(WriteFileSkill())
    registry.register(GlobSkill())
    registry.register(GrepSkill())

    if graph:
        from skills.symbol_search import SymbolSearchSkill, CallersSkill, ReadSymbolSkill
        registry.register(SymbolSearchSkill(graph))
        registry.register(CallersSkill(graph))
        registry.register(ReadSymbolSkill(graph))

    from skills.py_check import PyCheckSkill
    registry.register(PyCheckSkill())

    return registry


def _attach_imports(ctx: ContextManager, user_input: str) -> None:
    from code_graph.imports import ImportResolver
    matches = _FILE_REF_RE.findall(user_input)
    if not matches:
        return
    resolver = ImportResolver(".")
    blocks: list[str] = []
    for fpath in set(matches):
        sigs = resolver.resolve(fpath)
        if sigs:
            lines = "\n".join(s.to_prompt_block() for s in sigs)
            blocks.append(f"# imports from {fpath}\n{lines}")
    if blocks:
        attachment = "\n\n".join(blocks)
        ctx.set_prefix_attachment(f"# Resolved imports\n{attachment}")


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
    project_root = os.getcwd()

    from rich.console import Console as _RichConsole
    _console = _RichConsole()
    _console.clear()
    _console.print(Text.assemble(
        ("  ━ Dekacode ", "bold cyan"),
        (VERSION, "yellow"),
        (" @ ", "dim"),
        (project_root, "green"),
        (" activated", "bold cyan"),
    ))

    graph = _build_graph(project_root)
    registry = _setup_registry(graph)

    prompt_engine = PromptEngine()
    prompt_engine.load_all()
    tool_lines = prompt_engine.build_tool_descriptions(registry)
    system_prompt = prompt_engine.build_system_prompt(tool_lines)
    _console.print(Text.assemble(
        ("  Prompts: ", "dim"),
        (f"{len(prompt_engine.get_enabled())} enabled", "green"),
    ))
    for line in prompt_engine.summary().split("\n"):
        _console.print(Text(f"  {line}", style="dim"))

    ctx = ContextManager(system_prompt)
    token_counter = TokenCounter()
    prefetcher = SpeculativePrefetcher(graph)
    router = ModelRouter()
    logger = SessionLogger(log_dir=settings.log_dir)
    chat_store = ChatStore(project_root)

    _console.print("  [dim]Type /resume to continue last session, or just type a message to start fresh.[/]")

    compact_map = graph.to_compact_map()
    ctx.set_prefix_attachment(f"# Project structure\n{compact_map[:2000]}")

    model_mode = settings.default_model or "flash"
    client.switch_model(model_mode)
    current_model_name = client.model

    turn_start_idx = 0

    _console.print(Text.assemble(
        ("  Code Agent ready", "bold green"),
        ("  provider=", "dim"), (settings.provider, "yellow"),
        ("  model=", "dim"), (current_model_name, "cyan"),
    ))
    _console.print(Text.assemble(
        ("  mode=", "dim"), (model_mode, "magenta"),
        ("  peak=", "dim"), ("⚠", "red") if in_peak_hours() else ("✓", "green"),
    ))
    _console.print(Text.assemble(
        ("  Commands: ", "dim"),
        *[pair for cmd in ["cost", "stats", "graph", "sessions", "resume", "save", "load", "flash", "pro", "mode", "help"]
        for pair in [(f"/{cmd}", "cyan"), (" ", "dim")]],
    ))
    _console.print("  [dim]Type your message or 'exit' to quit.[/]\n")

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
    _last_saved_len = 0
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
        logger.save()

    _tool_status_map = {
        "bash": "Bashing", "read_file": "Reading", "write_file": "Writing",
        "glob": "Globbing", "grep": "Grepping", "web_fetch": "Fetching",
        "symbol_search": "Searching", "callers": "Tracing",
        "read_symbol": "Reading", "py_check": "Checking",
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
        nonlocal _last_saved_len
        hist = chat_store.load_messages(sid)
        if not hist:
            return False
        chat_store.set_session(sid)
        ctx.history = hist
        _last_saved_len = len(hist)
        usage = chat_store.load_usage(sid)
        total_cost = sum(u["cost"] for u in usage)
        total_in = sum(u["input_tokens"] for u in usage)
        _console.print(Text.assemble(
            ("  Loaded ", "green"),
            (sid, "cyan"),
            (f"  {len(hist)} msgs", "yellow"),
            (f"  ¥{total_cost:.4f}", "bold yellow"),
            (f"  {int(total_in/1000)}K in", "cyan"),
        ))
        _render_hist(hist)
        return True

    try:
        while True:
            try:
                user_input = (await _prompt_session.prompt_async("\n > ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                _clean_exit = True
                break

            if user_input.lower() in ("exit", "quit", "/exit"):
                _clean_exit = True
                break

            if not user_input:
                continue

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
                table.add_row("Context", f"[cyan]prefix={len(ctx.prefix)}[/] [cyan]history={len(ctx.history)}[/] [cyan]draft={len(ctx.draft)}[/] [dim]total={total}[/]")
                table.add_row("API calls", f"[yellow]{len(token_counter.records)}[/]")
                table.add_row("Graph", f"[green]{graph.total_symbols()}[/] [dim]symbols,[/] [green]{len(graph.files)}[/] [dim]files[/]")
                table.add_row("Model", f"[magenta]{model_mode}[/] [dim]({current_model_name})[/]")
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
                        tokens = f"{int(s['total_input']/1000)}K" if s['total_input'] > 0 else ""
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

            elif user_input == "/help":
                table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                table.add_column("Command", style="cyan", no_wrap=True)
                table.add_column("Description", style="dim")
                table.add_row("/cost", "Show session token cost")
                table.add_row("/stats", "Show context stats")
                table.add_row("/graph", "Show project symbol map")
                table.add_row("/sessions", "List saved chat sessions")
                table.add_row("/resume", "Load most recent session")
                table.add_row("/save", "Save current session now")
                table.add_row("/load id", "Load a past session by ID")
                table.add_row("/flash", "Switch to flash model (cheap)")
                table.add_row("/pro", "Switch to pro model (powerful)")
                table.add_row("/mode", "Auto model selection")
                table.add_row("/exit", "Exit")
                _console.print(table)

            elif user_input.startswith("/"):
                _console.print(f"  [yellow]Unknown command:[/] {user_input}")

            else:
                if not chat_store.session_id:
                    chat_store.create_session()
                _trim_history(ctx)
                _last_saved_len = min(_last_saved_len, len(ctx.history))
                ctx.add_user_message(user_input)
                _attach_imports(ctx, user_input)

                _rebuild_graph_if_dirty()
                turn_start_idx = len(token_counter.records)
                turn = 0
                model_mode = router.select()
                current_model_name = client.switch_model(model_mode)

                await display.begin()
                while turn < settings.max_tool_iterations:
                    _rebuild_graph_if_dirty()
                    tools = registry.get_tool_definitions()
                    request = ctx.build_request()
                    try:
                        await display.status("Thinking")
                        response = await client.chat(request, tools, model_mode=model_mode)
                    except Exception as e:
                        await display.end()
                        _console.print(f"  [red]✗ API Error:[/] {e}")
                        ctx.rollback_draft()
                        break

                    choices = response.get("choices")
                    if not choices:
                        await display.end()
                        _console.print("  [red]✗ API Error: empty response[/]")
                        ctx.rollback_draft()
                        break

                    rec = token_counter.record(response, model=model_mode)
                    display.token(token_counter.display(rec))

                    if settings.max_session_cost > 0 and token_counter.session_cost > settings.max_session_cost:
                        await display.end()
                        _console.print(f"  [red]Budget exceeded:[/] ¥{token_counter.session_cost:.4f} > ¥{settings.max_session_cost:.4f}")
                        logger.save()
                        _clean_exit = True
                        return

                    msg = choices[0].get("message", {})
                    content = msg.get("content") or ""
                    tool_calls = msg.get("tool_calls")

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
                        if content:
                            _console.print(Markdown(content))

                        for tc in parsed:
                            try:
                                try:
                                    args = json.loads(tc.function.arguments)
                                except json.JSONDecodeError as e:
                                    result_text = f"[Parse Error] Invalid JSON arguments: {e}"
                                else:
                                    tool_label = {
                                        "bash": "Bashing",
                                        "read_file": "Reading",
                                        "write_file": "Writing",
                                        "glob": "Globbing",
                                        "grep": "Grepping",
                                        "web_fetch": "Fetching",
                                        "symbol_search": "Searching",
                                        "callers": "Tracing",
                                        "read_symbol": "Reading",
                                        "py_check": "Checking",
                                    }.get(tc.function.name, "Working")
                                    detail = _get_tool_detail(tc.function.name, args)
                                    if tc.function.name == "bash":
                                        cmd = args.get("command", "")
                                        if cmd.lstrip().startswith("grep"):
                                            tool_label = "Grepping"
                                    await display.status(tool_label, detail)
                                    result = await registry.execute(tc.function.name, args)
                                    result_text = result.output if result.success else f"[Error] {result.output}"
                            except Exception as e:
                                result_text = f"[Error] Tool crashed: {type(e).__name__}: {e}"

                            if tc.function.name == "bash":
                                result_text = OutputFilter.bash(result_text)
                            elif tc.function.name == "grep":
                                result_text = OutputFilter.grep(result_text)
                            elif tc.function.name == "web_fetch":
                                result_text = OutputFilter.web_fetch(result_text)

                            ctx.add_tool_result(tc.id, tc.function.name, result_text)

                            undefined = prefetcher.analyze(result_text)
                            if undefined:
                                await display.status("Prefetching")
                                prefetched = prefetcher.prefetch(undefined[:5])
                                if prefetched:
                                    ctx.add_tool_result(
                                        f"{tc.id}_prefetch",
                                        "_prefetch",
                                        f"# Auto-resolved undefined symbols\n{prefetched}",
                                    )

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
                                    fetched = resolver.fetch(symbols)
                                    if fetched:
                                        _console.print(Text.assemble(("  ⌘ Resolved ", "cyan"), (f"{len(symbols)} placeholders", "dim")))
                                        ctx.add_assistant_message(assistant)
                                        ctx.add_tool_result(
                                            "_placeholder",
                                            "_placeholder",
                                            f"# Fetched definitions\n{fetched}",
                                        )
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
                                (f"{turn_total_in} ", ""),
                                ("in  ", "dim"),
                                ("↓ ", "cyan"),
                                (f"{turn_total_out} ", ""),
                                ("out  ", "dim"),
                                ("│ ", "dim"),
                                (f"¥{turn_total_cost:.4f}", "bold yellow"),
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
                _turn_number += 1

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
                logger.log_turn({
                    "user_message": user_input[:200],
                    "turns": turn + 1,
                    "model": model_mode,
                    "input_tokens": summary_in,
                    "output_tokens": summary_out,
                    "cache_hit_input": summary_cache,
                    "cost": summary_cost,
                })

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
