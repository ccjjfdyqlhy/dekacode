---
title: 运行规则
description: Agent 的行为约束
enabled: true
order: 30
---
Rules:
1. When you need to use a tool, respond with a tool call (not text).
2. After receiving tool results, analyze them and decide the next step.
3. When you have the final answer, respond in text with a clear summary.
4. Prefer absolute paths for file operations.
5. Be thorough — explore the codebase before making changes.
6. Each time you call a tool, include a brief description (≤20 tokens) in the content field alongside the tool_calls, explaining what you are currently doing. This description will be displayed in the status line instead of a progress bar.
