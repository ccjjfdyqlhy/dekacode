# Dekacode

**Token-efficient AI Coding Agent for the terminal.**

Dekacode is an interactive AI assistant specialized in software engineering. It runs in your terminal, understands natural language, and autonomously performs file system and shell operations through LLM tool-calling. Every design decision prioritizes **token efficiency** — minimized context, aggressive caching, and smart model routing keep costs low.

---

## Features

- **Tool-calling agent** — read/write files, execute bash, glob, grep, fetch URLs, search symbols, check Python syntax
- **Call graph** — AST-based project-wide symbol index with caller/callee chain traversal (up to 143 symbols indexed in ~0.01s)
- **Token-first architecture**
  - Append-only context loop + fixed prefix → maximizes DeepSeek V4 prefix cache hits (cost as low as ¥0.025/1M tokens)
  - Speculative pre-fetch: auto-resolves undefined symbols from error output
  - `[FETCH:Class:Name]` placeholder protocol — model requests definitions on demand
  - RTK output filters: strips ANSI, timestamps, UUIDs from bash/grep output
- **Dual model routing** — Flash (cheap) for simple tasks, Pro (powerful) for complex ones; auto-downgrades during peak hours
- **Rich terminal UI** — Markdown rendering, syntax highlighting, real-time status spinner with per-operation timing
- **Session persistence** — SQLite-backed conversation history with `/resume` to restore
- **Prompt fragments** — Modular system prompt with YAML front matter (`enabled: true/false`, `order:`)
- **File watcher** — Detects source changes and incrementally rebuilds the call graph
- **Cost observability** — Per-call token/cache/cost tracking with budget limits

---

## Quick Start

### Requirements

- Python 3.12+
- An OpenAI-compatible API endpoint (DeepSeek, OpenAI, ZhiPu, local LM Studio, etc.)

### Install

```bash
git clone <repo> && cd dekacode
pip install -r requirements.txt
cp .env.example .env   # edit with your API keys
```

### Configure

Edit `.env`:

```ini
PROVIDER=openai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com

FLASH_MODEL=deepseek-v4-flash
PRO_MODEL=deepseek-v4-pro
```

### Run

```bash
cd /your/project
python /path/to/dekacode/main.py
```

---

## Usage

### Commands

| Command | Description |
|---------|-------------|
| `/cost` | Show session token cost |
| `/stats` | Show context / graph / model stats |
| `/graph` | Show project symbol map |
| `/sessions` | List saved chat sessions |
| `/resume` | Load the most recent session |
| `/load <id>` | Load a specific session |
| `/flash` | Switch to flash model (cheap) |
| `/pro` | Switch to pro model (powerful) |
| `/mode` | Auto model selection |
| `/help` | Show all commands |
| `/exit` | Exit |

### Examples

```
 > 看一下这个项目
 > 检查 main.py 的语法错误
 > 帮我找到 handle_request 的所有调用方
 > 给 UserService 添加日志
```

---

## Architecture

```
main.py                  Entry point, main loop
├── prompt_engine.py     Builds system prompt from prompts/*.md
├── context.py           Three-zone context (prefix / history / draft)
├── skill.py             Skill base class & registry
├── router.py            Flash/Pro model routing
├── token_counter.py     Token cost tracking
├── chat_store.py        SQLite session persistence
├── status_display.py    Terminal status spinner
└── utils.py             LLM HTTP client

skills/                  Tool implementations (bash, file_ops, etc.)
code_graph/              AST call graph builder, cache, search
prompts/                 YAML-front-matter prompt fragments
```

---

## Project Structure

```
.dekacode/
├── chat.db              Conversation history (SQLite)
├── codegraph_cache.db   Call graph cache (SQLite)
└── logs/                Session JSON logs
```

---

## Prompt System

Each `.md` file in `prompts/` has YAML front matter:

```yaml
---
title: My Prompt Section
description: What this prompt does
enabled: true
order: 10
---
Content here...
```

Disabled fragments (`enabled: false`) are skipped. The `{tools}` placeholder is replaced with the live skill registry.

---

## Token Economy

| Feature | Savings |
|---------|---------|
| Fixed prefix → cache hit | Input cost ↓ 120x |
| Call graph → symbol search | Context ↓ 80%+ |
| Speculative pre-fetch | Round trips ↓ 3-4 |
| Peak-hour auto-downgrade | Cost ↓ 50% |
| RTK output filters | Tool output ↓ 60-90% |

Pricing based on DeepSeek V4: Flash ¥2/1M out, Pro ¥6/1M out (peak hours ×2).

---

## License

MIT
