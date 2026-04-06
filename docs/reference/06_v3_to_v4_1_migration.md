# 06. V3 -> V4.1 迁移说明

## 迁移原则

- 保留 V3 的研究内容与 notes
- 删除 V3 的状态分裂
- 把 V3 的 backlog 迁入新的 task graph
- 把 V3 的 run 迁入新的 run layout
- 把 Markdown 降级为 notes，而不是状态源

## 映射

### 管理层
- `00_admin/project_manifest.json` -> `state/project.json`
- `00_admin/workflow_state.json` -> `state/stage_state.json` + `state/runtime.json`
- `00_admin/backlog.json` -> `state/task_graph.json`
- `00_admin/human_gates.json` -> `state/stage_state.json.gates`

### 扫描 / 设计 / 结果
- `01_scan/evidence_registry.json` -> `state/evidence_registry.json`
- `01_scan/baseline_registry.json` -> `state/baseline_registry.json`
- `02_design/claim_graph.json` -> `state/claims.json`
- `02_design/mvp_definition.json` -> `state/mvp.json`
- `04_results/results_registry.json` -> `state/results_registry.json`
- `06_artifacts/artifact_registry.json` -> `state/artifact_registry.json`
- `05_paper/figure_plan.json` -> `state/figure_plan.json`

### 文档
- 原有 Markdown 被迁入 `notes/`

### run
- `03_runs/<run>/run_manifest.json` -> `runs/<run>/manifest.json`
- `03_runs/<run>/metrics.json` -> `runs/<run>/metrics.json`
- 如果 V3 没有 request contract，则生成 `executor = manual` 的 `request.json`

## 迁移命令
```bash
ros migrate-v3 path/to/v3_project --output path/to/v4_1_project
```

## 迁移后的第一步建议
1. 跑 `ros validate`
2. 看 `ros plan`
3. 补全每个 run 的 `request.json`
4. 再决定是否接 shell executor 或外部 runner
