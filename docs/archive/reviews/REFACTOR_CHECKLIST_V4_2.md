# 重构清单（P0 / P1 / P2）

## P0

### P0-1 统一 run 真相源到 `run_registry`
- 原因：V4.1 最大结构问题是 queue/manifest/runtime 分裂
- 收益：为 worker lease、retry、cancel、external ingest 提供统一落点
- Breaking：是

### P0-2 引入真实 worker lifecycle
- 原因：没有 leased/running/retryable/blocked/cancelled，就不算真实 runtime
- 收益：系统第一次具备可持续运行的实验内核
- Breaking：部分是

### P0-3 引入 evaluator layer
- 原因：execute 阶段不能只看“有没有结果”，必须看结果是否成立
- 收益：让 claim/result consistency、artifact integrity、evidence coverage 进入机器闭环
- Breaking：是（stage exit 变严）

### P0-4 guardrails 扩到质量与风险层
- 原因：V4.1 只拦越权，不拦坏结果、不拦高风险 shell
- 收益：更接近可接生产执行器的安全边界
- Breaking：是

### P0-5 orchestration 引入 session registry
- 原因：没有 session，难以映射 Responses/Agents 的运行语义
- 收益：handoff / response / continuation / trace 结构更真实
- Breaking：否

## P1

### P1-1 SQLite mirror 扩表
- 原因：原表结构无法查询 attempts / evaluations / sessions / traces
- 收益：调试、审计、运营视角明显变强
- Breaking：否（重建型镜像）

### P1-2 CLI 升级成 runtime 操作台
- 原因：原 CLI 更偏 demo 入口，不够像 runtime console
- 收益：支持 approve-run / cancel-run / retry-run / ingest-run-output / audit-report
- Breaking：小

### P1-3 模板与 sample 升级
- 原因：代码升级而模板不升级会制造伪复杂度
- 收益：新项目默认就是 V4.2 结构
- Breaking：否

## P2

### P2-1 evaluator registry 更插件化
- 原因：当前 evaluator 已够用，但仍偏内置
- 收益：后续更易接 benchmark / scoring / ranking
- Breaking：否

### P2-2 remote worker / external queue
- 原因：当前 worker 仍是本地单进程模型
- 收益：更贴近生产分布式执行
- Breaking：否

### P2-3 claim coverage graph
- 原因：当前 claim/evidence/result 关系仍偏 registry，而非完整图查询
- 收益：更利于 reviewer-style coverage audit
- Breaking：否
