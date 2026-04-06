from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import is_placeholder_value, json_hash, load_json, now_iso, resource_path
from .scheduler import build_scheduler_snapshot
from .workspace import WorkspaceSnapshot


RULE_DESCRIPTIONS = {
    "scan_evidence_minimum": "evidence_registry 至少 3 条",
    "scan_baseline_minimum": "baseline_registry 至少 3 条",
    "scan_novelty_written": "novelty_audit 非占位",
    "design_claim_defined": "claims 至少 1 条",
    "design_claim_checks_defined": "每个活跃 claim 都有 evidence_refs 与 acceptance_checks",
    "design_mvp_locked": "mvp_name 非占位",
    "execution_run_created": "至少 1 个 run",
    "execution_first_result": "至少 1 条 result",
    "execution_runtime_stable": "没有待执行 / 重试 / 阻塞的关键 run，且成功 run 的 evaluation 为绿色",
    "write_grounded_draft": "title_abstract/outline 已以结果为依据",
    "audit_artifacts_ready": "artifact_registry 中无 missing/invalid 项",
    "audit_evaluations_green": "没有 run evaluation failure",
}

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
STATUS_OPEN = {"planned", "todo", "in_progress", "blocked"}


def load_stage_machine() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "stage_machine.json"), {"stages": [], "gates": []})


def load_task_blueprints() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "task_blueprints.json"), {"tasks": []})


def load_reasoning_profiles() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "reasoning_profiles.json"), {"profiles": {}})


def load_guardrail_policy() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "guardrail_policy.json"), {})


def stage_order() -> dict[str, int]:
    return {item["stage"]: idx for idx, item in enumerate(load_stage_machine().get("stages", []))}


def stage_info(stage: str) -> dict[str, Any]:
    for item in load_stage_machine().get("stages", []):
        if item.get("stage") == stage:
            return item
    return {}


def _note_non_placeholder(workspace: WorkspaceSnapshot, rel_path: str, min_len: int = 80) -> bool:
    text = workspace.read_note(rel_path).strip()
    if len(text) < min_len:
        return False
    lowered = text.lower()
    return "replace-me" not in lowered and "todo" not in lowered and "tbd" not in lowered


def _claims_structured(workspace: WorkspaceSnapshot) -> bool:
    min_refs = load_guardrail_policy().get("min_evidence_refs_per_claim", 2)
    known_evidence = {item.get("evidence_id") for item in workspace.evidence_registry.get("items", [])}
    claims = workspace.claims.get("claims", [])
    if not claims:
        return False
    for claim in claims:
        if claim.get("status") == "archived":
            continue
        refs = [item for item in claim.get("evidence_refs", []) if item in known_evidence]
        checks = claim.get("acceptance_checks", [])
        if len(refs) < min_refs or not checks:
            return False
    return True


def _runtime_stable(workspace: WorkspaceSnapshot) -> bool:
    metrics = workspace.metrics_summary()
    if metrics["succeeded_runs"] < 1:
        return False
    if metrics["evaluation_failures"] > 0:
        return False
    snapshot = build_scheduler_snapshot(workspace, worker_labels=[])
    if snapshot.get("summary", {}).get("dispatchable_runs", 0) > 0:
        return False
    if snapshot.get("summary", {}).get("active_runs", 0) > 0:
        return False
    waiting = snapshot.get("waiting", [])
    high_priority_waiting = [
        item
        for item in waiting
        if item.get("priority", "normal") in {"critical", "high"}
        and not set(item.get("reasons", [])).issubset({"manual_execution_required"})
    ]
    return len(high_priority_waiting) == 0


def _artifacts_ready(workspace: WorkspaceSnapshot) -> bool:
    items = workspace.artifact_registry.get("items", [])
    if not items:
        return False
    bad = [item for item in items if item.get("status") in {"missing", "invalid"}]
    return len(bad) == 0


def evaluate_rule(rule_name: str, workspace: WorkspaceSnapshot) -> bool:
    m = workspace.metrics_summary()
    if rule_name == "scan_evidence_minimum":
        return m["evidence_items"] >= 3
    if rule_name == "scan_baseline_minimum":
        return m["baseline_items"] >= 3
    if rule_name == "scan_novelty_written":
        return _note_non_placeholder(workspace, "notes/novelty_audit.md", min_len=120)
    if rule_name == "design_claim_defined":
        return m["claim_count"] >= 1
    if rule_name == "design_claim_checks_defined":
        return _claims_structured(workspace)
    if rule_name == "design_mvp_locked":
        return not is_placeholder_value(workspace.mvp.get("mvp_name"))
    if rule_name == "execution_run_created":
        return m["run_count"] >= 1
    if rule_name == "execution_first_result":
        return m["result_count"] >= 1
    if rule_name == "execution_runtime_stable":
        return _runtime_stable(workspace)
    if rule_name == "write_grounded_draft":
        if m["result_count"] < 1 or m["evaluation_failures"] > 0 or m.get("preferred_runs", 0) < 1:
            return False
        return _note_non_placeholder(workspace, "notes/title_abstract.md", 80) and _note_non_placeholder(workspace, "notes/outline.md", 80)
    if rule_name == "audit_artifacts_ready":
        return _artifacts_ready(workspace)
    if rule_name == "audit_evaluations_green":
        return m["evaluation_failures"] == 0 and m["succeeded_runs"] >= 1
    raise KeyError(f"Unknown closure rule: {rule_name}")


def runtime_backlog(workspace: WorkspaceSnapshot, scheduler_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = scheduler_snapshot or build_scheduler_snapshot(workspace, worker_labels=[])
    buckets: dict[str, Any] = {
        status: []
        for status in [
            "planned",
            "queued",
            "leased",
            "running",
            "retryable",
            "blocked",
            "failed",
            "cancelled",
            "succeeded",
            "ready",
            "dispatchable",
            "waiting",
        ]
    }
    for run in workspace.run_registry.get("runs", []):
        status = run.get("status", "planned")
        buckets.setdefault(status, []).append(run)
    buckets["ready"] = snapshot.get("ready", [])
    buckets["dispatchable"] = snapshot.get("dispatchable", [])
    buckets["waiting"] = snapshot.get("waiting", [])
    buckets["scheduler_summary"] = snapshot.get("summary", {})
    buckets["scheduler_groups"] = snapshot.get("groups", [])
    return buckets


def sync_task_graph(workspace: WorkspaceSnapshot) -> bool:
    changed = False
    graph = workspace.task_graph
    tasks = graph.setdefault("tasks", [])
    existing = {task["task_id"]: task for task in tasks if "task_id" in task}
    order = stage_order()
    current_stage_rank = order.get(workspace.current_stage, 0)

    for blueprint in load_task_blueprints().get("tasks", []):
        task = existing.get(blueprint["task_id"])
        if task is None:
            task = deepcopy(blueprint)
            task.update(
                {
                    "status": "planned" if order.get(task["stage"], 0) > current_stage_rank else "todo",
                    "notes": "",
                    "created_at": workspace.runtime.get("last_run_at") or workspace.project.get("created_at") or now_iso(),
                    "updated_at": workspace.runtime.get("last_run_at") or workspace.project.get("created_at") or now_iso(),
                }
            )
            tasks.append(task)
            existing[task["task_id"]] = task
            changed = True
        else:
            for key, value in blueprint.items():
                if key not in task:
                    task[key] = deepcopy(value)

    task_index = {task["task_id"]: task for task in tasks if "task_id" in task}
    for task in tasks:
        old_status = task.get("status", "todo")
        closure_rule = task.get("closure_rule")
        stage_rank = order.get(task.get("stage", "scan"), 0)
        if closure_rule and evaluate_rule(closure_rule, workspace):
            new_status = "done"
        elif old_status == "cancelled":
            new_status = old_status
        elif stage_rank > current_stage_rank:
            new_status = "planned"
        else:
            deps = task.get("depends_on", [])
            gate_id = task.get("requires_gate")
            deps_done = all(task_index.get(dep, {}).get("status") == "done" for dep in deps)
            gate_ready = True
            if gate_id:
                gate_status = workspace.gate_status(gate_id)
                if gate_status not in {"approved", "not_required"} and stage_rank <= current_stage_rank:
                    gate_ready = False
            if not deps_done or not gate_ready:
                new_status = "blocked"
            elif old_status == "in_progress":
                new_status = "in_progress"
            elif old_status == "done":
                new_status = "done"
            else:
                new_status = "todo"
        if new_status != old_status:
            task["status"] = new_status
            task["updated_at"] = workspace.runtime.get("last_run_at") or workspace.project.get("created_at") or now_iso()
            changed = True

    tasks.sort(key=lambda item: (order.get(item.get("stage", "scan"), 99), PRIORITY_ORDER.get(item.get("priority", "P3"), 99), item.get("task_id", "")))
    if changed:
        workspace.save_state("task_graph")
    return changed


def evaluate_stage_exit(workspace: WorkspaceSnapshot, stage: str) -> dict[str, Any]:
    info = stage_info(stage)
    unmet_rules = [rule for rule in info.get("exit_rules", []) if not evaluate_rule(rule, workspace)]
    pending_gates = [gate_id for gate_id in info.get("required_gates", []) if workspace.gate_status(gate_id) != "approved"]
    return {
        "stage": stage,
        "unmet_rules": unmet_rules,
        "pending_gates": pending_gates,
        "advance_ready": len(unmet_rules) == 0 and len(pending_gates) == 0,
        "gate_needed": len(unmet_rules) == 0 and len(pending_gates) > 0,
        "next_stage": info.get("next_stage"),
    }


def _resolve_profile(
    workspace: WorkspaceSnapshot,
    agent: str,
    default_profile: str,
    backlog: dict[str, Any],
    metrics: dict[str, int],
    scheduler_snapshot: dict[str, Any],
) -> str:
    reasoning_policy = workspace.project.get("reasoning_policy", {})
    if agent == "scan" and metrics["evidence_items"] < 3:
        return reasoning_policy.get("deep_research", "deep_research")
    if agent in {"design", "audit"} and (metrics["evaluation_failures"] > 0 or metrics.get("preferred_runs", 0) < 1):
        return reasoning_policy.get("critical", "pro")
    if agent == "execution":
        summary = scheduler_snapshot.get("summary", {})
        if summary.get("dispatchable_runs", 0) > 0:
            return reasoning_policy.get("critical", "pro")
        if backlog["retryable"] or metrics["evaluation_failures"] > 0:
            return reasoning_policy.get("critical", "pro")
        if len(scheduler_snapshot.get("groups", [])) > 1:
            return reasoning_policy.get("critical", "pro")
    if metrics["pending_run_approvals"] > 0:
        return reasoning_policy.get("critical", "pro")
    return default_profile


def build_plan(workspace: WorkspaceSnapshot, persist: bool = True) -> dict[str, Any]:
    if persist:
        sync_task_graph(workspace)
    current_stage = workspace.current_stage
    metrics = workspace.metrics_summary()
    order = stage_order()
    current_stage_rank = order.get(current_stage, 0)
    tasks = workspace.task_graph.get("tasks", [])
    stage_tasks = [task for task in tasks if task.get("stage") == current_stage and task.get("status") in STATUS_OPEN]
    carry_over = [task for task in tasks if order.get(task.get("stage", "scan"), 0) < current_stage_rank and task.get("status") in STATUS_OPEN]
    open_tasks = stage_tasks + carry_over
    open_tasks.sort(key=lambda item: (PRIORITY_ORDER.get(item.get("priority", "P3"), 99), order.get(item.get("stage", current_stage), 99), item.get("task_id", "")))

    exit_eval = evaluate_stage_exit(workspace, current_stage)
    scheduler_snapshot = build_scheduler_snapshot(workspace, worker_labels=[])
    backlog = runtime_backlog(workspace, scheduler_snapshot=scheduler_snapshot)
    blocking: list[str] = []
    for task in open_tasks:
        if task.get("priority") == "P0":
            blocking.append(f"P0 task open: {task.get('task_id')} / {task.get('title')}")
    blocking.extend(RULE_DESCRIPTIONS.get(rule, rule) for rule in exit_eval["unmet_rules"])
    for gate_id in exit_eval["pending_gates"]:
        blocking.append(f"Pending human gate: {gate_id}")
    if backlog["retryable"]:
        blocking.append(f"Retryable runs pending attention: {', '.join(run['run_id'] for run in backlog['retryable'][:3])}")
    if backlog["blocked"]:
        blocking.append(f"Blocked runs pending approval or external action: {', '.join(run['run_id'] for run in backlog['blocked'][:3])}")
    if scheduler_snapshot.get("summary", {}).get("dispatchable_runs", 0) > 0:
        blocking.append(f"Dispatchable runs waiting for workers: {', '.join(run['run_id'] for run in scheduler_snapshot.get('dispatchable', [])[:3])}")
    if backlog["queued"] or backlog["leased"] or backlog["running"]:
        active = backlog["queued"] + backlog["leased"] + backlog["running"]
        blocking.append(f"Active run lifecycle not yet settled: {', '.join(run['run_id'] for run in active[:3])}")
    if metrics["evaluation_failures"] > 0:
        blocking.append("There are failing run evaluations that should be resolved before promoting claims or writing aggressively.")
    if metrics.get("preferred_runs", 0) < 1 and current_stage in {"write", "audit"}:
        blocking.append("No preferred run has been selected yet; writing/audit posture should remain conservative.")

    requested_gates = []
    if exit_eval["gate_needed"]:
        for gate_id in exit_eval["pending_gates"]:
            requested_gates.append({"gate_id": gate_id, "reason": f"{current_stage} 已满足机器条件，等待人工 gate 批准后再进入下一阶段"})

    handoff_reason = ""
    if metrics["pending_run_approvals"] > 0 or requested_gates:
        recommended_agent = "controller"
        recommended_profile = workspace.project.get("reasoning_policy", {}).get("critical", "pro")
        handoff_reason = "pending_human_gate_or_run_approval"
    elif current_stage == "execute" and (
        backlog["retryable"]
        or backlog["blocked"]
        or backlog["queued"]
        or backlog["leased"]
        or backlog["running"]
        or scheduler_snapshot.get("summary", {}).get("dispatchable_runs", 0) > 0
    ):
        recommended_agent = "execution"
        recommended_profile = _resolve_profile(workspace, "execution", "think", backlog, metrics, scheduler_snapshot)
        handoff_reason = "runtime_backlog"
    elif metrics["evaluation_failures"] > 0:
        recommended_agent = "audit" if current_stage in {"write", "audit"} else "design"
        recommended_profile = workspace.project.get("reasoning_policy", {}).get("critical", "pro")
        handoff_reason = "failing_evaluations"
    elif exit_eval["advance_ready"]:
        recommended_agent = "controller"
        recommended_profile = workspace.project.get("reasoning_policy", {}).get("critical", "pro") if current_stage in {"design", "audit", "execute"} else workspace.project.get("reasoning_policy", {}).get("default", "think")
        handoff_reason = "stage_ready_to_advance"
    elif open_tasks:
        recommended_agent = open_tasks[0].get("agent", stage_info(current_stage).get("default_agent", "controller"))
        recommended_profile = _resolve_profile(
            workspace,
            recommended_agent,
            open_tasks[0].get("profile", stage_info(current_stage).get("default_profile", "think")),
            backlog,
            metrics,
            scheduler_snapshot,
        )
        handoff_reason = f"open_task:{open_tasks[0].get('task_id')}"
    else:
        info = stage_info(current_stage)
        recommended_agent = info.get("default_agent", "controller")
        recommended_profile = _resolve_profile(workspace, recommended_agent, info.get("default_profile", "think"), backlog, metrics, scheduler_snapshot)
        handoff_reason = "stage_default"

    recommendations: list[str] = []
    if exit_eval["advance_ready"]:
        if exit_eval.get("next_stage") is None:
            recommendations.append(f"{current_stage} 的 exit rules 与 gates 已满足，当前阶段已达到终态，可等待人工收尾或对外发布。")
        else:
            recommendations.append(f"{current_stage} 的 exit rules 与 gates 已满足，可以进入 {exit_eval['next_stage']}.")
    elif exit_eval["gate_needed"]:
        recommendations.append("机器侧 exit rules 已满足，但还需要人工 gate。")
    else:
        recommendations.append(f"优先清理 {current_stage} 阶段的 P0 项和 runtime backlog，再考虑推进。")
    if scheduler_snapshot.get("summary", {}).get("dispatchable_runs", 0) > 0:
        recommendations.append("已有 dispatchable runs，可启动带匹配标签的 worker 继续推进 execute 闭环。")
    if backlog["retryable"]:
        recommendations.append("优先处理 retryable runs，避免 execute 阶段在失败重试前过早推进。")
    if metrics["evaluation_failures"] > 0:
        recommendations.append("先修复 evaluator fail，再升级 claim 强度或写正式摘要。")
    if metrics.get("preferred_runs", 0) < 1 and current_stage in {"write", "audit"}:
        recommendations.append("在没有 preferred run 之前，摘要、结论和 release 文案都应保持保守措辞。")

    gaps = {
        "unmet_rules": [{"rule": rule, "description": RULE_DESCRIPTIONS.get(rule, rule)} for rule in exit_eval["unmet_rules"]],
        "pending_gates": exit_eval["pending_gates"],
        "runtime_backlog": {
            key: [item.get("run_id") for item in value[:10]]
            for key, value in backlog.items()
            if isinstance(value, list) and value and key in {"queued", "leased", "running", "retryable", "blocked", "dispatchable"}
        },
        "scheduler_summary": scheduler_snapshot.get("summary", {}),
        "selector_groups": scheduler_snapshot.get("groups", [])[:10],
    }

    payload = {
        "current_stage": current_stage,
        "metrics": metrics,
        "open_tasks": open_tasks[:10],
        "blocking": blocking,
        "requested_gates": requested_gates,
        "recommended_agent": recommended_agent,
        "recommended_profile": recommended_profile,
        "handoff_reason": handoff_reason,
        "advance_ready": exit_eval["advance_ready"],
        "proposed_stage": exit_eval["next_stage"] if exit_eval["advance_ready"] else current_stage,
        "recommendations": recommendations,
        "gaps": gaps,
        "stage_exit": exit_eval,
        "runtime_backlog": gaps["runtime_backlog"],
        "scheduler": scheduler_snapshot,
    }
    if persist:
        workspace.runtime["last_plan_hash"] = json_hash(payload)
        workspace.save_state("runtime")
    return payload
