# Dekacode

**极致省 Token 的终端 AI 编程助手。**

Dekacode 运行在终端中，作为 AI 软件工程助手。它能理解自然语言指令，通过 LLM 工具调用自动执行文件操作、Shell 命令、代码分析和符号导航。所有架构决策以 **Token 效率** 为优先：最小化上下文、激进缓存、推测性预取、智能模型路由。

---

## 特性

- **Tool-calling Agent** — 读写文件、执行 bash、glob 搜索、grep、抓取 URL、符号搜索、Python 语法检查、diff 文件等
- **AST 调用图** — 全项目符号索引，支持上下级调用链追踪；140+ 符号索引仅需 ~0.01s
- **Token 优先架构**
  - Append-Only 上下文 + 固定前缀 → 最大化 DeepSeek V4 前缀缓存命中（最低 ¥0.025/百万 tokens）
  - 推测性预取（Speculative Pre-fetch）：从错误输出中自动解析未定义符号并注入源码
  - `[FETCH:Class:Name]` 占位符协议：模型按需请求符号定义
  - RTK 输出过滤：去除 ANSI 颜色码、时间戳、UUID（工具输出减少 60–90%）
- **双模型路由** — Flash（便宜）处理简单任务，Pro（强大）处理复杂任务；高峰时段自动降级
- **Rich 终端界面** — Markdown 渲染、语法高亮、实时状态动画（含进度条和计时）
- **会话持久化** — SQLite 存储聊天记录，`/resume` 一键恢复
- **模块化提示词** — YAML 前注片段（`enabled: true/false`、`order:`），灵活组合 system prompt
- **文件监听** — 检测源码变更并增量重建调用图
- **成本可观测** — 每次调用追踪 token/缓存/花费，支持会话预算上限
- **耗时预测器** — 基于 OLS 的请求延迟预测，优化进度显示
- **缓存保活** — 空闲时发送 keepalive 请求，防止服务端前缀缓存过期
- **Provider 无关** — 兼容任意 OpenAI 兼容 API：DeepSeek、OpenAI、智谱、LM Studio（本地）等

---

## 快速开始

### 环境要求

- Python 3.12+
- OpenAI 兼容 API 端点

### 安装

```bash
git clone https://github.com/your-org/dekacode.git && cd dekacode
pip install -r requirements.txt
cp .env.example .env   # 编辑你的 API 密钥
```

### 配置

```ini
PROVIDER=openai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com

FLASH_MODEL=deepseek-chat
PRO_MODEL=deepseek-reasoner
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
| `/cost` | 查看会话 Token 和花费汇总 |
| `/stats` | 查看上下文 / 调用图 / 模型统计 |
| `/prompts` | 列出启用/禁用的提示词片段 |
| `/graph` | 查看项目符号地图 |
| `/sessions` | 列出已保存的会话 |
| `/resume` | 加载最近的会话 |
| `/save` | 立即保存当前会话 |
| `/load <id>` | 加载指定 ID 的会话 |
| `/retry` | 重试上一次输入 |
| `/undo` | 撤销上一轮 |
| `/flash` | 切换到 Flash 模型（便宜） |
| `/pro` | 切换到 Pro 模型（强大） |
| `/mode` | 自动模型选择 |
| `/help` | 显示所有命令 |
| `/exit` | 退出 |

### 示例

```
 > 看一下这个项目
 > 检查 main.py 的语法错误
 > 找到 handle_request 的所有调用方
 > 给 UserService 添加日志
```

---

## 架构

```
main.py                     入口：主循环、命令分发、工具执行
├── prompt_engine.py        从 prompts/*.md 片段构建 system prompt
├── context.py              三层上下文（prefix / history / draft）
│   └── SpeculativePrefetcher  从错误输出自动解析未定义符号
├── skill.py                Skill 基类、注册中心、工具定义生成
├── router.py               Flash/Pro 模型选择，高峰时段感知
├── token_counter.py        Token 和花费追踪（缓存命中/未命中、高峰倍率）
├── predictor.py            基于 OLS 的请求耗时预测
├── cache_warmer.py         保活请求维持前缀缓存
├── chat_store.py           SQLite 会话持久化（消息、用量、预测器状态）
├── session_logger.py       详细 JSON 请求/响应日志
├── status_display.py       富终端状态动画（含进度条）
├── config.py               Pydantic-settings 配置（.env）
├── models.py               数据模型：Message、ToolCall、Function 等
└── utils.py                LLM HTTP 客户端，含重试逻辑

skills/                     工具实现
├── bash.py                  Shell 命令执行
├── file_ops.py              读写/编辑/glob/grep/列出文件
├── git_ops.py               Git diff
├── symbol_search.py         符号搜索、调用者查询、读取符号源码
├── py_check.py              Python 语法检查和 AST 摘要
├── web_fetch.py             URL 内容抓取
└── filters.py               RTK 输出过滤（ANSI、时间戳、UUID 去除）

code_graph/                  AST 调用图
├── builder.py               扫描项目，从 AST 构建符号索引
├── symbol.py                Symbol 和 CallGraph 数据结构
├── cache.py                 SQLite 图缓存，带过时检测
├── search.py                符号搜索、调用者/被调用者链遍历
├── watcher.py               文件变更监控
├── placeholders.py          [FETCH:] 占位符解析器
└── imports.py               Import -> 文件路径解析

prompts/                     YAML 前注提示词片段
├── system.md                Code Agent 身份定义
├── tools.md                 工具列表（运行时注入）
├── rules.md                 行为约束
├── jianyan.md               极度精简语言模式
├── overview.md              项目总览协议
├── placeholders.md          [FETCH:] 协议说明
└── terse.md                 Token 节省提示（默认禁用）
```

### 数据流

```
用户输入 → ContextManager（追加到历史）
  → LLMClient.chat()（system + prefix + history + draft）
    → 模型响应（文字 | tool_calls）
      → 工具调用 → SkillRegistry.execute()
        → 结果 → ContextManager（追加到 draft）
          → 循环直到 stop
```

---

## Token 经济

| 优化手段 | 节省效果 |
|---|---|
| 固定前缀 → 缓存命中 | 输入成本 ↓ 120x |
| 调用图 → 符号搜索 | 上下文 ↓ 80%+ |
| 推测性预取 | 往返次数 ↓ 3–4 |
| 高峰自动降级 | 成本 ↓ 50% |
| RTK 输出过滤 | 工具输出 ↓ 60–90% |
| 耗时预测器 → 准确 ETA | 更好的体验 |

定价参考（DeepSeek V4）：Flash ¥2/百万输出，Pro ¥6/百万输出（高峰 ×2）。

---

## 项目文件

```
.dekacode/
├── chat.db              聊天记录（SQLite）
├── codegraph_cache.db   调用图缓存（SQLite）
└── logs/                会话 JSON 日志
```

---

## 许可

MIT
