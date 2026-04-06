# 02. 重构点清单（按优先级排序）

## P0：必须重做，否则系统仍然只是“像 orchestrator”

### P0-1. 统一状态源
**动作**
- 所有机器真相源统一进 `state/*.json`

**原因**
- 去掉 manifest / workflow / backlog / agent_memory 之间的漂移

### P0-2. 把 backlog 升级成 task graph
**动作**
- 新增 `state/task_graph.json`
- 引入 blueprint task + closure rule + depends_on + requires_gate

**原因**
- 真正让 planner 能根据任务闭包驱动阶段推进

### P0-3. 把 execute 变成真实 runtime
**动作**
- 新增 `runs/*/request.json`
- 新增 `state/run_queue.json`
- 新增 shell/manual executor
- 新增 metrics -> results 回写

**原因**
- 没有真实执行器，就没有真实 execute 阶段

### P0-4. 给 action plan 加 guardrails
**动作**
- 严格检查 state write、note write、tool call、stage transition、result provenance

**原因**
- 多 agent 系统如果没有 guardrails，后面会不可维护

## P1：必须补齐，否则系统不够专业

### P1-1. 把 reasoning profile 做成调度策略
- think：快、浅、低成本、适合 routine
- pro：高判断、高 gate 敏感
- deep_research：允许 tool loop、适合证据扩展

### P1-2. 把 Responses API 接成真实 provider
- structured mode
- tool_loop mode
- background polling
- optional previous_response_id continuation

### P1-3. 增加 observability
- event_log
- trace
- tool_calls
- guardrails
- decisions
- sqlite mirror

## P2：下一阶段扩展点

### P2-1. worker / queue service
把当前本地 executor 升级为独立 worker。

### P2-2. claim/result consistency checks
自动审计 claim 是否真的被 result 覆盖。

### P2-3. Agents SDK runtime
在不改变 workspace 真相源的前提下，把 controller / handoff / tracing / guardrails 迁到 Agents SDK 壳层。

## 本次 V4.1 已实施的点

- [x] 统一状态层
- [x] task graph
- [x] run queue
- [x] shell/manual executor
- [x] Responses provider
- [x] guardrails
- [x] SQLite mirror
- [x] migration
- [x] migrated sample project
