---
title: 任务规划
description: 多步骤任务使用 todowrite 工具制定计划
enabled: true
order: 35
---
When you are assigned a task that requires 3+ distinct steps or actions (not including trivial tool calls), use `todowrite` to create a task plan before starting. Follow these rules:

- Create a todo list with clear, actionable items
- Mark one item `in_progress` at a time (only ONE at a time)
- Mark items `completed` as you finish them
- If the user provides a numbered or comma-separated list of tasks, capture them as todos
- Set `priority` for each item: `high`, `medium`, or `low`
- Keep todos updated — call `todowrite` after completing or changing status of any item
