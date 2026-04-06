# 变更摘要 V4.2

## 一、改了哪些文件

### 运行时核心
- `research_os/workspace.py`
- `research_os/planner.py`
- `research_os/tools.py`
- `research_os/guardrails.py`
- `research_os/evaluators.py`
- `research_os/executors.py`
- `research_os/actions.py`
- `research_os/providers.py`
- `research_os/orchestrator.py`
- `research_os/validation.py`
- `research_os/sqlite_sync.py`
- `research_os/migrate.py`
- `research_os/bootstrap.py`
- `research_os/cli.py`
- `research_os/agents_sdk_bridge.py`
- `research_os/__init__.py`

### 控制面 / 数据契约
- `control_plane/workflows/stage_machine.json`
- `control_plane/workflows/task_blueprints.json`
- `control_plane/workflows/reasoning_profiles.json`
- `control_plane/workflows/guardrail_policy.json`
- `control_plane/workflows/tool_registry.json`
- `control_plane/workflows/runtime_policy.json`（新增）
- `control_plane/workflows/evaluator_registry.json`（新增）
- `control_plane/agents/*.json`
- `control_plane/schemas/action_plan.schema.json`
- `control_plane/schemas/run_manifest.schema.json`
- `control_plane/schemas/project.schema.json`
- `control_plane/schemas/task.schema.json`
- `control_plane/schemas/run_request.schema.json`（新增）
- `control_plane/schemas/run_registry.schema.json`（新增）
- `control_plane/schemas/evaluation_registry.schema.json`（新增）
- `control_plane/schemas/session_registry.schema.json`（新增）
- `control_plane/schemas/output_manifest.schema.json`（新增）

### 模板 / Sample / 文档
- `templates/project/**`
- `templates/run/**`
- `projects/sample_joint_tri_runtime_v4_2/**`（新增健康 sample）
- `projects/README.md`
- `README.md`
- `QUICKSTART.md`
- `CHANGELOG.md`
- `DELIVERY_SUMMARY.md`
- `ARCHITECTURE_REVIEW_V4_2.md`（新增）
- `REFACTOR_CHECKLIST_V4_2.md`（新增）
- `MIGRATION_V4_2.md`（新增）
- `ROADMAP_V4_2.md`（新增）
- `CHANGE_SUMMARY_V4_2.md`（新增）

## 二、为什么改
- V4.1 的主要瓶颈不在 planner，而在 runtime/queue/executor/evaluator 不够真实
- 运行时状态分裂导致后续无法自然接入真实 worker / external runner / hosted tools
- guardrails 不足以保护 claim promotion、artifact integrity 和 paper-grounding
- 缺 session registry，导致很难对接真实 Responses/Agents 运行语义

## 三、删除 / 降级了什么
- 降级 `state/run_queue.json` 为 legacy compatibility input
- 降级 `ros run-executor` 为 `ros run-worker` 的兼容别名
- 降级旧 sample `sample_joint_tri_compress_v4_1` 为迁移源，而非主示例
- 删除“仅凭 manifest.status 就能代表完整 run lifecycle”的假设

## 四、新增了什么能力
- canonical `run_registry`
- worker lease / heartbeat / retry / timeout / cancel / ingest
- evaluator layer
- stronger guardrails
- session registry
- richer SQLite mirror
- runtime audit report
- V4.1 → V4.2 upgrade path

## 五、Breaking changes
- execute 阶段退出条件更严格：必须 runtime 稳定且 evaluation 为绿
- audit 阶段新增 `audit_evaluations_green`
- 占位 model/dataset 的 run 会被 guardrails 阻止创建
- evaluation fail 时写作层更新会被拦截
- canonical run state 从 `run_queue` 切到 `run_registry`
