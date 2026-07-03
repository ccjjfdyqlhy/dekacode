import asyncio
import json
import os
import re
import time

VERSION = "V0.1"

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

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
from rich import box

from code_graph.placeholders import PlaceholderResolver
from status_display import StatusDisplay
from token_counter import TokenCounter
from utils import LLMClient

_FILE_REF_RE = re.compile(r"([\w./\\-]+\.py)")

MAX_CONVERSATION_HISTORY = 40


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
            _rc.print(f"  [dim]Call graph:[/] [green]{graph.total_symbols()}[/] [dim]symbols,[/] [green]{len(graph.files)}[/] [dim]files (cached)[/]")
            return graph
    _rc.print(f"  [yellow]⟳[/] [dim]Building call graph (full scan)...[/]")
    t0 = time.time()
    builder = GraphBuilder(project_root)
    graph = builder.build()
    cache.save(graph)
    _rc.print(f"  [green]✓[/] [dim]{graph.total_symbols()} symbols, {len(graph.files)} files in[/] {time.time()-t0:.1f}s")
    return graph


async def run_agent_loop(settings: Settings) -> None:
    client = LLMClient(settings)
    project_root = os.getcwd()

    from rich.console import Console as _RichConsole
    _console = _RichConsole()
    _console.print(f"━ [bold cyan]Dekacode[/] [yellow]{VERSION}[/] [dim]@[/] [green]{project_root}[/] [bold cyan]activated[/]", style="bold")

    graph = _build_graph(project_root)
    registry = _setup_registry(graph)

    prompt_engine = PromptEngine()
    prompt_engine.load_all()
    tool_lines = prompt_engine.build_tool_descriptions(registry)
    system_prompt = prompt_engine.build_system_prompt(tool_lines)
    _console.print(f"  [dim]Prompts:[/] [green]{len(prompt_engine.get_enabled())}[/] [dim]enabled[/]")
    for line in prompt_engine.summary().split("\n"):
        _console.print(f"  {line}")

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

    _console.print(f"  [bold green]Code Agent ready[/]  [dim]provider=[/][yellow]{settings.provider}[/] [dim]model=[/][cyan]{current_model_name}[/]")
    _console.print(f"  [dim]mode=[/][magenta]{model_mode}[/]  [dim]peak=[/]{'[red]⚠[/]' if in_peak_hours() else '[green]✓[/]'}")
    _console.print("  [dim]Commands:[/] [cyan]/cost[/] [cyan]/stats[/] [cyan]/graph[/] [cyan]/sessions[/] [cyan]/resume[/] [cyan]/load[/] [cyan]/flash[/] [cyan]/pro[/] [cyan]/mode[/] [cyan]/help[/]")
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
            _console.print(f"  [yellow]⟳[/] [dim]{len(changed)} file(s) modified, rebuilding call graph...[/]")
            t0 = time.time()
            builder = GraphBuilder(project_root)
            graph = builder.build()
            graph_cache.save(graph)
            _console.print(f"  [green]✓[/] [dim]Rebuilt in[/] {time.time()-t0:.1f}s [dim]({graph.total_symbols()} symbols)[/]")

    _clean_exit = False
    _turn_number = 0
    _last_saved_len = 0
    _prompt_session = PromptSession(history=InMemoryHistory())
    display = StatusDisplay()

    def _save_all(final: bool = False) -> None:
        nonlocal _last_saved_len
        unsaved = ctx.history[_last_saved_len:]
        if unsaved and (final or not _clean_exit):
            chat_store.save_messages(unsaved)
            _last_saved_len = len(ctx.history)
        if token_counter.records and not _clean_exit:
            pending = token_counter.records[turn_start_idx:]
            if pending:
                _turn_number += 1
                chat_store.save_usage(
                    turn=_turn_number, model=model_mode,
                    input_tokens=sum(r.input_tokens for r in pending),
                    output_tokens=sum(r.output_tokens for r in pending),
                    cache_hit_input=sum(r.cache_hit_input for r in pending),
                    cost=sum(r.cost for r in pending),
                )
        if token_counter.records:
            _console.print(f"  [yellow]{token_counter.session_summary()}[/]")
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
                _console.print(f"\n > {m.content}")
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
        _console.print(f"  [green]Loaded[/] [cyan]{sid}[/]: [yellow]{len(hist)}[/] [dim]msgs,[/] [yellow]¥{total_cost:.4f}[/], [cyan]{int(total_in/1000)}K[/] [dim]in[/]")
        _render_hist(hist)
        return True

    try:
        while True:
            try:
                user_input = (await _prompt_session.prompt_async(" > ")).strip()
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
                    _console.print(f"  [yellow]{token_counter.session_summary()}[/]")
                else:
                    _console.print("  [dim]No API calls yet.[/]")

            elif user_input == "/stats":
                total = ctx.total_messages()
                _console.print(f"  [bold]Context:[/] [cyan]prefix={len(ctx.prefix)}[/] [cyan]history={len(ctx.history)}[/] [cyan]draft={len(ctx.draft)}[/] [dim]total={total}[/]")
                _console.print(f"  [bold]API calls:[/] [yellow]{len(token_counter.records)}[/]")
                _console.print(f"  [bold]Graph:[/] [green]{graph.total_symbols()}[/] [dim]symbols,[/] [green]{len(graph.files)}[/] [dim]files[/]")
                _console.print(f"  [bold]Model:[/] [magenta]{model_mode}[/] [dim]({current_model_name})[/]")

            elif user_input == "/graph":
                _console.print(Syntax(graph.to_compact_map()[:3000], "python", word_wrap=True))

            elif user_input == "/sessions":
                all_sessions = chat_store.list_sessions(limit=20)
                if not all_sessions:
                    _console.print("  [dim]No saved sessions[/]")
                else:
                    for s in all_sessions:
                        cur = "[green]←[/]" if s["id"] == chat_store.session_id else " "
                        summary = s["summary"][:60] if s["summary"] else "[dim](no summary)[/]"
                        cost_str = f" [yellow]¥{s['total_cost']:.4f}[/]" if s['total_cost'] > 0 else ""
                        tokens_str = f" [cyan]{int(s['total_input']/1000)}K in[/]" if s['total_input'] > 0 else ""
                        _console.print(f"  {cur} [cyan]{s['id']}[/] [dim]({s['message_count']} msgs)[/]{cost_str}{tokens_str}  {summary}")

            elif user_input == "/resume":
                recent = chat_store.list_sessions(limit=1)
                if not recent:
                    _console.print("  [dim]No previous session[/]")
                else:
                    _load_session(recent[0]["id"])

            elif user_input.startswith("/load "):
                sid = user_input[6:].strip()
                if not _load_session(sid):
                    _console.print(f"  [red]Session '{sid}' not found or empty[/]")

            elif user_input == "/flash":
                model_mode = router.switch("flash")
                current_model_name = client.switch_model("flash")
                _console.print(f"  [cyan]Switched to flash:[/] [bold]{current_model_name}[/]")

            elif user_input == "/pro":
                model_mode = router.switch("pro")
                current_model_name = client.switch_model("pro")
                _console.print(f"  [magenta]Switched to pro:[/] [bold]{current_model_name}[/]")

            elif user_input == "/mode":
                model_mode = router.switch("auto")
                peak = in_peak_hours()
                model_mode = "flash"
                current_model_name = client.switch_model("flash")
                _console.print(f"  [green]Auto mode:[/] [magenta]{model_mode}[/] [dim]({current_model_name})[/] peak={'[red]⚠[/]' if peak else '[green]✓[/]'}")

            elif user_input == "/help":
                _console.print("  [cyan]/cost[/]     [dim]Show session token cost[/]")
                _console.print("  [cyan]/stats[/]    [dim]Show context stats[/]")
                _console.print("  [cyan]/graph[/]    [dim]Show project symbol map[/]")
                _console.print("  [cyan]/sessions[/] [dim]List saved chat sessions[/]")
                _console.print("  [cyan]/resume[/]   [dim]Load most recent session[/]")
                _console.print("  [cyan]/load id[/]  [dim]Load a past session by ID[/]")
                _console.print("  [cyan]/flash[/]    [dim]Switch to flash model (cheap)[/]")
                _console.print("  [cyan]/pro[/]      [dim]Switch to pro model (powerful)[/]")
                _console.print("  [cyan]/mode[/]     [dim]Auto model selection[/]")
                _console.print("  [cyan]/exit[/]     [dim]Exit[/]")

            else:
                if not chat_store.session_id:
                    chat_store.create_session()
                _trim_history(ctx)
                ctx.add_user_message(user_input)
                _attach_imports(ctx, user_input)

                _rebuild_graph_if_dirty()
                turn_start_idx = len(token_counter.records)
                turn = 0
                model_mode = router.select()
                current_model_name = client.switch_model(model_mode)

                while turn < settings.max_tool_iterations:
                    _rebuild_graph_if_dirty()
                    tools = registry.get_tool_definitions()
                    request = ctx.build_request()
                    try:
                        await display.status("Thinking")
                        response = await client.chat(request, tools, model_mode=model_mode)
                    except Exception as e:
                        await display.done()
                        _console.print(f"\n  [red]✗ API Error:[/] {e}")
                        ctx.rollback_draft()
                        break

                    choices = response.get("choices")
                    if not choices:
                        await display.done()
                        _console.print("\n  [red]✗ API Error: empty response[/]")
                        ctx.rollback_draft()
                        break

                    await display.done()
                    rec = token_counter.record(response, model=model_mode)
                    _console.print(f"  {token_counter.display(rec)}")

                    if settings.max_session_cost > 0 and token_counter.session_cost > settings.max_session_cost:
                        _console.print(f"\n[red]Budget exceeded:[/] ¥{token_counter.session_cost:.4f} > ¥{settings.max_session_cost:.4f}")
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
                        ctx.add_assistant_message(assistant)
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
                                    await display.status(tool_label)
                                    result = await registry.execute(tc.function.name, args)
                                    result_text = result.output if result.success else f"[Error] {result.output}"
                            except Exception as e:
                                result_text = f"[Error] Tool crashed: {type(e).__name__}: {e}"

                            await display.done()
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
                                await display.done()
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
                                    await display.done()
                                    if fetched:
                                        _console.print(f"  [cyan]⌘[/] [dim]Resolved {len(symbols)} placeholders[/]")
                                        ctx.add_assistant_message(assistant)
                                        ctx.add_tool_result(
                                            "_placeholder",
                                            "_placeholder",
                                            f"# Fetched definitions\n{fetched}",
                                        )
                                        continue

                        ctx.add_assistant_message(assistant)
                        if content:
                                _console.print(Markdown(content))
                                if token_counter.records:
                                    last = token_counter.records[-1]
                                    ctx_pct = last.input_tokens / 1_000_000 * 100
                                    cache_pct = last.cache_hit_input / last.input_tokens * 100 if last.input_tokens > 0 else 0
                                    out_pct = last.output_tokens / 128_000 * 100
                                    _console.print(f"  [dim]Context[/] [cyan]{ctx_pct:.1f}%[/]  [dim]Cache[/] [green]{cache_pct:.0f}%[/]  [dim]Output[/] [yellow]{out_pct:.1f}%[/]")
                        break
                else:
                    _console.print("  [yellow]⚠[/] [dim]Reached max tool iterations[/]")
                    ctx.rollback_draft()
                    if turn > 0:
                        turn -= 1

                turn_records = token_counter.records[turn_start_idx:]
                summary_in = sum(r.input_tokens for r in turn_records)
                summary_out = sum(r.output_tokens for r in turn_records)
                summary_cache = sum(r.cache_hit_input for r in turn_records)
                summary_cost = sum(r.cost for r in turn_records)
                _turn_number += 1
                chat_store.save_usage(
                    turn=_turn_number,
                    model=model_mode,
                    input_tokens=summary_in,
                    output_tokens=summary_out,
                    cache_hit_input=summary_cache,
                    cost=summary_cost,
                )
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
            _console.print(f"  [red]⚠ Crash[/] [dim]Chat saved (session:[/] [cyan]{chat_store.session_id}[/][dim])[/]")


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
