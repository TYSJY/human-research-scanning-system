# B线 · 实验

论文 → 代码 → 预跑 → 优化 → 真实实验 → 结果回写。

## 默认步骤

- 1. 根据论文生成代码 -> `experiments/codegen`
- 2. AI 预跑与排错 -> `experiments/preflight`
- 3. 继续优化实验 -> `experiments/results`
- 4. 检查还有无优化空间 -> `experiments/results`
- 5. 跑通并稳定 -> `experiments/results`
- 6. 本地服务器真实实验 -> `experiments/server_runs`
- 7. 结果写回论文 -> `experiments/results`
