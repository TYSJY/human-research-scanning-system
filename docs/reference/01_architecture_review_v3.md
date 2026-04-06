# 01. V3 架构评审报告

## 总评

V3 的方向是对的，但成熟度被目录和文档放大了。

它真正完成的是：
- 从 prompt 仓库迈向了 agent/runtime 思路
- 开始有 stage machine、human gate、reasoning profile
- 已经意识到 Markdown 不应该是唯一真相源

它没有真正完成的是：
- 统一状态层
- 真实 task graph
- 真实 run runtime
- 真实 tool contract
- 真实 trace / audit / guardrail
- 真实 provider integration

所以 V3 更准确的定位不是“成熟 orchestrator”，而是：

> 一个已经长出控制平面意识、但仍停留在半编排状态的 Research OS 原型。

## V3 的强项

### 1. 阶段主线是对的
`scan -> design -> execute -> write -> audit` 是论文驱动研究的正确大骨架。

### 2. 角色拆分比纯 prompt 库更进一步
controller / scan / design / execution / writing / audit 的职责方向基本合理。

### 3. 已经开始考虑 real system concerns
包括：
- human gate
- trace
- SQLite export
- provider 抽象
- sample project

这些都说明 V3 不是单纯 prompt 仓库。

## V3 的结构性问题

### P0-1. 状态源仍然分裂
V3 同时存在：
- `project_manifest.json`
- `workflow_state.json`
- `backlog.json`
- `human_gates.json`
- `07_agent/last_action.json`
- `07_agent/agent_memory.json`

这会带来：
- 同一个事实被多处复制
- stage 漂移
- “看起来完成”和“机器上完成”不一致
- 编排器无法回答“现在到底该做什么”

### P0-2. backlog 不是 task graph
V3 的 `backlog.json` 仍然是弱列表，不是能驱动真实闭环的 task graph。
它缺少：
- stage 映射
- closure rule
- 依赖闭包
- gate 依赖
- 输出约束
- 任务自动收敛逻辑

### P0-3. execution 仍然偏文档化
V3 有 run 目录，但缺少真正的 execution runtime：
- 没有 queue
- 没有 request contract
- 没有 executor
- 没有从 metrics 自动回写 result 的机制

所以 execute 阶段还停留在“实验计划的文件夹化”，没有完成“运行时化”。

### P0-4. orchestration 还偏假编排
V3 的 orchestration 更像：
- rule-based route
- provider scaffold
- action apply

但还不是：
- task-driven runtime
- provider/tool loop
- guarded write pipeline
- traceable workflow engine

### P1-1. agent 权限是目录前缀，不是资源 contract
V3 的 agent 权限更像“能写哪个目录”，而不是：
- 能写哪些 state keys
- 能写哪些 note paths
- 能调用哪些 tools
- 哪些动作必须被 gate/guardrail 拦住

### P1-2. reasoning profiles 还像标签
V3 已经提出 think / pro / deep_research，但它们还没有真正进入：
- provider 模式
- reasoning budget
- background 策略
- tool usage policy
- human review bias

### P1-3. observability 不够
V3 有 trace，但无法系统回答：
- 哪个 agent 在什么时候动了哪个 state
- 哪次工具调用被 guardrail 拦截
- 哪个阶段是怎么推进的
- 为什么这个 run 被排队、被失败、被回写

## V3 中“看起来高级”的部分

以下内容方向对，但在 V3 里更多是“架势”，不是完整 runtime：
- reasoning profiles
- provider abstraction
- agent spec
- SQLite export
- orchestration trace

问题不在于这些概念错，而在于没有被压实成**系统闭环**。

## 对 V3 的结论

V3 值得保留的核心思想：
- Research OS 方向
- 多 agent 分工
- stage machine
- human gate
- 保守写作与审计意识

V3 不值得继续保留的核心结构：
- 分裂状态源
- 弱 backlog
- 目录式权限
- 文档化 execution
- 伪编排 runtime
