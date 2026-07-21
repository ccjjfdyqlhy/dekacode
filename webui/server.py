import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import Settings
from utils import LLMClient
from skill import SkillRegistry
from skills.todowrite import get_tracker
from prompt_engine import PromptEngine
from context import ContextManager
from models import Function, Message, ToolCall
from modes import AgentMode, ModeState
from code_graph.builder import GraphBuilder
from code_graph.cache import GraphCache
from context_gatherer import ContextGatherer
from token_counter import TokenCounter, fmt_tokens

settings = Settings()
project_root = os.getcwd()

_TOOL_STATUS_MAP = {
    "bash": "Bashing", "read_file": "Reading", "write_file": "Writing",
    "edit_file": "Editing", "read_files": "Reading", "grep_context": "Grepping",
    "list_dir": "Listing", "glob": "Globbing", "grep": "Grepping",
    "diff_file": "Diffing", "ast_summary": "Analyzing",
    "web_fetch": "Fetching", "symbol_search": "Searching", "callers": "Tracing",
    "read_symbol": "Reading", "py_check": "Checking",
    "github": "GitHubbing",
}


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
        return f"{path}  +{content.count(chr(10))} lines"
    elif name == "glob":
        return args.get("pattern", "?")
    elif name == "grep":
        return f"/{args.get('pattern', '?')}/"
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
    elif name == "list_dir":
        return args.get("path", "?")
    return ""

app = FastAPI(title="Dekacode WebUI")

COMMANDS = {
    "/mode": "Toggle agent/oneshot mode",
    "/help": "Show available commands",
    "/clear": "Clear conversation",
    "/stats": "Show context stats",
    "/cost": "Show session token cost",
    "/retry": "Retry last input",
    "/undo": "Undo last turn",
}


# ─── Engine ────────────────────────────────────────────────────────

class DekacodeEngine:
    def __init__(self):
        self.client = LLMClient(settings)
        self.graph = self._build_graph()
        self.registry = self._setup_registry()
        self.prompt_engine = PromptEngine()
        self.prompt_engine.load_all()
        self.tool_lines = self.prompt_engine.build_tool_descriptions(self.registry)
        self.system_prompt = self.prompt_engine.build_system_prompt(self.tool_lines)
        self.model_mode = "flash"
        self.client.switch_model(self.model_mode)
        self._token_counter = TokenCounter()

    def _build_graph(self):
        cache = GraphCache(project_root)
        if cache.is_fresh():
            g = cache.load()
            if g:
                return g
        builder = GraphBuilder(project_root, max_depth=settings.max_depth)
        g = builder.build()
        cache.save(g)
        return g

    def _setup_registry(self):
        registry = SkillRegistry()
        skills_config = {
            "modules": [
                "skills.web_fetch",
                "skills.bash",
                "skills.file_ops",
                "skills.git_ops",
                "skills.py_check",
                "skills.dekacode",
                "skills.github_ops",
                "skills.todowrite",
            ],
            "packages": [
                "skills.core",
                "skills.project",
            ],
            "exclude": [],
        }
        if self.graph:
            skills_config["modules"].append("skills.symbol_search")
        registry.load_skills_from_config(skills_config, graph=self.graph, settings=settings)
        return registry

    def new_session(self):
        ctx = ContextManager(self.system_prompt)
        return Session(self, ctx)

    def switch_model(self, mode: str) -> str:
        model_name = self.client.switch_model(mode)
        self.model_mode = mode
        return model_name


class Session:
    def __init__(self, engine: DekacodeEngine, ctx: ContextManager):
        self.engine = engine
        self.ctx = ctx
        self.graph = engine.graph
        self.agent_mode = ModeState()
        self._stop_requested = False
        self._rec_start = 0
        self._turn_start_time = 0.0
        self._gather_tools = {"read_file", "read_files", "glob", "grep", "grep_context",
                              "symbol_search", "callers", "read_symbol", "list_dir",
                              "web_fetch", "ast_summary", "py_check"}
        self._execute_tools = {"write_file", "edit_file", "bash",
                               "dekacode", "github", "diff_file"}

    def _filter_by_set(self, active_set):
        return [td for td in self.engine.registry.get_tool_definitions()
                if td.function["name"] in active_set]

    def stop(self):
        self._stop_requested = True

    async def process_message(self, user_input: str, websocket: WebSocket):
        self._stop_requested = False
        self._rec_start = len(self.engine._token_counter.records)
        self._turn_start_time = time.time()
        if self.agent_mode.is_oneshot():
            await self._process_oneshot(user_input, websocket)
        else:
            await self._process_agent(user_input, websocket)

    async def _send_todo(self, ws: WebSocket):
        tracker = get_tracker()
        items = [{"content": i.content, "status": i.status, "priority": i.priority} for i in tracker.items]
        if items:
            await self._send(ws, type="todo", items=items, done=tracker.all_done())

    async def _send_summary(self, ws: WebSocket):
        records = self.engine._token_counter.records[self._rec_start:]
        if not records:
            return
        total_in = sum(r.input_tokens for r in records)
        total_out = sum(r.output_tokens for r in records)
        total_cache = sum(r.cache_hit_input for r in records)
        total_cost = sum(r.cost for r in records)
        elapsed = time.time() - self._turn_start_time
        last = records[-1]
        ctx_pct = last.input_tokens / 1_000_000 * 100 if last.input_tokens else 0
        cache_pct = (last.cache_hit_input / last.input_tokens * 100) if last.input_tokens > 0 else 0
        out_pct = last.output_tokens / 128_000 * 100 if last.output_tokens else 0
        if total_in == 0 and total_out == 0:
            await self._send(ws, type="summary",
                             elapsed=round(elapsed, 1),
                             usage_supported=False)
        else:
            await self._send(ws, type="summary",
                             input_tokens=total_in,
                             output_tokens=total_out,
                             cache_hit=total_cache,
                             cache_miss=total_in - total_cache,
                             cost=round(total_cost, 4),
                             elapsed=round(elapsed, 1),
                             ctx_pct=round(ctx_pct, 1),
                             cache_pct=round(cache_pct, 0),
                             out_pct=round(out_pct, 1),
                             usage_supported=True)

    async def _collect_stream(self, messages, tools, model_mode, max_tokens, ws=None):
        content_buf = ""
        tool_calls_buf = []
        finish_reason = None
        last_usage = None
        _reasoning_active = False
        _reasoning_buf = ""
        t_start = time.time()
        last_progress = t_start
        async for chunk in self.engine.client.chat_stream(
            messages, tools, model_mode=model_mode, max_tokens=max_tokens
        ):
            if chunk.delta_reasoning:
                if not _reasoning_active:
                    _reasoning_active = True
                    if ws:
                        await self._send(ws, type="thinking_start", status="Thinking...")
                _reasoning_buf += chunk.delta_reasoning
                if ws:
                    await self._send(ws, type="reasoning_delta", content=chunk.delta_reasoning)
                    latest = _reasoning_buf.strip().rsplit('\n', 1)[-1]
                    if latest:
                        await self._send(ws, type="thinking_text", content=latest)
            if chunk.delta_content:
                content_buf += chunk.delta_content
                if ws:
                    await self._send(ws, type="text_delta", content=chunk.delta_content)
            if chunk.delta_tool_calls:
                tool_calls_buf = chunk.delta_tool_calls
                if ws and tool_calls_buf:
                    tc_name = tool_calls_buf[0]["function"]["name"]
                    prep = {
                        "bash": "Preparing command",
                        "read_file": "Preparing read",
                        "write_file": "Preparing write",
                        "edit_file": "Preparing edit",
                        "read_files": "Preparing read",
                        "glob": "Preparing search",
                        "grep": "Preparing search",
                        "grep_context": "Preparing search",
                        "list_dir": "Preparing list",
                        "diff_file": "Preparing diff",
                        "ast_summary": "Preparing analysis",
                        "web_fetch": "Preparing fetch",
                        "symbol_search": "Preparing search",
                        "callers": "Preparing trace",
                        "read_symbol": "Preparing read",
                        "py_check": "Preparing check",
                        "github": "Preparing GitHub",
                        "todowrite": "Updating todo",
                    }.get(tc_name, "Preparing")
                    await self._send(ws, type="thinking_status", status=prep)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.usage:
                last_usage = chunk.usage
            if ws and time.time() - last_progress > 0.5:
                elapsed = time.time() - t_start
                await self._send(ws, type="progress", elapsed=round(elapsed, 1))
                last_progress = time.time()
        return {
            "choices": [{
                "message": {
                    "content": content_buf or None,
                    "tool_calls": tool_calls_buf if tool_calls_buf else None,
                },
                "finish_reason": finish_reason or "stop",
            }],
            "usage": last_usage,
        }

    async def _send(self, ws: WebSocket, **data):
        if self._stop_requested:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            return False

    async def _process_agent(self, user_input: str, websocket: WebSocket):
        self.ctx.add_user_message(user_input)
        await self._send(websocket, type="thinking_start", status="Thinking...")

        for turn in range(10):
            if self._stop_requested:
                await self._send(websocket, type="thinking_done", status="Stopped")
                return

            tools = self.engine.registry.get_tool_definitions()
            request = self.ctx.build_request()

            try:
                await self._send(websocket, type="thinking_status", status="Streaming...")
                t0 = time.time()
                response = await self._collect_stream(
                    request, tools, model_mode=self.engine.model_mode, max_tokens=16384, ws=websocket
                )
                elapsed = time.time() - t0
            except Exception as e:
                await self._send(websocket, type="error", content=str(e))
                await self._send(websocket, type="thinking_done")
                return

            choices = response.get("choices")
            if not choices:
                await self._send(websocket, type="error", content="Empty response")
                await self._send(websocket, type="thinking_done")
                return

            rec = self.engine._token_counter.record(response, model=self.engine.model_mode, elapsed=elapsed)

            msg = choices[0].get("message", {})
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls")
            finish_reason = choices[0].get("finish_reason", "stop")

            if finish_reason == "length":
                self.ctx.add_assistant_message(Message(role="assistant", content=content or None))
                self.ctx.add_user_message("continue")
                continue

            assistant = Message(role="assistant", content=content or None)

            if tool_calls:
                parsed = []
                for tc in tool_calls:
                    func = Function(name=tc["function"]["name"],
                                    arguments=tc["function"]["arguments"])
                    parsed.append(ToolCall(id=tc["id"], type=tc.get("type", "function"), function=func))
                assistant.tool_calls = parsed
                self.ctx.draft.append(assistant)

                if not await self._send(websocket, type="tool_calls",
                                        calls=[{"name": tc.function.name, "args": tc.function.arguments,
                                                "id": tc.id} for tc in parsed]):
                    return

                if len(parsed) > 1:
                    preview = (content or "").replace("\n", " ")[:80]
                    batch_status = f"Batching {len(parsed)} tool calls"
                    if preview:
                        batch_status += f"  {preview}"
                    await self._send(websocket, type="thinking_status", status=batch_status)
                elif parsed:
                    tc = parsed[0]
                    try:
                        a = json.loads(tc.function.arguments)
                        label = _TOOL_STATUS_MAP.get(tc.function.name, "Working")
                        detail = _get_tool_detail(tc.function.name, a)
                        status = f"{label} {detail}" if detail else label
                        preview = (content or "").replace("\n", " ")[:60]
                        if preview:
                            status += f"  {preview}"
                        await self._send(websocket, type="thinking_status", status=status)
                    except Exception:
                        await self._send(websocket, type="thinking_status", status="Working...")

                for tc in parsed:
                    if self._stop_requested:
                        break
                    try:
                        args = json.loads(tc.function.arguments)
                        label = _TOOL_STATUS_MAP.get(tc.function.name, "Working")
                        detail = _get_tool_detail(tc.function.name, args)
                        status = f"{label} {detail}" if detail else label
                        await self._send(websocket, type="thinking_status", status=status)

                        result = await self.engine.registry.execute(tc.function.name, args)
                        text = result.output if result.success else f"[Error] {result.output}"
                        self.ctx.add_tool_result(tc.id, tc.function.name, text)
                        await self._send(websocket, type="tool_result",
                                         id=tc.id, name=tc.function.name,
                                         success=result.success, content=text[:2000])
                        if tc.function.name == "todowrite":
                            await self._send_todo(websocket)
                    except json.JSONDecodeError as e:
                        text = f"[Parse Error] {e}"
                        self.ctx.add_tool_result(tc.id, tc.function.name, text)
                        await self._send(websocket, type="tool_result",
                                         id=tc.id, name=tc.function.name,
                                         success=False, content=text[:2000])
                    except Exception as e:
                        text = f"[Error] {type(e).__name__}: {e}"
                        self.ctx.add_tool_result(tc.id, tc.function.name, text)
                        await self._send(websocket, type="tool_result",
                                         id=tc.id, name=tc.function.name,
                                         success=False, content=text[:2000])
                self.ctx.commit_draft()
            else:
                if content:
                    self.ctx.add_assistant_message(assistant)
                    await self._send(websocket, type="text", content=content)
                await self._send_summary(websocket)
                await self._send(websocket, type="thinking_done")
                break

    async def _process_oneshot(self, user_input: str, websocket: WebSocket):
        gatherer = ContextGatherer(project_root, self.graph)
        parse_result = gatherer.parse(user_input)
        oneshot_input = parse_result.clean_input or user_input

        if parse_result.directives_found and parse_result.context_block:
            self.ctx.history.append(Message(role="system", content=parse_result.context_block))

        await self._send(websocket, type="thinking_start",
                         status="Gathering info (phase 1/2)")

        # ── Phase 1: Gather ──
        gather_prompt = self.engine.prompt_engine.build_oneshot_system_prompt("gather", self.engine.tool_lines)
        gather_msgs = [Message(role="system", content=gather_prompt)]
        gather_msgs += self.ctx.history + self.ctx.draft
        gather_msgs.append(Message(role="user", content=oneshot_input))
        gather_tools = self._filter_by_set(self._gather_tools)

        await self._send(websocket, type="thinking_status", status="Gathering info (phase 1/2)")
        if self._stop_requested:
            return
        try:
            await self._send(websocket, type="thinking_status", status="Streaming gather...")
            t0 = time.time()
            response = await self._collect_stream(gather_msgs, gather_tools,
                                                  model_mode=self.engine.model_mode, max_tokens=16384, ws=websocket)
            elapsed = time.time() - t0
        except Exception as e:
            await self._send(websocket, type="error", content=f"Gather phase error: {e}")
            await self._send(websocket, type="thinking_done")
            return

        choices = response.get("choices")
        if not choices:
            await self._send(websocket, type="error", content="Empty gather response")
            await self._send(websocket, type="thinking_done")
            return

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls")
        gather_content = msg.get("content") or ""

        if tool_calls and not self._stop_requested:
            parsed = []
            for tc in tool_calls:
                func = Function(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                parsed.append(ToolCall(id=tc["id"], type=tc.get("type", "function"), function=func))

            assistant = Message(role="assistant", content=gather_content or None)
            assistant.tool_calls = parsed
            self.ctx.draft.append(assistant)

            await self._send(websocket, type="tool_calls", phase="gather",
                             calls=[{"name": tc.function.name, "args": tc.function.arguments,
                                     "id": tc.id} for tc in parsed])

            if len(parsed) > 1:
                await self._send(websocket, type="thinking_status",
                                 status=f"Batching {len(parsed)} tool calls")
            elif parsed:
                tc = parsed[0]
                try:
                    a = json.loads(tc.function.arguments)
                    label = _TOOL_STATUS_MAP.get(tc.function.name, "Working")
                    detail = _get_tool_detail(tc.function.name, a)
                    status = f"{label} {detail}" if detail else label
                    await self._send(websocket, type="thinking_status", status=status)
                except Exception:
                    pass

            for tc in parsed:
                if self._stop_requested:
                    break
                result_text, is_ok = await self._exec_one_tc_result(tc)
                self.ctx.add_tool_result(tc.id, tc.function.name, result_text)
                await self._send(websocket, type="tool_result",
                                 id=tc.id, name=tc.function.name,
                                 success=is_ok, content=result_text[:2000])
                if tc.function.name == "todowrite":
                    await self._send_todo(websocket)
            self.ctx.commit_draft()

        # ── Phase 2: Execute ──
        if self._stop_requested:
            await self._send(websocket, type="thinking_done")
            return

        exec_prompt = self.engine.prompt_engine.build_oneshot_system_prompt("execute", self.engine.tool_lines)
        exec_msgs = [Message(role="system", content=exec_prompt)]
        exec_msgs += self.ctx.history + self.ctx.draft
        exec_tools = self._filter_by_set(self._execute_tools)

        await self._send(websocket, type="thinking_status", status="Planning execution (phase 2/2)")
        try:
            await self._send(websocket, type="thinking_status", status="Streaming execute...")
            t0 = time.time()
            response = await self._collect_stream(exec_msgs, exec_tools,
                                                  model_mode=self.engine.model_mode, max_tokens=16384, ws=websocket)
            elapsed = time.time() - t0
        except Exception as e:
            await self._send(websocket, type="error", content=f"Execute phase error: {e}")
            await self._send(websocket, type="thinking_done")
            return

        choices = response.get("choices")
        if not choices:
            await self._send(websocket, type="error", content="Empty execute response")
            await self._send(websocket, type="thinking_done")
            return

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls")
        content = msg.get("content") or ""

        if tool_calls and not self._stop_requested:
            parsed = []
            for tc in tool_calls:
                func = Function(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                parsed.append(ToolCall(id=tc["id"], type=tc.get("type", "function"), function=func))

            assistant = Message(role="assistant", content=content or None)
            assistant.tool_calls = parsed
            self.ctx.draft.append(assistant)

            await self._send(websocket, type="tool_calls", phase="execute",
                             calls=[{"name": tc.function.name, "args": tc.function.arguments,
                                     "id": tc.id} for tc in parsed])

            for tc in parsed:
                if self._stop_requested:
                    break
                try:
                    args = json.loads(tc.function.arguments)
                    label = _TOOL_STATUS_MAP.get(tc.function.name, "Working")
                    detail = _get_tool_detail(tc.function.name, args)
                    status = f"{label} {detail}" if detail else label
                    await self._send(websocket, type="thinking_status", status=status)
                except Exception:
                    pass
                result_text, is_ok = await self._exec_one_tc_result(tc)
                self.ctx.add_tool_result(tc.id, tc.function.name, result_text)
                await self._send(websocket, type="tool_result", id=tc.id,
                                 name=tc.function.name, success=is_ok,
                                 content=result_text[:2000])
                if tc.function.name == "todowrite":
                    await self._send_todo(websocket)
            self.ctx.commit_draft()

        if content and not self._stop_requested:
            await self._send(websocket, type="text", content=content)

        await self._send_summary(websocket)
        await self._send(websocket, type="thinking_done")

    async def _exec_one_tc_result(self, tc: ToolCall):
        try:
            args = json.loads(tc.function.arguments)
            result = await self.engine.registry.execute(tc.function.name, args)
            return (result.output, result.success)
        except Exception as e:
            return (f"[Error] {e}", False)


# ── Global engine ──

engine = DekacodeEngine()


@app.on_event("startup")
async def startup():
    print(f"  Dekacode WebUI ready  project={project_root}  model={engine.client.model}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = engine.new_session()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "message":
                text = msg.get("content", "").strip()
                if not text:
                    continue
                if text.startswith("/"):
                    await _handle_command(text, session, websocket)
                else:
                    await session.process_message(text, websocket)

            elif msg_type == "stop":
                session.stop()

            elif msg_type == "temp_session":
                session = engine.new_session()

            elif msg_type == "restore_session":
                session = engine.new_session()

            elif msg_type == "mode":
                mode = msg.get("mode", "agent")
                try:
                    session.agent_mode.set(mode)
                except ValueError:
                    session.agent_mode.toggle()
                await websocket.send_json({
                    "type": "mode_changed",
                    "mode": session.agent_mode.mode.value,
                })

            elif msg_type == "switch_model":
                model_id = msg.get("model", "flash")
                try:
                    model_name = engine.switch_model(model_id)
                    await websocket.send_json({
                        "type": "model_switched",
                        "model": model_id,
                        "display": model_name,
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Failed to switch model: {e}",
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass


async def _handle_command(cmd: str, session: Session, ws: WebSocket):
    parts = cmd.split()
    command = parts[0]

    if command == "/help":
        lines = [f"  {k}  {v}" for k, v in COMMANDS.items()]
        await ws.send_json({"type": "command_output", "content": "Available commands:\n" + "\n".join(lines)})

    elif command == "/mode":
        if len(parts) > 1:
            try:
                session.agent_mode.set(parts[1])
            except ValueError:
                await ws.send_json({"type": "command_output", "content": f"Invalid mode '{parts[1]}'. Use 'agent' or 'oneshot'."})
                return
        else:
            session.agent_mode.toggle()
        mode = session.agent_mode.mode.value
        await ws.send_json({"type": "mode_changed", "mode": mode})
        hint = " Use @req/@sym/@grep/@ls/@tree" if mode == "oneshot" else ""
        await ws.send_json({"type": "command_output", "content": f"Mode switched to: {mode}.{hint}"})

    elif command == "/clear":
        session.ctx.history.clear()
        session.ctx.draft.clear()
        await ws.send_json({"type": "command_output", "content": "Conversation cleared."})

    elif command == "/stats":
        total = session.ctx.total_messages()
        await ws.send_json({
            "type": "command_output",
            "content": f"Context: system=1 prefix={len(session.ctx.prefix)} "
                       f"history={len(session.ctx.history)} draft={len(session.ctx.draft)} "
                       f"total={total}",
        })

    elif command == "/cost":
        records = engine._token_counter.records
        if records:
            total_in = sum(r.input_tokens for r in records)
            total_out = sum(r.output_tokens for r in records)
            total_cost = sum(r.cost for r in records)
            await ws.send_json({
                "type": "command_output",
                "content": f"Tokens: {fmt_tokens(total_in)} in, {fmt_tokens(total_out)} out  Cost: ¥{total_cost:.4f}",
            })
        else:
            await ws.send_json({"type": "command_output", "content": "No API calls yet."})

    elif command == "/retry":
        await ws.send_json({"type": "command_output", "content": "Retry not supported in WebUI (resend your message)."})

    elif command == "/undo":
        await ws.send_json({"type": "command_output", "content": "Undo not supported in WebUI (use /clear to reset)."})

    else:
        await ws.send_json({"type": "command_output", "content": f"Unknown command: {command}. Type /help for available commands."})


@app.get("/api/status")
async def status():
    return {
        "model": engine.client.model,
        "project": project_root,
        "symbols": engine.graph.total_symbols() if engine.graph else 0,
        "files": len(engine.graph.files) if engine.graph else 0,
    }

@app.get("/api/commands")
async def list_commands():
    return [{"cmd": k, "desc": v} for k, v in COMMANDS.items()]

@app.get("/api/balance")
async def balance():
    try:
        result = await engine.client.query_balance()
        return result or {}
    except Exception:
        return {}

@app.get("/api/models")
async def list_models():
    models = engine.client.list_models()
    for m in models:
        m["active"] = m["id"] == engine.model_mode
    return models


@app.get("/api/options")
async def get_options():
    return {
        "thinking_collapsed_default": settings.thinking_collapsed_default,
    }


@app.post("/api/options")
async def set_options(request: Request):
    data = await request.json()
    if "thinking_collapsed_default" in data:
        settings.thinking_collapsed_default = data["thinking_collapsed_default"]
        env_path = Path(__file__).parent.parent / ".env"
        _update_env_file(env_path, "THINKING_COLLAPSED_DEFAULT",
                         str(settings.thinking_collapsed_default).lower())
    return {"thinking_collapsed_default": settings.thinking_collapsed_default}


def _update_env_file(path: Path, key: str, value: str):
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines(True)
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}=") or line.strip().startswith(f"# {key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"\n{key}={value}\n")
    path.write_text("".join(lines), encoding="utf-8")


# ── Serve static files ──

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def main():
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
