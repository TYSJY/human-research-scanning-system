# 07. 与 Agents SDK 的对齐关系

V4.1 的本地 runtime 已经和 Agents SDK 的核心概念基本对齐：

- controller / specialist -> agents
- recommended agent -> handoff 目标
- action plan guardrails -> input/output/tool guardrails
- logs/trace -> tracing
- runtime previous_response_id -> session / continuation strategy

## 为什么这次没有直接把整个 runtime 改成 Agents SDK

因为当前最重要的是：
1. 先把本地 workspace 真相源压实
2. 先把 run/runtime/guardrail 做对
3. 再把 SDK 当成 runtime shell 引入

否则会变成“把一个不稳定的状态模型，搬进一个更花哨的执行壳”。

## 最合理的迁移方式

### 第一层：保持本地 workspace
继续用本地 `state/*` 做权威状态。

### 第二层：用 Agents SDK 托管 runtime
把 controller 与 specialist 定义成 SDK agents，用 handoff + tracing + guardrails 跑。

### 第三层：保留本地 tools
真正写状态、排队实验、回写结果，仍走本地 `tools.py`。

这样可以兼得：
- SDK tracing / handoff / guardrails
- 本地可审计状态
- 不依赖远端 conversation 作为唯一真相源
