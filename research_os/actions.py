from __future__ import annotations

from copy import deepcopy
from typing import Any

from .common import deep_merge, json_hash, now_iso
from .guardrails import log_guardrail_result, validate_action_plan
from .sqlite_sync import sync_project_sqlite
from .tools import execute_tool
from .workspace import WorkspaceSnapshot


LIST_ROOT_KEYS = {
    "evidence_registry": "items",
    "baseline_registry": "items",
    "results_registry": "results",
    "artifact_registry": "items",
    "run_registry": "runs",
    "evaluation_registry": "evaluations",
    "session_registry": "sessions",
}


def _append_items(state_key: str, state_root: dict[str, Any], payload: list[dict[str, Any]]) -> dict[str, Any]:
    list_key = LIST_ROOT_KEYS.get(state_key, "items")
    if list_key not in state_root or not isinstance(state_root[list_key], list):
        state_root[list_key] = []
    state_root[list_key].extend(deepcopy(payload))
    return state_root


def _apply_state_update(workspace: WorkspaceSnapshot, update: dict[str, Any]) -> str:
    state_key = update["state_key"]
    op = update["operation"]
    payload = update["payload"]
    current = workspace.states[state_key]
    if op == "merge_root":
        workspace.states[state_key] = deep_merge(current, payload)
    elif op == "replace_root":
        workspace.states[state_key] = deepcopy(payload)
    elif op == "append_items":
        if not isinstance(payload, list):
            raise ValueError(f"append_items expects list payload for state {state_key}")
        workspace.states[state_key] = _append_items(state_key, current, payload)
    else:
        raise ValueError(f"Unsupported state update op: {op}")
    workspace.save_state(state_key)
    return f"state:{state_key}"


def _apply_task_updates(workspace: WorkspaceSnapshot, updates: list[dict[str, Any]]) -> list[str]:
    changes: list[str] = []
    task_index = {task.get("task_id"): task for task in workspace.task_graph.get("tasks", [])}
    for update in updates:
        task_id = update["task_id"]
        task = task_index.get(task_id)
        if task is None:
            raise ValueError(f"Unknown task_id in task_updates: {task_id}")
        task["status"] = update["status"]
        if update.get("note"):
            task["notes"] = update["note"]
        if update.get("patch"):
            task.update(deepcopy(update["patch"]))
        task["updated_at"] = now_iso()
        changes.append(f"task:{task_id}")
    if updates:
        workspace.save_state("task_graph")
    return changes


def _update_session_apply_metadata(
    workspace: WorkspaceSnapshot,
    session_id: str | None,
    *,
    action_plan: dict[str, Any],
    guardrail_status: str,
    apply_change_count: int = 0,
) -> None:
    if not session_id:
        return
    workspace.update_session(
        session_id,
        guardrail_status=guardrail_status,
        action_plan_hash=json_hash(action_plan),
        tool_call_count=len(action_plan.get("tool_calls", [])),
        apply_change_count=apply_change_count,
    )



def apply_action_plan(
    workspace: WorkspaceSnapshot,
    action_plan: dict[str, Any],
    expected_agent: str | None = None,
    provider_meta: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    guardrail_result = validate_action_plan(workspace, action_plan, expected_agent=expected_agent)
    log_guardrail_result(workspace, action_plan, guardrail_result)
    session_id = (provider_meta or {}).get("session_id")
    if not guardrail_result.ok:
        _update_session_apply_metadata(workspace, session_id, action_plan=action_plan, guardrail_status="fail", apply_change_count=0)
        raise PermissionError("\n".join(guardrail_result.errors))

    changes: list[str] = []
    if dry_run:
        _update_session_apply_metadata(workspace, session_id, action_plan=action_plan, guardrail_status="pass", apply_change_count=0)
        return {"changes": changes, "warnings": guardrail_result.warnings, "guardrails": guardrail_result.__dict__}

    for update in action_plan.get("state_updates", []):
        changes.append(_apply_state_update(workspace, update))

    for update in action_plan.get("note_updates", []):
        workspace.write_note(update["path"], update["content"], mode=update["mode"])
        changes.append(f"note:{update['path']}")

    changes.extend(_apply_task_updates(workspace, action_plan.get("task_updates", [])))

    for request in action_plan.get("requested_gates", []):
        message = execute_tool(
            workspace,
            "request_gate",
            {"gate_id": request["gate_id"], "reason": request["reason"]},
            actor=action_plan["agent"],
            profile=action_plan["profile"],
        )
        changes.append(f"tool:{message}")

    for tool_call in action_plan.get("tool_calls", []):
        message = execute_tool(
            workspace,
            tool_call["tool"],
            tool_call["arguments"],
            actor=action_plan["agent"],
            profile=action_plan["profile"],
        )
        changes.append(f"tool:{message}")

    runtime = workspace.runtime
    runtime["last_agent"] = action_plan.get("agent")
    runtime["last_profile"] = action_plan.get("profile")
    runtime["last_summary"] = action_plan.get("summary")
    runtime["last_provider"] = (provider_meta or {}).get("provider")
    runtime["last_run_at"] = now_iso()
    if session_id:
        runtime["last_session_id"] = session_id
    if provider_meta and provider_meta.get("response_id"):
        key = f"{action_plan.get('agent')}:{action_plan.get('profile')}"
        runtime.setdefault("continuations", {})
        runtime["continuations"][key] = {
            "response_id": provider_meta["response_id"],
            "provider": provider_meta.get("provider"),
            "mode": provider_meta.get("mode"),
            "updated_at": now_iso(),
        }
    workspace.save_state("runtime")

    _update_session_apply_metadata(workspace, session_id, action_plan=action_plan, guardrail_status="pass", apply_change_count=len(changes))

    trace_payload = {
        "timestamp": now_iso(),
        "session_id": session_id,
        "agent": action_plan.get("agent"),
        "profile": action_plan.get("profile"),
        "summary": action_plan.get("summary"),
        "changes": changes,
        "warnings": action_plan.get("warnings", []),
        "recommendations": action_plan.get("recommendations", []),
        "provider_meta": provider_meta or {},
        "stage_decision": action_plan.get("stage_decision", {}),
        "guardrails": {"status": "pass", "warnings": guardrail_result.warnings},
        "action_plan_hash": json_hash(action_plan),
    }
    workspace.append_log("trace.jsonl", trace_payload)
    workspace.log_event(
        "action_plan_applied",
        agent=action_plan.get("agent"),
        profile=action_plan.get("profile"),
        change_count=len(changes),
        summary=action_plan.get("summary"),
        session_id=session_id,
        tool_call_count=len(action_plan.get("tool_calls", [])),
    )
    sync_project_sqlite(workspace.root)
    return {"changes": changes, "warnings": guardrail_result.warnings, "guardrails": guardrail_result.__dict__}
