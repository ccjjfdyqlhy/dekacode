<p align="center">
  <img src="dekacode.png" alt="Dekacode" width="480">
</p>

**极致省 Token 的终端 AI 编程助手 — 还有 Web 界面。**

Dekacode 运行在终端或浏览器中，作为 AI 软件工程助手。它能理解自然语言指令，通过 LLM 工具调用自动执行文件操作、Shell 命令、代码分析和符号导航。

所有架构决策以 **Token 效率** 为优先：最小化上下文、激进缓存、推测性预取、智能模型路由。

---

## 特性

### 核心引擎
- **Tool-calling Agent** — 20+ 内置工具：读写文件、执行 bash、glob 搜索、grep、抓取 URL、符号搜索、Python 语法检查、diff 文件、编辑代码等
- **AST 调用图** — 全项目符号索引，支持上下级调用链追踪；140+ 符号索引仅需 ~0.01s
- **Agent / One-Shot 双模式** — 交互式多轮 Agent 或基于 @ 指令的一次性执行（`@req`、`@sym`、`@grep`、`@ls`、`@tree`）
- **双模型路由** — Flash（便宜）处理简单任务，Pro（强大）处理复杂任务；高峰时段自动降级
- **扩展分析工具集** — 批量执行、符号定位、代码诊断、项目摘要、依赖映射、快照、增量 Git 分析

### Token 优先架构
- **Append-Only 上下文 + 固定前缀** — 最大化 DeepSeek V4 前缀缓存命中（最低 ¥0.025/百万 tokens）
- **推测性预取（Speculative Pre-fetch）** — 从错误输出中自动解析未定义符号并注入源码
- **`[FETCH:Class:Name]` 占位符协议** — 模型按需请求符号定义
- **RTK 输出过滤** — 去除 ANSI 颜色码、时间戳、UUID（工具输出减少 60–90%）

### 用户界面
- **Rich 终端界面** — Markdown 渲染、语法高亮、实时状态动画（含进度条和计时）
- **Web UI** — FastAPI 网页界面（端口 8080）：
  - 可折叠侧栏，支持会话管理
  - 实时执行面板，动态显示工具进度
  - 消息内思考详情，记录每个工具调用的状态和参数
  - 模型切换器（Flash / Pro / OpenAI），显示底层 API 模型名
  - 模式滑杆（Agent / OneShot）
  - 浮动毛玻璃输入框，带发送和模型切换按钮
  - 每次 AI 回复后展示 Token/费用/耗时摘要
  - 会话持久化，刷新不丢聊天记录

### 基础设施
- **会话持久化** — SQLite 存储聊天记录；浏览器端会话刷新不丢失
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

依赖项：`pydantic>=2.0`、`pydantic-settings>=2.0`、`httpx>=0.27`、`prompt_toolkit>=3.0`、`rich>=13.0`、`fastapi>=0.100`、`uvicorn>=0.20`

### 配置

```ini
PROVIDER=openai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.deepseek.com

FLASH_MODEL=deepseek-v4-flash
PRO_MODEL=deepseek-v4-pro
```

完整配置选项见 `.env.example`（双 API 密钥、Provider 切换、会话限额等）。

### 运行

```bash
cd /your/project
python /path/to/dekacode/main.py          # 终端界面
python /path/to/dekacode/main.py --web    # Web 界面 → http://localhost:8080
```

---

## Web 界面

使用 `--web` 参数启动后会提供完整的浏览器聊天界面：

- **侧栏** — 可折叠，包含会话列表、模式/模型信息、设置选项
- **聊天区** — 居中消息面板，支持 Markdown 渲染（表格、代码块、标题、列表、分隔线），每条 AI 回复附带 Token/费用/耗时摘要
- **执行面板** — 输入框上方浮动毛玻璃面板，实时显示工具进度（旋转图标 + 状态文字 + 计时）
- **思考详情** — 消息内可折叠区域，记录每个工具调用的状态图标和参数详情
- **输入框** — 浮动毛玻璃文本域：
  - `Enter` 发送，`Ctrl+Enter` 换行
  - 模型选择按钮（显示当前模式+模型，如 "Agent Flash"）
  - 弹出面板包含模式滑杆（Agent / OneShot / anaii 锁定）和模型列表（显示底层 API 模型名）
- **会话管理** — 本地存储聊天记录，刷新页面自动恢复，新建会话不丢失历史

### API 端点

| 路径 | 说明 |
|------|------|
| `/ws` | WebSocket 聊天消息、工具调用、模式切换 |
| `/api/status` | 当前模型、项目路径、符号/文件数 |
| `/api/models` | 可用模型列表及选中状态 |
| `/api/commands` | 斜杠命令列表 |
| `/api/balance` | 账户余额（如 API 支持） |

---

## 终端命令

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
| `/mode` | 切换 Agent / OneShot 模式 |
| `/help` | 显示所有命令 |
| `/exit` | 退出 |

### 使用示例

```
 > 看一下这个项目
 > 检查 main.py 的语法错误
 > 找到 handle_request 的所有调用方
 > 给 UserService 添加日志
 > 总结最近 5 次提交的变更
 > 生成模块依赖关系图
```

---

## 架构

```
main.py                     入口：主循环、命令分发、工具执行
├── prompt_engine.py        从 prompts/*.md 片段构建 system prompt
├── context.py              三层上下文（prefix / history / draft）
│   └── SpeculativePrefetcher  从错误输出自动解析未定义符号
├── context_gatherer.py     One-Shot 模式下通过 @ 指令收集上下文
├── skill.py                Skill 基类、注册中心、工具定义生成
├── router.py               Flash/Pro 模型选择，高峰时段感知
├── token_counter.py        Token 和花费追踪（缓存命中/未命中、高峰倍率）
├── predictor.py            基于 OLS 的请求耗时预测
├── cache_warmer.py         保活请求维持前缀缓存
├── chat_store.py           SQLite 会话持久化（消息、用量、预测器状态）
├── session_logger.py       详细 JSON 请求/响应日志
├── status_display.py       富终端状态动画（含进度条）
├── modes.py                Agent / OneShot 模式状态机
├── config.py               Pydantic-settings 配置（.env）
├── models.py               数据模型：Message、ToolCall、Function 等
├── utils.py                LLM HTTP 客户端，含重试逻辑
└── webui/                  FastAPI 网页界面
    ├── server.py           WebSocket 通信、REST API、静态文件
    └── static/             前端资源（HTML、JS、CSS、logo）

skills/                     工具实现
├── bash.py                  Shell 命令执行
├── file_ops.py              读写/编辑/glob/grep/列出文件
├── git_ops.py               Git diff
├── symbol_search.py         符号搜索、调用者查询、读取符号源码
├── py_check.py              Python 语法检查和 AST 摘要
├── web_fetch.py             URL 内容抓取
├── filters.py               RTK 输出过滤（ANSI、时间戳、UUID 去除）
├── dekacode.py              中枢 Skill — 整合核心 + 项目分析模块
├── core/                    核心分析工具
│   ├── batch.py             批量 bash 和符号搜索
│   ├── cache.py             文件/结果缓存
│   ├── chunk.py             语义分块读文件 & 智能 grep
│   ├── locator.py           查找定义、查找引用、全量符号
│   └── diagnose.py          错误诊断、导入问题检测
└── project/                 项目级分析
    ├── incremental.py       Git diff 行、文件变更、增量变更图
    ├── summary.py           文件/项目/会话摘要
    └── snapshot.py          关键文件识别、模块依赖图、项目快照

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
├── oneshot_gather.md        One-Shot 收集阶段提示词
├── oneshot_execute.md       One-Shot 执行阶段提示词
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

## 运行时目录

```
.dekacode/
├── chat.db              聊天记录（SQLite）
├── codegraph_cache.db   调用图缓存（SQLite）
└── logs/                会话 JSON 日志
```

---

## 许可

MIT
