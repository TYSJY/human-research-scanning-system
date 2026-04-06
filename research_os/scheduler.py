from __future__ import annotations

from typing import Any

from .common import coerce_str_list, load_json, lookup_path, minutes_since, resource_path
from .workspace import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, WorkspaceSnapshot


SCHEDULABLE_STATUSES = {"queued", "retryable"}


def load_runtime_policy() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "runtime_policy.json"), {})


def _task_priority_lookup(workspace: WorkspaceSnapshot) -> dict[str, str]:
    return {task.get("task_id"): task.get("priority", "P3") for task in workspace.task_graph.get("tasks", []) if task.get("task_id")}


def _priority_score(priority: str) -> int:
    return {"critical": 1000, "high": 750, "normal": 450, "low": 150}.get((priority or "normal").lower(), 0)


def _task_score(priority: str) -> int:
    return {"P0": 160, "P1": 100, "P2": 50, "P3": 0}.get(priority, 0)


def _profile_score(profile: str) -> int:
    return {"pro": 40, "deep_research": 25, "think": 0}.get(profile or "think", 0)


def _selector_group(run: dict[str, Any], request: dict[str, Any], manifest: dict[str, Any]) -> str:
    explicit = run.get("queue_group") or lookup_path(run, "selector.group") or request.get("queue_group") or lookup_path(request, "selector.group")
    if explicit:
        return str(explicit)
    if run.get("task_id"):
        return f"task:{run['task_id']}"
    if manifest.get("question"):
        return f"question:{manifest['question']}"
    return f"run:{run.get('run_id')}"


def _preferred_groups(workspace: WorkspaceSnapshot) -> dict[str, str]:
    groups: dict[str, str] = {}
    for run in workspace.run_registry.get("runs", []):
        selection = run.get("selection", {})
        group = selection.get("group") or run.get("queue_group")
        if group and selection.get("status") == "preferred" and run.get("status") == "succeeded":
            groups[str(group)] = run.get("run_id")
    return groups


def _required_labels(run: dict[str, Any], request: dict[str, Any]) -> list[str]:
    return sorted(
        set(
            coerce_str_list(lookup_path(run, "worker_requirements.labels"))
            + coerce_str_list(lookup_path(request, "worker_requirements.labels"))
        )
    )


def _dependencies_status(workspace: WorkspaceSnapshot, run: dict[str, Any], request: dict[str, Any]) -> tuple[bool, list[str]]:
    dependency_ids = sorted(set(coerce_str_list(run.get("depends_on_runs")) + coerce_str_list(request.get("depends_on_runs"))))
    unsatisfied: list[str] = []
    failed: list[str] = []
    for dependency_id in dependency_ids:
        dependency = workspace.get_run(dependency_id)
        if dependency is None:
            unsatisfied.append(f"missing:{dependency_id}")
            continue
        dep_status = dependency.get("status")
        if dep_status != "succeeded":
            unsatisfied.append(f"{dependency_id}:{dep_status}")
            if dep_status in {"failed", "cancelled"}:
                failed.append(dependency_id)
    return len(unsatisfied) == 0, failed or unsatisfied


def _retry_due(run: dict[str, Any]) -> bool:
    retry_at = run.get("retry_at")
    if not retry_at:
        return True
    return minutes_since(retry_at) > 0


def _queue_age_score(run: dict[str, Any]) -> int:
    age_minutes = minutes_since(run.get("queued_at") or run.get("created_at"))
    return min(int(age_minutes * 2), 240)


def _attempt_penalty(run: dict[str, Any]) -> int:
    return int(run.get("attempt_count", 0) or 0) * 20


def _score_run(workspace: WorkspaceSnapshot, run: dict[str, Any], request: dict[str, Any], manifest: dict[str, Any]) -> int:
    task_priority = _task_priority_lookup(workspace).get(run.get("task_id"), "P3")
    selection = run.get("selection", {})
    score = 0
    score += _priority_score(run.get("priority", "normal"))
    score += _task_score(task_priority)
    score += _profile_score(run.get("reasoning_profile") or request.get("reasoning_profile") or workspace.project.get("reasoning_policy", {}).get("default", "think"))
    score += _queue_age_score(run)
    if run.get("status") == "retryable":
        score += 60
    if run.get("evaluation_status") == "fail":
        score += 15
    if selection.get("status") == "preferred":
        score -= 80
    score -= _attempt_penalty(run)
    if manifest.get("question") and run.get("task_id"):
        score += 15
    return score


def build_scheduler_snapshot(workspace: WorkspaceSnapshot, worker_labels: list[str] | None = None) -> dict[str, Any]:
    worker_labels = sorted(set(worker_labels or []))
    runtime_budget = workspace.project.get("budgets", {}).get("runtime", {})
    max_concurrent = int(runtime_budget.get("max_concurrent_runs", 1) or 1)
    active_runs = [run for run in workspace.run_registry.get("runs", []) if run.get("status") in ACTIVE_RUN_STATUSES]
    capacity_remaining = max(max_concurrent - len(active_runs), 0)
    preferred_groups = _preferred_groups(workspace)

    ready: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}

    for run in workspace.run_registry.get("runs", []):
        run_id = run.get("run_id")
        if not run_id:
            continue
        request = workspace.load_run_request(run_id)
        manifest = workspace.load_run_manifest(run_id)
        group = _selector_group(run, request, manifest)
        stop_after_preferred = bool(lookup_path(run, "selector.stop_after_preferred", lookup_path(request, "selector.stop_after_preferred", False)))
        required_labels = _required_labels(run, request)
        dependencies_ready, dependency_reason = _dependencies_status(workspace, run, request)
        preferred_in_group = preferred_groups.get(group)

        entry = {
            "run_id": run_id,
            "status": run.get("status"),
            "priority": run.get("priority", "normal"),
            "executor": run.get("executor") or request.get("executor", "manual"),
            "task_id": run.get("task_id"),
            "queue_group": run.get("queue_group") or group,
            "reasoning_profile": run.get("reasoning_profile") or request.get("reasoning_profile") or workspace.project.get("reasoning_policy", {}).get("default", "think"),
            "required_labels": required_labels,
            "selection": run.get("selection", {}),
            "score": _score_run(workspace, run, request, manifest),
            "reasons": [],
        }

        group_bucket = groups.setdefault(group, {"group": group, "run_ids": [], "preferred_run_id": preferred_in_group, "stop_after_preferred": stop_after_preferred})
        group_bucket["run_ids"].append(run_id)

        if run.get("status") in TERMINAL_RUN_STATUSES:
            terminal.append(entry)
            continue
        if run.get("status") in ACTIVE_RUN_STATUSES:
            entry["reasons"].append("active")
            running.append(entry)
            continue
        if entry["executor"] == "manual":
            entry["reasons"].append("manual_execution_required")
            waiting.append(entry)
            continue
        if entry["executor"] == "external":
            entry["reasons"].append("awaiting_external_completion")
            waiting.append(entry)
            continue
        if run.get("status") == "planned":
            entry["reasons"].append("not_queued")
            waiting.append(entry)
            continue
        approval_status = lookup_path(run, "approval.status", "not_required")
        if approval_status in {"pending", "requested", "rejected"}:
            entry["reasons"].append("approval_required")
            waiting.append(entry)
            continue
        if run.get("status") not in SCHEDULABLE_STATUSES:
            entry["reasons"].append("status_not_schedulable")
            waiting.append(entry)
            continue
        if run.get("status") == "retryable" and not _retry_due(run):
            entry["reasons"].append("retry_window_not_elapsed")
            waiting.append(entry)
            continue
        if not dependencies_ready:
            entry["reasons"].append("dependency_not_ready")
            entry["dependency_detail"] = dependency_reason
            waiting.append(entry)
            continue
        if required_labels and not set(required_labels).issubset(set(worker_labels)):
            entry["reasons"].append("worker_label_mismatch")
            waiting.append(entry)
            continue
        if stop_after_preferred and preferred_in_group and preferred_in_group != run_id:
            entry["reasons"].append("selector_group_already_has_preferred_run")
            entry["preferred_run_id"] = preferred_in_group
            waiting.append(entry)
            continue
        ready.append(entry)

    ready.sort(key=lambda item: (-int(item.get("score", 0)), item.get("priority", "normal"), item.get("run_id", "")))
    dispatchable = ready[:capacity_remaining] if capacity_remaining > 0 else []
    blocked_by_capacity = ready[capacity_remaining:] if capacity_remaining < len(ready) else []
    for item in blocked_by_capacity:
        item.setdefault("reasons", []).append("capacity_exhausted")

    waiting.sort(key=lambda item: (-int(item.get("score", 0)), item.get("run_id", "")))
    running.sort(key=lambda item: (item.get("run_id", ""),))
    terminal.sort(key=lambda item: (item.get("run_id", ""),))

    return {
        "generated_at": workspace.runtime.get("last_run_at") or workspace.project.get("created_at"),
        "worker_labels": worker_labels,
        "capacity": {"max_concurrent_runs": max_concurrent, "active_runs": len(active_runs), "capacity_remaining": capacity_remaining},
        "dispatchable": dispatchable,
        "ready": ready,
        "waiting": waiting + blocked_by_capacity,
        "running": running,
        "terminal": terminal,
        "groups": sorted(groups.values(), key=lambda item: item["group"]),
        "summary": {
            "dispatchable_runs": len(dispatchable),
            "ready_runs": len(ready),
            "waiting_runs": len(waiting) + len(blocked_by_capacity),
            "active_runs": len(running),
            "terminal_runs": len(terminal),
            "selector_groups": len(groups),
        },
    }


def select_dispatchable_runs(workspace: WorkspaceSnapshot, worker_labels: list[str] | None = None, limit: int = 1) -> list[dict[str, Any]]:
    snapshot = build_scheduler_snapshot(workspace, worker_labels=worker_labels)
    return snapshot.get("dispatchable", [])[: max(limit, 0)]
