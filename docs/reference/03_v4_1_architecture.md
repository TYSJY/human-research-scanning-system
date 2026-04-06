# 03. V4.1 新架构总览

## 分层

### 1. control_plane
保存可配置、可审计、可替换的控制信息：
- `agents/`
- `workflows/`
- `schemas/`
- `prompts/`

### 2. state
保存机器真相源：
- `project.json`
- `stage_state.json`
- `task_graph.json`
- `evidence_registry.json`
- `baseline_registry.json`
- `claims.json`
- `mvp.json`
- `results_registry.json`
- `artifact_registry.json`
- `run_queue.json`
- `runtime.json`
- `figure_plan.json`

### 3. notes
保存解释层、写作层、沉淀层：
- novelty audit
- experiment plan
- title/abstract
- release checklist
- risks

### 4. runs
保存真实执行单元：
- `manifest.json`
- `request.json`
- `metrics.json`
- `stdout.log`
- `stderr.log`
- `notes.md`

### 5. logs
保存审计日志：
- `event_log.jsonl`
- `trace.jsonl`
- `guardrails.jsonl`
- `tool_calls.jsonl`
- `decisions.jsonl`

### 6. db
保存查询镜像：
- `project.db`

## 闭环

V4.1 的闭环是：

1. planner 读 `state/*`
2. 选择 agent + reasoning profile
3. provider 输出严格 action plan
4. guardrails 校验 action plan
5. actions apply 到 state / notes / tools
6. tools 触发 run / queue / result / gate 等副作用
7. executor 消费 queue 并回写 metrics / results
8. sqlite mirror 重建
9. planner 重新计算下一步

这才构成真正的 runtime。

## 为什么 Markdown 仍然保留

V4.1 没有删除 Markdown，因为它仍然有价值：
- 人可读的解释
- reviewer-style notes
- paper drafting
- checklist
- 长文沉淀

但它已经不再承担“机器真相源”。

## agent 边界

V4.1 的 agent 权限不再按目录划分，而是按：
- state_write_keys
- note_write_paths
- allowed_tools
- handoffs

这使得“谁能改什么”清楚得多。
