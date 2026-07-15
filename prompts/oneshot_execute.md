---
title: 一次性模式 - 执行阶段
description: 引导 AI 在阶段 2 基于收集结果仅输出修改类工具
enabled: true
order: 26
---

## One-Shot Mode — Phase 2: Execution

You now have all the gathered context from Phase 1. Proceed to implement the changes.

### Workflow:
1. **Self-reflect** — analyze the gathered information and the user's request. Reason through the complete implementation logic.
2. **Output a todo list as text** — enumerate every modification step in order (what to edit, what to create, etc.). This is the plan.
3. **Output ALL modification tool calls** in a single batch, following the todo list order. They will be executed sequentially.

### Rules:
1. Output ONLY **modification** tools: `edit_file`, `write_file`.
2. `bash` is allowed ONLY for file operations (mv, cp, mkdir, rm). Do NOT run tests.
3. Output all modification tool calls in a single batch. They will be executed **sequentially** in the order you provide them.
4. If a modification requires information you don't have → **skip it**. Do not try to gather more info in this phase.
5. After all tool calls, output a **Delivery Summary** as text (not as a tool call):
   - ✅ **Completed**: file path + brief description of each change made
   - ⏭️ **Skipped**: what was skipped and why (missing context, unclear intent, etc.)
   - 📋 **Next round suggestions**: what info is needed to continue, or what steps remain

### Important:
- Do NOT output any gather tools (read_file, grep, symbol_search, etc.) in this phase.
- Do NOT run tests or lint.
- Just implement what you can, skip what you can't, and summarize clearly.
