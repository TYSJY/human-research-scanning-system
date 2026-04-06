# 迁移说明 V4.2

## 一、V4.1 → V4.2

### 命令
```bash
ros upgrade-v4_1 path/to/v4_1_project --output path/to/v4_2_project
```

### 会发生什么
- 保留原项目内容
- 新增 / 补齐：
  - `state/run_registry.json`
  - `state/evaluation_registry.json`
  - `state/session_registry.json`
  - `reports/`
- 从 legacy `state/run_queue.json + runs/*` 自动回填 `run_registry`
- 规范化 claims / runtime / run metadata
- 尝试为成功 run 回填 evaluator 记录
- 重建 SQLite mirror

### 注意
- `state/run_queue.json` 仍可保留，但不再是真相源
- execute → write 的退出条件变严；旧项目可能会因为 evaluator fail 停在 execute/audit
- 旧 claims 若没有 acceptance checks，会被补默认结构，但建议人工收紧

## 二、V3 → V4.2

### 命令
```bash
ros migrate-v3 path/to/v3_project --output path/to/v4_2_project
```

### 会迁移什么
- evidence / baseline / claims / mvp / results / artifacts / figure plan
- backlog → task_graph
- notes → `notes/*.md`
- legacy run manifest / metrics → `runs/*`
- workflow summary → runtime 字段
- trace → `logs/trace.jsonl`

### 不会自动解决什么
- 旧 run 的真实 executor 语义
- claims 的严格 acceptance checks
- 外部 runner 的真实绑定
- 旧项目中的占位字段与人工 gate 决策

## 三、推荐的迁移后检查
```bash
ros validate     path/to/v4_2_project
ros audit-report path/to/v4_2_project
ros sync-sqlite  path/to/v4_2_project
```
