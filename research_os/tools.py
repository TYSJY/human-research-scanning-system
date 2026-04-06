from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import coerce_str_list, deep_merge, is_placeholder_value, now_iso
from .guardrails import assess_run_request, validate_tool_call
from .workspace import WorkspaceSnapshot


def _upsert(items: list[dict[str, Any]], key_name: str, payload: dict[str, Any]) -> None:
    target = payload.get(key_name)
    for item in items:
        if item.get(key_name) == target:
            item.update(deepcopy(payload))
            return
    items.append(deepcopy(payload))


def _normalize_expected_artifacts(request: dict[str, Any]) -> list[dict[str, Any]]:
    metrics_output = request.get("metrics_output", "metrics.json")
    normalized: list[dict[str, Any]] = [
        {"path": "stdout.log", "kind": "log", "required": True, "promote_to_artifact_registry": False},
        {"path": "stderr.log", "kind": "log", "required": True, "promote_to_artifact_registry": False},
        {"path": metrics_output, "kind": "metrics", "required": True, "promote_to_artifact_registry": True},
    ]
    raw_items = request.get("expected_artifacts", []) or []
    for item in raw_items:
        if isinstance(item, str):
            kind = "metrics" if item.endswith(".json") else "log" if item.endswith(".log") else "artifact"
            normalized.append(
                {
                    "path": item,
                    "kind": kind,
                    "required": True,
                    "promote_to_artifact_registry": kind not in {"log"},
                }
            )
        elif isinstance(item, dict) and item.get("path"):
            payload = deepcopy(item)
            payload.setdefault("kind", "artifact")
            payload.setdefault("required", True)
            payload.setdefault("promote_to_artifact_registry", payload.get("kind") not in {"log"})
            normalized.append(payload)

    deduped: list[dict[str, Any]] = []
    by_path: dict[str, int] = {}
    for item in normalized:
        path_value = item.get("path")
        if not path_value:
            continue
        if path_value in by_path:
            deduped[by_path[path_value]] = deepcopy(item)
        else:
            by_path[path_value] = len(deduped)
            deduped.append(deepcopy(item))
    return deduped


def _set_default(payload: dict[str, Any], key: str, value: Any) -> None:
    if key not in payload or is_placeholder_value(payload.get(key)):
        payload[key] = deepcopy(value)


def execute_tool(workspace: WorkspaceSnapshot, tool: str, arguments: dict[str, Any], actor: str, profile: str) -> str:
    validation = validate_tool_call(workspace, tool, arguments or {}, actor=actor, profile=profile)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))
    if tool == "transition_stage":
        return transition_stage(workspace, arguments, actor, profile)
    if tool == "request_gate":
        return request_gate(workspace, arguments, actor, profile)
    if tool == "log_decision":
        return log_decision(workspace, arguments, actor, profile)
    if tool == "register_evidence":
        return register_evidence(workspace, arguments, actor, profile)
    if tool == "register_baseline":
        return register_baseline(workspace, arguments, actor, profile)
    if tool == "register_result":
        return register_result(workspace, arguments, actor, profile)
    if tool == "register_artifact":
        return register_artifact(workspace, arguments, actor, profile)
    if tool == "create_run":
        return create_run(workspace, arguments, actor, profile)
    if tool == "queue_run":
        return queue_run(workspace, arguments, actor, profile)
    if tool == "update_task":
        return update_task(workspace, arguments, actor, profile)
    raise ValueError(f"Unknown tool: {tool}")


def _log_tool_call(workspace: WorkspaceSnapshot, tool: str, arguments: dict[str, Any], actor: str, profile: str, message: str) -> None:
    workspace.append_log(
        "tool_calls.jsonl",
        {
            "timestamp": now_iso(),
            "tool": tool,
            "actor": actor,
            "profile": profile,
            "arguments": arguments,
            "message": message,
        },
    )


def transition_stage(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    target = arguments["stage"]
    order = ["scan", "design", "execute", "write", "audit"]
    current_index = order.index(target)
    status_map = {}
    for idx, stage in enumerate(order):
        if idx < current_index:
            status_map[stage] = "done"
        elif idx == current_index:
            status_map[stage] = "active"
        else:
            status_map[stage] = "blocked"
    workspace.stage_state["current_stage"] = target
    workspace.stage_state["stage_status"] = status_map
    workspace.save_state("stage_state")
    workspace.log_event("stage_transition", actor=actor, profile=profile, target_stage=target)
    message = f"stage -> {target}"
    _log_tool_call(workspace, "transition_stage", arguments, actor, profile, message)
    return message


def request_gate(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    gate_id = arguments["gate_id"]
    reason = arguments.get("reason", "")
    for gate in workspace.stage_state.get("gates", []):
        if gate.get("gate_id") == gate_id:
            if gate.get("status") != "approved":
                gate["status"] = "requested"
                gate["requested_by"] = actor
                gate["requested_at"] = now_iso()
                gate["last_reason"] = reason
            workspace.save_state("stage_state")
            workspace.log_event("gate_requested", actor=actor, profile=profile, gate_id=gate_id, reason=reason)
            message = f"gate requested: {gate_id}"
            _log_tool_call(workspace, "request_gate", arguments, actor, profile, message)
            return message
    workspace.stage_state.setdefault("gates", []).append(
        {"gate_id": gate_id, "title": gate_id, "status": "requested", "requested_by": actor, "requested_at": now_iso(), "last_reason": reason}
    )
    workspace.save_state("stage_state")
    message = f"gate requested: {gate_id}"
    _log_tool_call(workspace, "request_gate", arguments, actor, profile, message)
    return message


def log_decision(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    payload = {
        "timestamp": now_iso(),
        "actor": actor,
        "profile": profile,
        "decision": arguments.get("decision", ""),
        "why": arguments.get("why", ""),
        "impact": arguments.get("impact", ""),
    }
    workspace.append_log("decisions.jsonl", payload)
    workspace.log_event("decision_logged", actor=actor, profile=profile, decision=payload["decision"])
    message = f"decision logged: {payload['decision']}"
    _log_tool_call(workspace, "log_decision", arguments, actor, profile, message)
    return message


def register_evidence(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    payload = deepcopy(arguments)
    payload.setdefault("recorded_at", now_iso())
    _upsert(workspace.evidence_registry.setdefault("items", []), "evidence_id", payload)
    workspace.save_state("evidence_registry")
    workspace.log_event("evidence_registered", actor=actor, profile=profile, evidence_id=payload.get("evidence_id"))
    message = f"evidence:{payload.get('evidence_id')}"
    _log_tool_call(workspace, "register_evidence", arguments, actor, profile, message)
    return message


def register_baseline(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    payload = deepcopy(arguments)
    payload.setdefault("recorded_at", now_iso())
    _upsert(workspace.baseline_registry.setdefault("items", []), "baseline_id", payload)
    workspace.save_state("baseline_registry")
    workspace.log_event("baseline_registered", actor=actor, profile=profile, baseline_id=payload.get("baseline_id"))
    message = f"baseline:{payload.get('baseline_id')}"
    _log_tool_call(workspace, "register_baseline", arguments, actor, profile, message)
    return message


def register_result(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    payload = deepcopy(arguments)
    payload.setdefault("registered_at", now_iso())
    payload.setdefault("validation_status", "pending")
    payload.setdefault("provenance", {})
    _upsert(workspace.results_registry.setdefault("results", []), "result_id", payload)
    workspace.save_state("results_registry")
    run_id = payload.get("run_id")
    if run_id:
        run = workspace.get_run(run_id)
        if run is not None:
            result_ids = set(run.get("result_ids", []))
            if payload.get("result_id"):
                result_ids.add(payload["result_id"])
            run["result_ids"] = sorted(result_ids)
            if payload.get("claim_id"):
                claims = set(run.get("claims_under_test", []))
                claims.add(payload["claim_id"])
                run["claims_under_test"] = sorted(claims)
            workspace.save_state("run_registry")
    workspace.log_event("result_registered", actor=actor, profile=profile, result_id=payload.get("result_id"), run_id=run_id)
    message = f"result:{payload.get('result_id')}"
    _log_tool_call(workspace, "register_result", arguments, actor, profile, message)
    return message


def register_artifact(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    payload = deepcopy(arguments)
    payload.setdefault("name", payload.get("path"))
    payload.setdefault("status", "ready")
    payload.setdefault("updated_at", now_iso())
    payload.setdefault("kind", None)
    payload.setdefault("path", None)
    payload.setdefault("run_id", None)
    payload.setdefault("owner", actor)
    payload.setdefault("notes", "")
    payload.setdefault("provenance", {})
    _upsert(workspace.artifact_registry.setdefault("items", []), "name", payload)
    workspace.save_state("artifact_registry")
    workspace.log_event("artifact_registered", actor=actor, profile=profile, artifact=payload.get("name"), run_id=payload.get("run_id"))
    message = f"artifact:{payload.get('name')}"
    _log_tool_call(workspace, "register_artifact", arguments, actor, profile, message)
    return message


def create_run(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    run_id = arguments["run_id"]
    manifest = deepcopy(arguments.get("manifest", {}))
    request = deepcopy(arguments.get("request", {}))
    run_dir = workspace.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    runtime_defaults = workspace.project.get("budgets", {}).get("runtime", {})
    default_retry = deepcopy(runtime_defaults.get("default_retry_policy", {}))
    default_reasoning = workspace.project.get("reasoning_policy", {}).get("default", "think")

    _set_default(manifest, "run_id", run_id)
    _set_default(manifest, "created_at", now_iso())
    _set_default(manifest, "notes", "")
    _set_default(request, "executor", "manual")
    _set_default(request, "executor_profile", None)
    _set_default(request, "command", [])
    _set_default(request, "env", {})
    _set_default(request, "cwd_mode", "run_dir")
    if request.get("timeout_sec") is None or request.get("timeout_sec") == 0:
        request["timeout_sec"] = runtime_defaults.get("default_timeout_sec", 1800)
    _set_default(request, "lease_ttl_sec", runtime_defaults.get("lease_ttl_sec", 30))
    _set_default(request, "heartbeat_sec", runtime_defaults.get("heartbeat_sec", 2))
    _set_default(request, "metrics_output", "metrics.json")
    _set_default(request, "register_results", [])
    _set_default(request, "resource_budget", {})
    _set_default(request, "retry_policy", default_retry if default_retry else {"max_attempts": 1, "retry_on": [], "backoff_sec": 0, "fail_on_evaluation_error": True})
    _set_default(request, "approval", {"required": False, "reason": "", "risk_tags": []})
    _set_default(request, "evaluators", ["metrics_presence", "result_value_presence", "artifact_integrity", "claim_result_consistency", "evidence_coverage", "provenance_completeness"])
    if arguments.get("task_id") and is_placeholder_value(request.get("task_id")):
        request["task_id"] = arguments.get("task_id")
    if is_placeholder_value(request.get("depends_on_runs")):
        request["depends_on_runs"] = arguments.get("depends_on_runs") or []
    if is_placeholder_value(request.get("queue_group")):
        request["queue_group"] = arguments.get("queue_group") or request.get("task_id") or run_id
    if is_placeholder_value(request.get("reasoning_profile")):
        request["reasoning_profile"] = arguments.get("reasoning_profile") or default_reasoning
    if is_placeholder_value(request.get("worker_requirements")):
        request["worker_requirements"] = deepcopy(arguments.get("worker_requirements") or {"labels": []})
    if is_placeholder_value(request.get("selector")):
        request["selector"] = deepcopy(
            arguments.get("selector")
            or {"group": request.get("queue_group") or run_id, "min_score_to_promote": 75, "stop_after_preferred": False}
        )
    if request.get("created_from_session_id") is None:
        request["created_from_session_id"] = arguments.get("created_from_session_id") or workspace.runtime.get("last_session_id")
    request["expected_artifacts"] = _normalize_expected_artifacts(request)

    risk = assess_run_request(workspace, manifest, request)
    if risk["risk_tags"]:
        request["approval"]["risk_tags"] = sorted(set(request["approval"].get("risk_tags", []) + risk["risk_tags"]))
    request["approval"]["required"] = bool(request["approval"].get("required")) or risk["approval_required"]
    if risk["blocked_reasons"]:
        request["approval"]["required"] = True
        request["approval"]["reason"] = "; ".join(risk["blocked_reasons"])

    workspace.save_run_manifest(run_id, manifest)
    workspace.save_run_request(run_id, request)
    workspace.save_run_metrics(run_id, {"metrics": {}})
    workspace.save_run_output_manifest(run_id, {"run_id": run_id, "generated_at": None, "files": [], "missing": []})
    workspace.write_run_log(run_id, "stdout.log", "")
    workspace.write_run_log(run_id, "stderr.log", "")
    workspace.write_run_log(run_id, "notes.md", "# Run Notes\n\n- Created by Research OS V4.8\n")

    approval_status = "pending" if request["approval"].get("required") else "not_required"
    claims_under_test = sorted({spec.get("claim_id") for spec in request.get("register_results", []) if spec.get("claim_id")})
    entry = {
        "run_id": run_id,
        "status": "planned",
        "priority": arguments.get("priority", "normal"),
        "executor": request.get("executor", "manual"),
        "task_id": request.get("task_id"),
        "queue_group": request.get("queue_group"),
        "reasoning_profile": request.get("reasoning_profile", default_reasoning),
        "depends_on_runs": coerce_str_list(request.get("depends_on_runs")),
        "worker_requirements": request.get("worker_requirements", {"labels": []}),
        "created_at": manifest.get("created_at"),
        "created_by": actor,
        "created_from_session_id": request.get("created_from_session_id"),
        "queued_at": None,
        "started_at": None,
        "ended_at": None,
        "attempt_count": 0,
        "max_attempts": int(request.get("retry_policy", {}).get("max_attempts", 1) or 1),
        "retry_count": 0,
        "retry_at": None,
        "approval": {
            "required": bool(request["approval"].get("required")),
            "status": approval_status,
            "reason": request["approval"].get("reason", ""),
            "risk_tags": request["approval"].get("risk_tags", []),
        },
        "lease": {},
        "cancel_requested": False,
        "cancel_requested_at": None,
        "blocked_reason": None,
        "last_error": None,
        "evaluation_status": "pending",
        "last_evaluated_at": None,
        "result_ids": [],
        "claims_under_test": claims_under_test,
        "manifest_path": f"runs/{run_id}/manifest.json",
        "request_path": f"runs/{run_id}/request.json",
        "metrics_path": f"runs/{run_id}/metrics.json",
        "output_manifest_path": f"runs/{run_id}/output_manifest.json",
        "resource_budget": request.get("resource_budget", {}),
        "retry_policy": request.get("retry_policy", {}),
        "selector": request.get("selector", {}),
        "selection": {"group": request.get("selector", {}).get("group") or request.get("queue_group") or run_id, "status": "unscored", "score": None, "best_in_group": False, "updated_at": None, "score_breakdown": {}},
        "attempts": [],
    }
    workspace.upsert_run(run_id, entry)
    workspace.log_event(
        "run_created",
        actor=actor,
        profile=profile,
        run_id=run_id,
        approval_status=approval_status,
        reasoning_profile=request.get("reasoning_profile"),
        task_id=request.get("task_id"),
        queue_group=request.get("queue_group"),
    )
    message = f"run created: {run_id}"
    _log_tool_call(workspace, "create_run", arguments, actor, profile, message)
    return message


def queue_run(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    run_id = arguments["run_id"]
    priority = arguments.get("priority", "normal")
    run = workspace.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown run_id: {run_id}")
    if run.get("status") in {"queued", "leased", "running"}:
        message = f"run already active: {run_id}"
        _log_tool_call(workspace, "queue_run", arguments, actor, profile, message)
        return message
    run["priority"] = priority
    approval = run.get("approval", {})
    if approval.get("status") in {"pending", "requested", "rejected"}:
        run["status"] = "blocked"
        run["blocked_reason"] = "approval_required"
        workspace.save_state("run_registry")
        message = f"run blocked awaiting approval: {run_id}"
        _log_tool_call(workspace, "queue_run", arguments, actor, profile, message)
        return message
    if run.get("cancel_requested"):
        run["status"] = "cancelled"
        workspace.save_state("run_registry")
        message = f"run cancelled before queueing: {run_id}"
        _log_tool_call(workspace, "queue_run", arguments, actor, profile, message)
        return message

    request = workspace.load_run_request(run_id)
    executor = request.get("executor", run.get("executor", "manual"))
    if executor == "manual":
        run["status"] = "blocked"
        run["blocked_reason"] = "manual_execution_required"
        workspace.save_state("run_registry")
        message = f"run blocked: manual executor requires human dispatch: {run_id}"
        _log_tool_call(workspace, "queue_run", arguments, actor, profile, message)
        return message

    budget_gate_approved = workspace.gate_status("budget_expand") == "approved"
    limit = int(workspace.project.get("budgets", {}).get("max_active_or_queued_runs_without_budget_expand", 2) or 2)
    active_or_queued = [item for item in workspace.run_registry.get("runs", []) if item.get("run_id") != run_id and item.get("status") in {"queued", "leased", "running"}]
    if not budget_gate_approved and len(active_or_queued) >= limit:
        run["status"] = "blocked"
        run["blocked_reason"] = "budget_expand_required"
        workspace.save_state("run_registry")
        workspace.log_event("run_blocked_budget", run_id=run_id, active_or_queued=len(active_or_queued), limit=limit)
        message = f"run blocked awaiting budget gate: {run_id}"
        _log_tool_call(workspace, "queue_run", arguments, actor, profile, message)
        return message

    run["status"] = "queued"
    run["queued_at"] = now_iso()
    run["blocked_reason"] = None
    workspace.save_state("run_registry")
    workspace.log_event("run_queued", actor=actor, profile=profile, run_id=run_id, priority=priority)
    message = f"run queued: {run_id}"
    _log_tool_call(workspace, "queue_run", arguments, actor, profile, message)
    return message


def update_task(workspace: WorkspaceSnapshot, arguments: dict[str, Any], actor: str, profile: str) -> str:
    task_id = arguments["task_id"]
    patch = deepcopy(arguments.get("patch", {}))
    for task in workspace.task_graph.get("tasks", []):
        if task.get("task_id") == task_id:
            task.update(deep_merge({}, patch))
            task["updated_at"] = now_iso()
            workspace.save_state("task_graph")
            workspace.log_event("task_updated", actor=actor, profile=profile, task_id=task_id, patch=patch)
            message = f"task updated: {task_id}"
            _log_tool_call(workspace, "update_task", arguments, actor, profile, message)
            return message
    raise ValueError(f"Unknown task_id: {task_id}")
