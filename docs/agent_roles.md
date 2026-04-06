# Research Roles

控制平面的底层 agent 名称仍保持稳定，但在产品表达上，我们把它们解释为更容易理解的研究角色。

| Internal agent | Product role | Responsibility |
| --- | --- | --- |
| `controller` | Research Lead | 决定当前该推进什么、是否需要人工 gate、何时切换阶段 |
| `scan` | Literature Analyst | 补齐 evidence、baseline、novelty 风险与 reviewer objections |
| `design` | Study Designer | 收敛 claim、acceptance checks、MVP 与 experiment plan |
| `execution` | Experiment Operator | 创建 run、排队执行、回收并注册结果 |
| `writing` | Scholarly Writer | 基于已注册结果生成摘要、结构与写作骨架 |
| `audit` | Evidence Auditor | 审查交付完整度、证据覆盖、复现性和发布前缺口 |

这种命名方式更接近真实研究团队协作，也更符合“专业科研助手”的产品气质。
