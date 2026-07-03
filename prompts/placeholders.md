---
title: 占位符协议说明
description: 告知 LLM 可使用 [FETCH:] 占位符请求上下文
enabled: true
order: 50
---
When you need a symbol definition that is not in the current context, you can use placeholders in your response:
- [FETCH:Class:ClassName] - Request a class definition
- [FETCH:Function:func_name] - Request a function definition
- [FETCH:Method:ClassName.method] - Request a method definition
- [FETCH:Variable:var_name] - Request a variable definition

The system will automatically fetch and inject these definitions before your next turn.
