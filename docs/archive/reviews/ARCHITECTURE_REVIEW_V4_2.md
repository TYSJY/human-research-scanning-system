# 架构评审报告 V4.2

## 一、当前系统状态判断

### 它已经是什么
V4.1 的起点并不是 demo prompt 仓库，而是一个已经具备正确骨架的内核：
- 有结构化 state，而非纯 Markdown
- 有 task graph / stage machine / reasoning profiles
- 有 controller + specialist agent 的基础编排
- 有 action plan schema + tool abstraction
- 有 shell/manual executor
- 有 event / trace / guardrails / decision log
- 有 SQLite mirror
- 有 V3 → V4.1 migration
- 能走通最小闭环：规划 → 入队 → 执行 → 回写 → 审计

### 它还不是什么
它仍然不是：
- 生产级自动科研系统
- 大规模多 worker 平台
- 完整 evaluator-driven research engine
- 完整成熟的 Agents SDK/Responses 原生 runtime
- 强一致性的科研质量控制平面

### 本轮判断
因此本轮不应该“再发明一个新壳子”，而应该：
- 保留 task/stage/gate/state 的骨架
- 重写 runtime / queue / executor / evaluator / session 关键链路
- 删除或降级 run_queue 这种 V4.1 遗留分裂状态

## 二、强项

### 1. 信息架构方向是对的
`state / notes / logs / runs / db` 的分层是健康的。Markdown 已经被降到 presentation layer，这一点必须保留。

### 2. task graph + stage machine 不是装饰
planner 已经能根据 stage exit、gate、任务状态来选择 agent/profile，这说明系统不是完全“prompt 硬跳转”。

### 3. provider / action plan / guardrails / tools 这条链是正确的
这条链虽然在 V4.1 还偏轻，但方向是对的，值得继续升级，而不是推倒重来。

### 4. SQLite mirror 很有价值
JSON 作为真相源、SQLite 作为查询镜像，这个分工比直接让 SQLite 成为写路径更适合当前阶段。

## 三、V4.1 的结构性瓶颈

### 1. run lifecycle 分裂
V4.1 的 run 真相源分散在：
- `state/run_queue.json`
- `runs/*/manifest.json`
- 执行器内存状态

导致：
- 无法表达 lease / retryable / blocked / cancelled
- 无法可靠支持 cancel / resume / external ingest
- queue status 与 manifest status 容易漂移

### 2. executor 更像顺序消费器，不像真实 worker
V4.1 没有 lease TTL、heartbeat、reaper、retry policy、approval gate 和 external completion 回灌，所以它更像 demo executor。

### 3. guardrails 只到权限层，没有到质量层
V4.1 guardrails 能拦住越权写入，但拦不住：
- claim 与 result 不匹配
- evidence coverage 不足
- output/artifact 不完整
- 高风险 shell 行为
- evaluation fail 后仍强写 paper notes

### 4. reasoning profiles 参与度不够深
V4.1 有 profile，但它更多影响 provider 参数，没有在 runtime / handoff / backlog triage 中形成强闭环。

### 5. orchestration 缺 session/handoff registry
没有 session 这一层，就难以把 Responses API / Agents SDK 的 response/thread/session/handoff 正确映射到本地运行时。

## 四、应该保留、重写、删除什么

### 保留
- `state/*.json` 作为真相源
- `task_graph + stage_machine + gates`
- `action_plan + tools + guardrails` 链路
- `logs/*.jsonl` 与 SQLite mirror
- `mock + openai provider` 双实现

### 重写
- run lifecycle / worker runtime
- SQLite schema
- validation
- migration
- provider tool loop 的 runtime mapping
- sample project

### 删除或降级
- `run_queue` 的 canonical 地位
- 只看 `manifest.status` 的 run 状态判断
- 无 evaluator 的 execute → write 推进逻辑
- 旧 sample 作为主 sample 的地位

## 五、V4.2 的重构判断

### 本轮最重要的升级是成功的
V4.2 把系统推进到更像真实运行内核的状态：
- runtime 真相源统一
- run lifecycle 完整
- worker/lease/retry/timeout/cancel/resume 可表达
- evaluator/guardrails/human gate 接进闭环
- session/trace 与 Responses runtime 更可映射

### 仍需后续迭代的部分
- 分布式 worker / remote queue
- evaluator 插件化与评分策略
- claim coverage graph 的更强图结构
- hosted tools / file search / external providers 的原生桥接
- 强一致性的 state transactions
