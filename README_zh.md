# Dekacode

**极致省 Token 的终端 AI 编程助手。**

Dekacode 是一个运行在终端中的 AI 编程助手。它能理解自然语言指令，通过 LLM 工具调用（tool-calling）自动执行文件操作和 Shell 命令。所有设计决策以 **Token 效率** 为优先——最小化上下文、激进缓存、智能模型路由，让成本保持在低位。

---

## 特性

- **Tool-calling Agent** — 读写文件、执行 bash、glob 搜索、grep、抓取 URL、符号搜索、Python 语法检查
- **调用图（Call Graph）** — 基于 AST 的全项目符号索引，支持上下级调用链追踪（143 个符号索引仅需 ~0.01s）
- **Token 优先架构**
  - Append-Only 上下文 + 固定前缀 → 最大化 DeepSeek V4 前缀缓存命中（最低 ¥0.025/百万 tokens）
  - 推测性预取（Speculative Pre-fetch）：从错误输出中自动解析未定义符号并注入源码
  - `[FETCH:Class:Name]` 占位符协议：模型按需请求定义
  - RTK 输出过滤：去除 ANSI 颜色码、时间戳、UUID
- **双模型路由** — Flash（便宜）处理简单任务，Pro（强大）处理复杂任务；高峰时段自动降级
- **Rich 终端界面** — Markdown 渲染、语法高亮、实时状态动画（带计时）
- **会话持久化** — SQLite 存储聊天记录，`/resume` 一键恢复
- **提示词片段** — 模块化 system prompt，YAML 前注控制启用/禁用和顺序
- **文件监听** — 检测源码变更并增量重建调用图
- **成本可观测** — 每次调用追踪 token/缓存/花费，支持预算上限

---

## 快速开始

### 环境要求

- Python 3.12+
- OpenAI 兼容 API 端点（DeepSeek、OpenAI、智谱、本地 LM Studio 等）

### 安装

```bash
git clone <repo> && cd dekacode
pip install -r requirements.txt
cp .env.example .env   # 编辑你的 API 密钥
```

### 配置

编辑 `.env`：

```ini
PROVIDER=openai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com

FLASH_MODEL=deepseek-v4-flash
PRO_MODEL=deepseek-v4-pro
```

### 运行

```bash
cd /your/project
python /path/to/dekacode/main.py
```

---

## 使用

### 命令

| 命令 | 说明 |
|------|------|
| `/cost` | 查看会话 Token 花费 |
| `/stats` | 查看上下文 / 图 / 模型统计 |
| `/graph` | 查看项目符号地图 |
| `/sessions` | 列出已保存的会话 |
| `/resume` | 加载最近的会话 |
| `/load <id>` | 加载指定 ID 的会话 |
| `/flash` | 切换到 Flash 模型（便宜） |
| `/pro` | 切换到 Pro 模型（强大） |
| `/mode` | 自动模型选择 |
| `/help` | 显示所有命令 |
| `/exit` | 退出 |

### 示例

```
 > 看一下这个项目
 > 检查 main.py 的语法错误
 > 帮我找到 handle_request 的所有调用方
 > 给 UserService 添加日志
```

---

## 架构

```
main.py                  入口和主循环
├── prompt_engine.py     从 prompts/*.md 构建 system prompt
├── context.py           三层上下文（prefix / history / draft）
├── skill.py             Skill 基类和注册中心
├── router.py            Flash/Pro 模型路由
├── token_counter.py     Token 成本追踪
├── chat_store.py        SQLite 会话持久化
├── status_display.py    终端状态动画
└── utils.py             LLM HTTP 客户端

skills/                  工具实现（bash、文件操作等）
code_graph/              AST 调用图构建器、缓存、搜索
prompts/                 带 YAML 前注的提示词片段
```

---

## 项目文件

```
.dekacode/
├── chat.db              聊天记录（SQLite）
├── codegraph_cache.db   调用图缓存（SQLite）
└── logs/                会话 JSON 日志
```

---

## 提示词系统

`prompts/` 下的每个 `.md` 文件都包含 YAML 前注：

```yaml
---
title: 我的提示片段
description: 这个提示的作用
enabled: true
order: 10
---
内容...
```

禁用（`enabled: false`）的片段会被跳过。`{tools}` 占位符在运行时替换为技能列表。

---

## Token 经济

| 特性 | 节省 |
|------|------|
| 固定前缀 → 缓存命中 | 输入成本 ↓ 120x |
| 调用图 → 符号搜索 | 上下文 ↓ 80%+ |
| 推测性预取 | 往返次数 ↓ 3-4 |
| 高峰自动降级 | 成本 ↓ 50% |
| RTK 输出过滤 | 工具输出 ↓ 60-90% |

基于 DeepSeek V4 定价：Flash ¥2/百万输出，Pro ¥6/百万输出（高峰 ×2）。

---

## 许可

MIT
