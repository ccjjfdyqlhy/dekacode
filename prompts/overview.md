---
title: 项目总览协议
description: 用户要求概览项目时，检查并增量更新 .dekacode/OVERVIEW.md
enabled: true
order: 45
---
## Project Overview Protocol

When the user asks to "overview the project" / "summarize the project" / "看一下这个项目" / "整体概括项目":

1. **Check existing**: Use `read_file` to check if `.dekacode/OVERVIEW.md` exists.
   - If reading fails (file not found): do a full exploration (step 2).
   - If reading succeeds: read the file, identify which sections need updates based on the user's specific question, then make targeted edits with `write_file`.
2. **Full exploration**: Explore the project structure (glob, read key files), then write a comprehensive OVERVIEW.md with:
   - Project purpose / architecture
   - Key modules and their responsibilities
   - Tech stack
   - Entry points
3. **Update only**: When updating, keep the existing structure and only modify/add the sections that changed. Do not rewrite the entire file unless the user explicitly asks.
4. **Location**: Always write to `.dekacode/OVERVIEW.md`.
