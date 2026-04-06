# 05. Responses API 接入说明

V4.1 提供两种 provider 模式。

## 模式一：structured
模型直接输出严格 JSON schema action plan。

适合：
- controller
- design
- writing
- audit

优点：
- 简单
- 稳定
- 容易审计

## 模式二：tool_loop
模型可以调用只读工具：
- `get_workspace_summary`
- `get_open_tasks`
- `get_registry`
- `get_run`

当信息足够时，再调用：
- `submit_action_plan`

适合：
- scan
- deep_research profile
- 需要多轮检查局部状态的 agent

## 关键原则

### 1. workspace 才是真相源
Responses conversation state 只是补充上下文，不应该取代本地 `state/*`。

### 2. tool_loop 默认只开放只读工具
真正会产生副作用的写操作仍然回到本地 `actions.apply_action_plan()` 与 `tools.py`，这样更可审计。

### 3. background 模式只是一种 provider 执行策略
它不会改变本地 state 的权威性。

## 推荐配置

- `think` -> structured / low effort
- `pro` -> structured / high effort / optional background
- `deep_research` -> tool_loop / high effort / optional background

## previous_response_id
V4.1 支持可选 continuation，但默认建议关闭。

原因：
- Research OS 的核心状态已经在本地 state
- 开启 continuation 可能引入上下文漂移
- 真正要保留的长期状态，应当显式写回 workspace
