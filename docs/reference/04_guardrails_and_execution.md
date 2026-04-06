# 04. Guardrails 与真实执行器

## Guardrails 现在拦什么

### 1. state write guardrails
检查 agent 是否有权写对应的 `state_key`。

### 2. note write guardrails
检查 agent 是否有权写对应 note path。

### 3. tool guardrails
检查：
- 工具是否属于该 agent
- 参数是否齐全
- 是否引用了不存在的 run / claim / gate
- result 是否带 provenance
- create_run / queue_run 是否突破预算

### 4. stage transition guardrails
只有在以下条件都满足时，才允许 `transition_stage`：
- 当前 stage exit rules 满足
- required gates 全部批准
- target stage 恰好是 stage machine 指定的 next stage

### 5. paper grounding guardrails
没有注册结果时，禁止写 title/abstract 与 outline 的正式稿。

## experiment executor

### run contract
每个 run 都由两部分组成：

#### manifest.json
表示这个 run 是什么。

#### request.json
表示这个 run 怎么执行。

这样就把“研究设计”和“执行请求”分开了。

## 支持的 executor

### manual
表示：
- 这个 run 仍要由人或外部系统执行
- 系统只跟踪状态，不执行命令

### shell
表示：
- 本地可以直接执行命令
- stdout / stderr / metrics 将被记录
- 可以自动回写 results_registry

## metrics -> results

`request.json` 可以声明 `register_results`：
- 从 `metrics.json` 抽取 value_path
- 生成结构化 result
- 自动写回 `state/results_registry.json`

这样 execute 和 write 才真的接起来。
