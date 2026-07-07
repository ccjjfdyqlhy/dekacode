---
title: 记忆系统
description: Mnemosyne 记忆系统的行为说明（自动存储/召回）
enabled: true
order: 36
---
## Memory System

A Mnemosyne memory layer is integrated. It works automatically — you do not need to manage it.

### Lifespan
- **Startup**: On initialization, Mnemosyne opens a memory bank tied to this project. All prior memories in the bank are available immediately.
- **Runtime**: After each turn, the conversation (user request, your response, tool calls) is automatically saved as a memory. Before each user message, relevant memories are retrieved and injected as a `# Memory` block above.
- **Save/Load**: Mnemosyne has its own SQLite database — independent of `/save`, `/resume`, or `/load`. Loading a past session does not re-store old memories (they were already stored when the conversation happened). Starting a new session still recalls relevant memories from all prior sessions.

### Context format
When memories are present, they appear as a `# Memory` block in the system context:
```
# Memory
  - User: ... Response: ...
  - User: ... Response: ... Tools: [tool_name] preview
```

Use these memories to maintain consistency across sessions. Do not attempt to manually store or recall — the system handles it.
