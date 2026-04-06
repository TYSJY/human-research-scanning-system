from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from .common import coerce_str_list, load_json, lookup_path, now_iso, resource_path
from .planner import build_plan
from .workspace import WorkspaceSnapshot


DEFAULT_BLOCKED_SHELL_PATTERNS = [
    "rm -rf /",
    "sudo ",
    "mkfs",
    "dd if=",
    ">:",
]
DEFAULT_APPROVAL_PATTERNS = [
    "curl ",
    "wget ",
    "ssh ",
    "scp ",
    "rsync ",
    "pip install ",
    "apt-get ",
]
DEFAULT_PROTECTED_STATE_KEYS = {"run_registry", "results_registry", "evaluation_registry", "session_registry"}


@dataclass
class GuardrailResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def load_agent_spec(agent_name: str) -> dict[str, Any]:
    return load_json(resource_path("control_plane", "agents", f"{agent_name}.json"), {})


def load_guardrail_policy() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "guardrail_policy.json"), {})


def load_evaluator_registry() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "evaluator_registry.json"), {"evaluators": []})


def _contains_promoted_status(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "status" and value in {"promoted", "locked"}:
                return True
            if _contains_promoted_status(value):
                return True
    if isinstance(payload, list):
        return any(_contains_promoted_status(item) for item in payload)
    return False


def _path_allowed(path: str, allowed_patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in allowed_patterns)


def _record(result: GuardrailResult, kind: str, status: str, message: str) -> None:
    result.checks.append({"kind": kind, "status": status, "message": message})


def assess_run_request(workspace: WorkspaceSnapshot, manifest: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    policy = load_guardrail_policy()
    risk_tags: list[str] = []
    warnings: list[str] = []
    blocked: list[str] = []
    approval_required = bool(lookup_path(request, "approval.required", False))
    executor = request.get("executor", "manual")
    timeout_sec = int(request.get("timeout_sec", 0) or 0)

    if executor not in {"manual", "shell", "external"}:
        blocked.append(f"Unsupported executor: {executor}")

    if executor == "shell":
        command = request.get("command", [])
        if isinstance(command, str):
            if not policy.get("allow_run_command_as_string", False):
                blocked.append("String shell command is disabled; use a JSON array command.")
        elif not isinstance(command, list) or not command:
            blocked.append("Shell executor requires a non-empty command array.")
        joined = " ".join(command) if isinstance(command, list) else str(command)
        joined_lower = joined.lower()
        for pattern in policy.get("blocked_shell_patterns", DEFAULT_BLOCKED_SHELL_PATTERNS):
            if pattern.lower() in joined_lower:
                blocked.append(f"Blocked shell pattern detected: {pattern}")
        for pattern in policy.get("approval_required_shell_patterns", DEFAULT_APPROVAL_PATTERNS):
            if pattern.lower() in joined_lower:
                risk_tags.append(f"shell:{pattern.strip()}")
                approval_required = True

    if timeout_sec > int(policy.get("approval_required_timeout_sec", 7200)):
        risk_tags.append("long_timeout")
        approval_required = True

    resource_budget = request.get("resource_budget", {})
    estimated_gpu_hours = float(resource_budget.get("estimated_gpu_hours", 0) or 0)
    if estimated_gpu_hours > float(policy.get("approval_required_gpu_hours", 8)):
        risk_tags.append("large_gpu_budget")
        approval_required = True

    if manifest.get("model") in {"replace-me", "replace-with-your-model", None, ""}:
        blocked.append("manifest.model is placeholder.")
    if manifest.get("dataset") in {"replace-me", "replace-with-your-dataset", None, ""}:
        blocked.append("manifest.dataset is placeholder.")
    if not manifest.get("question"):
        blocked.append("manifest.question is missing.")

    expected_artifacts = request.get("expected_artifacts", []) or []
    if expected_artifacts and not isinstance(expected_artifacts, list):
        blocked.append("request.expected_artifacts must be a list.")
    if isinstance(expected_artifacts, list):
        seen_paths: set[str] = set()
        for item in expected_artifacts:
            if isinstance(item, str):
                item_path = item
            elif isinstance(item, dict):
                item_path = item.get("path")
                if item_path and not isinstance(item_path, str):
                    blocked.append("expected_artifacts.path must be a string.")
                if item.get("kind") is not None and not isinstance(item.get("kind"), str):
                    blocked.append("expected_artifacts.kind must be a string.")
                if item.get("required") is not None and not isinstance(item.get("required"), bool):
                    blocked.append("expected_artifacts.required must be boolean.")
                if item.get("promote_to_artifact_registry") is not None and not isinstance(item.get("promote_to_artifact_registry"), bool):
                    blocked.append("expected_artifacts.promote_to_artifact_registry must be boolean.")
            else:
                blocked.append("expected_artifacts entries must be strings or objects.")
                continue
            if not item_path:
                blocked.append("expected_artifacts entry missing path.")
                continue
            if item_path in seen_paths:
                blocked.append(f"duplicate expected_artifacts path: {item_path}")
            seen_paths.add(item_path)

    worker_labels = coerce_str_list(lookup_path(request, "worker_requirements.labels", []))
    if len(worker_labels) != len(set(worker_labels)):
        warnings.append("worker_requirements.labels contains duplicates and will be normalized.")

    selector = request.get("selector", {}) or {}
    if selector and not isinstance(selector, dict):
        blocked.append("request.selector must be an object.")
    elif selector:
        if selector.get("group") in {None, ""}:
            blocked.append("request.selector.group is required when selector is provided.")
        min_score = selector.get("min_score_to_promote")
        if min_score is not None and not isinstance(min_score, (int, float)):
            blocked.append("request.selector.min_score_to_promote must be numeric.")
        if min_score is not None and not (0 <= float(min_score) <= 100):
            blocked.append("request.selector.min_score_to_promote must be between 0 and 100.")
        if selector.get("stop_after_preferred") is not None and not isinstance(selector.get("stop_after_preferred"), bool):
            blocked.append("request.selector.stop_after_preferred must be boolean.")

    return {
        "approval_required": approval_required,
        "risk_tags": sorted(set(risk_tags)),
        "warnings": warnings,
        "blocked_reasons": blocked,
    }


def _known_claims(workspace: WorkspaceSnapshot) -> set[str]:
    return {item.get("claim_id") for item in workspace.claims.get("claims", []) if item.get("claim_id")}


def _run_supports_claim(workspace: WorkspaceSnapshot, claim_id: str) -> list[dict[str, Any]]:
    supporting: list[dict[str, Any]] = []
    for run in workspace.run_registry.get("runs", []):
        if claim_id in set(run.get("claims_under_test", []) or []):
            supporting.append(run)
            continue
        for result in workspace.results_registry.get("results", []):
            if result.get("run_id") == run.get("run_id") and result.get("claim_id") == claim_id:
                supporting.append(run)
                break
    return supporting


def _has_preferred_supporting_run(workspace: WorkspaceSnapshot, claim_id: str) -> bool:
    policy = load_guardrail_policy()
    min_score = float(policy.get("min_run_score_to_promote_claim", 75) or 75)
    for run in _run_supports_claim(workspace, claim_id):
        selection = run.get("selection", {})
        score = selection.get("score")
        if run.get("status") == "succeeded" and run.get("evaluation_status") == "pass" and selection.get("status") == "preferred":
            if score is None or float(score) >= min_score:
                return True
    return False


def _validate_claims_payload(workspace: WorkspaceSnapshot, payload: Any, result: GuardrailResult) -> None:
    policy = load_guardrail_policy()
    claims = payload.get("claims", []) if isinstance(payload, dict) else []
    known_evidence = {item.get("evidence_id") for item in workspace.evidence_registry.get("items", [])}
    min_refs = policy.get("min_evidence_refs_per_claim", 2)
    seen: set[str] = set()
    for claim in claims:
        claim_id = claim.get("claim_id")
        if not claim_id:
            result.errors.append("claim payload missing claim_id")
            continue
        if claim_id in seen:
            result.errors.append(f"duplicate claim_id in payload: {claim_id}")
        seen.add(claim_id)
        evidence_refs = claim.get("evidence_refs", [])
        existing_refs = [ref for ref in evidence_refs if ref in known_evidence]
        if claim.get("status") in {"promoted", "locked"} and len(existing_refs) < min_refs:
            result.errors.append(f"Claim {claim_id} requires at least {min_refs} valid evidence_refs before promotion/lock.")
        if claim.get("status") in {"promoted", "locked"} and not claim.get("acceptance_checks"):
            result.errors.append(f"Claim {claim_id} must define acceptance_checks before promotion/lock.")
        elif not claim.get("acceptance_checks"):
            result.warnings.append(f"Claim {claim_id} has no acceptance_checks yet.")
        if policy.get("require_preferred_run_for_promoted_claims", True) and claim.get("status") in {"promoted", "locked"}:
            if not _has_preferred_supporting_run(workspace, claim_id):
                result.errors.append(f"Claim {claim_id} cannot be promoted/locked without a preferred supporting run.")


def _validate_requested_gates(workspace: WorkspaceSnapshot, action_plan: dict[str, Any], result: GuardrailResult) -> None:
    known_gates = {gate.get("gate_id") for gate in workspace.stage_state.get("gates", [])}
    for request in action_plan.get("requested_gates", []):
        gate_id = request.get("gate_id")
        if gate_id not in known_gates and not str(gate_id).startswith("run_approval."):
            result.errors.append(f"requested_gates references unknown gate: {gate_id}")
        if not request.get("reason"):
            result.warnings.append(f"requested_gates missing reason for {gate_id}")


def _validate_state_updates(workspace: WorkspaceSnapshot, spec: dict[str, Any], action_plan: dict[str, Any], result: GuardrailResult) -> None:
    policy = load_guardrail_policy()
    protected_keys = set(policy.get("protected_state_write_keys", [])) or set(DEFAULT_PROTECTED_STATE_KEYS)
    agent = action_plan.get("agent")
    for update in action_plan.get("state_updates", []):
        state_key = update.get("state_key")
        if state_key not in spec.get("state_write_keys", []):
            result.errors.append(f"{agent} cannot write state key: {state_key}")
            continue
        if state_key in protected_keys:
            result.errors.append(f"{agent} cannot directly mutate protected state key: {state_key}; use canonical tools instead.")
            continue
        _record(result, "state_write", "pass", f"{agent} can write {state_key}")
        if state_key == "claims":
            _validate_claims_payload(workspace, update.get("payload"), result)
            if policy.get("require_claim_lock_for_promoted_claims") and _contains_promoted_status(update.get("payload")):
                if workspace.gate_status("claim_lock") != "approved":
                    result.errors.append("Promoted or locked claim requires claim_lock gate approval.")


def _validate_note_updates(workspace: WorkspaceSnapshot, spec: dict[str, Any], action_plan: dict[str, Any], result: GuardrailResult) -> None:
    policy = load_guardrail_policy()
    agent = action_plan.get("agent")
    metrics = workspace.metrics_summary()
    preferred_runs = metrics.get("preferred_runs", 0)
    for update in action_plan.get("note_updates", []):
        path = update.get("path", "")
        if not _path_allowed(path, spec.get("note_write_paths", [])):
            result.errors.append(f"{agent} cannot write note path: {path}")
            continue
        _record(result, "note_write", "pass", f"{agent} can write {path}")
        if path in policy.get("paper_paths_require_results", []) and metrics["result_count"] < 1:
            result.errors.append(f"Cannot update {path} before registering at least one real result.")
        if path in policy.get("paper_paths_require_green_evaluations", []) and metrics["evaluation_failures"] > 0:
            result.errors.append(f"Cannot update {path} while there are failing run evaluations.")
        if path in policy.get("paper_paths_require_preferred_runs", []) and preferred_runs < 1:
            result.errors.append(f"Cannot update {path} before at least one preferred run is selected.")


def _validate_create_run(workspace: WorkspaceSnapshot, run_id: str, manifest: dict[str, Any], request: dict[str, Any], result: GuardrailResult, created_run_ids: set[str]) -> None:
    known_claims = _known_claims(workspace)
    risk = assess_run_request(workspace, manifest, request)
    for blocked_reason in risk["blocked_reasons"]:
        result.errors.append(f"create_run[{run_id}]: {blocked_reason}")
    for warning in risk["warnings"]:
        result.warnings.append(f"create_run[{run_id}]: {warning}")
    if risk["approval_required"]:
        result.warnings.append(f"create_run[{run_id}] will require human approval before queueing.")

    request_task_id = request.get("task_id")
    if request_task_id:
        known_tasks = {item.get("task_id") for item in workspace.task_graph.get("tasks", [])}
        if request_task_id not in known_tasks:
            result.errors.append(f"create_run[{run_id}] references unknown task_id: {request_task_id}")

    depends_on_runs = coerce_str_list(request.get("depends_on_runs"))
    for dependency_id in depends_on_runs:
        if dependency_id not in workspace.list_runs() and dependency_id not in created_run_ids:
            result.errors.append(f"create_run[{run_id}] depends_on_runs references unknown run_id: {dependency_id}")

    session_id = request.get("created_from_session_id")
    if session_id:
        known_sessions = {item.get("session_id") for item in workspace.session_registry.get("sessions", [])}
        if session_id not in known_sessions:
            result.warnings.append(f"create_run[{run_id}] created_from_session_id not found in session_registry: {session_id}")

    selector = request.get("selector", {}) or {}
    if selector and selector.get("group") in {None, ""}:
        result.errors.append(f"create_run[{run_id}] selector.group is required.")

    worker_labels = lookup_path(request, "worker_requirements.labels", []) or []
    if worker_labels and not all(isinstance(item, str) for item in worker_labels):
        result.errors.append(f"create_run[{run_id}] worker_requirements.labels must be strings.")

    known_evaluators = {item.get("name") for item in load_evaluator_registry().get("evaluators", [])}
    for evaluator in request.get("evaluators", []) or []:
        if evaluator not in known_evaluators:
            result.errors.append(f"create_run[{run_id}] references unknown evaluator: {evaluator}")

    for spec_item in request.get("register_results", []):
        if not spec_item.get("result_id") or not spec_item.get("metric") or not spec_item.get("value_path"):
            result.errors.append(f"create_run[{run_id}] has invalid register_results entry: {spec_item}")
        claim_id = spec_item.get("claim_id")
        if claim_id and claim_id not in known_claims:
            result.errors.append(f"create_run[{run_id}] references unknown claim_id: {claim_id}")


def _validate_tool_calls(workspace: WorkspaceSnapshot, spec: dict[str, Any], action_plan: dict[str, Any], result: GuardrailResult) -> None:
    policy = load_guardrail_policy()
    plan = build_plan(workspace, persist=False)
    agent = action_plan.get("agent")
    created_run_ids = {call.get("arguments", {}).get("run_id") for call in action_plan.get("tool_calls", []) if call.get("tool") == "create_run"}
    stage_transition_call = None

    for call in action_plan.get("tool_calls", []):
        tool = call.get("tool")
        arguments = call.get("arguments", {})
        if tool not in spec.get("allowed_tools", []):
            result.errors.append(f"{agent} cannot call tool: {tool}")
            continue
        _record(result, "tool", "pass", f"{agent} can call tool {tool}")

        if tool == "transition_stage":
            stage_transition_call = call
            target = arguments.get("stage")
            if policy.get("block_stage_transition_without_exit_conditions", True):
                if not plan.get("advance_ready"):
                    result.errors.append(f"Cannot transition to {target}: current stage is not advance_ready.")
                elif target != plan.get("proposed_stage"):
                    result.errors.append(f"Cannot transition to {target}: expected {plan.get('proposed_stage')}.")
        elif tool == "request_gate":
            gate_id = arguments.get("gate_id")
            known_gates = {gate.get("gate_id") for gate in workspace.stage_state.get("gates", [])}
            if gate_id not in known_gates and not str(gate_id).startswith("run_approval."):
                result.errors.append(f"Unknown gate: {gate_id}")
        elif tool == "create_run":
            run_id = arguments.get("run_id")
            if not run_id:
                result.errors.append("create_run requires run_id")
                continue
            _validate_create_run(workspace, run_id, arguments.get("manifest", {}), arguments.get("request", {}), result, created_run_ids)
        elif tool == "queue_run":
            run_id = arguments.get("run_id")
            if run_id not in workspace.list_runs() and run_id not in created_run_ids:
                result.errors.append(f"queue_run references unknown run: {run_id}")
            else:
                target = workspace.get_run(run_id)
                if target and target.get("status") not in {"planned", "blocked", "retryable", "failed", "cancelled"}:
                    result.errors.append(f"queue_run[{run_id}] cannot queue run in status {target.get('status')}")
        elif tool == "register_result":
            run_id = arguments.get("run_id")
            metric = arguments.get("metric")
            if not run_id or (run_id not in workspace.list_runs() and run_id not in created_run_ids):
                result.errors.append("register_result requires an existing run_id")
            if not metric:
                result.errors.append("register_result requires metric")
            if policy.get("require_run_provenance_for_results") and not arguments.get("provenance"):
                result.errors.append("register_result requires provenance")
            claim_id = arguments.get("claim_id")
            if claim_id and claim_id not in _known_claims(workspace):
                result.errors.append(f"register_result references unknown claim_id: {claim_id}")
        elif tool == "register_artifact":
            if not arguments.get("name"):
                result.errors.append("register_artifact requires name")
            if arguments.get("run_id") and arguments.get("run_id") not in workspace.list_runs() and arguments.get("run_id") not in created_run_ids:
                result.errors.append(f"register_artifact references unknown run_id: {arguments.get('run_id')}")
        elif tool == "update_task":
            task_id = arguments.get("task_id")
            known_tasks = {item.get("task_id") for item in workspace.task_graph.get("tasks", [])}
            if task_id not in known_tasks:
                result.errors.append(f"update_task references unknown task_id: {task_id}")

    proposed = action_plan.get("stage_decision", {}).get("proposed_stage")
    current_stage = action_plan.get("stage_decision", {}).get("current_stage")
    if proposed and current_stage and proposed != current_stage and stage_transition_call is None:
        result.warnings.append("Action plan proposes a new stage but does not include transition_stage tool call.")


def validate_tool_call(workspace: WorkspaceSnapshot, tool: str, arguments: dict[str, Any], actor: str = "runtime", profile: str = "runtime") -> GuardrailResult:
    result = GuardrailResult()
    synthetic_agent = actor or "runtime"
    synthetic_spec = {"allowed_tools": [tool], "state_write_keys": ["*"], "note_paths": ["*"]}
    action_plan = {
        "agent": synthetic_agent,
        "profile": profile,
        "summary": f"direct tool invocation: {tool}",
        "stage_decision": {
            "current_stage": workspace.current_stage,
            "proposed_stage": workspace.current_stage,
            "advance_ready": False,
            "rationale": "direct tool invocation",
        },
        "tool_calls": [{"tool": tool, "arguments": arguments or {}}],
        "state_updates": [],
        "note_updates": [],
        "requested_gates": [],
    }
    _validate_tool_calls(workspace, synthetic_spec, action_plan, result)
    return result


def validate_action_plan(workspace: WorkspaceSnapshot, action_plan: dict[str, Any], expected_agent: str | None = None) -> GuardrailResult:
    result = GuardrailResult()
    plan = build_plan(workspace, persist=False)
    agent = action_plan.get("agent")
    spec = load_agent_spec(agent) if agent else {}

    if not agent:
        result.errors.append("Missing action_plan.agent")
        return result

    if expected_agent and agent != expected_agent:
        result.errors.append(f"Action plan agent mismatch: expected {expected_agent}, got {agent}")

    current_stage = workspace.current_stage
    stage_decision = action_plan.get("stage_decision", {})
    if stage_decision.get("current_stage") != current_stage:
        result.errors.append(f"stage_decision.current_stage mismatch: workspace={current_stage}, payload={stage_decision.get('current_stage')}")
    else:
        _record(result, "stage", "pass", f"Current stage matches: {current_stage}")

    _validate_requested_gates(workspace, action_plan, result)
    _validate_state_updates(workspace, spec, action_plan, result)
    _validate_note_updates(workspace, spec, action_plan, result)
    _validate_tool_calls(workspace, spec, action_plan, result)

    if not action_plan.get("summary"):
        result.errors.append("Action plan summary is empty.")
    if not action_plan.get("profile"):
        result.errors.append("Action plan profile is empty.")

    if plan.get("requested_gates") and not action_plan.get("requested_gates") and action_plan.get("agent") == "controller":
        result.warnings.append("Controller omitted requested_gates even though planner indicates pending gate requests.")

    return result


def log_guardrail_result(workspace: WorkspaceSnapshot, action_plan: dict[str, Any], guardrail_result: GuardrailResult) -> None:
    status = "pass" if guardrail_result.ok else "fail"
    workspace.append_log(
        "guardrails.jsonl",
        {
            "timestamp": now_iso(),
            "agent": action_plan.get("agent"),
            "profile": action_plan.get("profile"),
            "status": status,
            "errors": guardrail_result.errors,
            "warnings": guardrail_result.warnings,
            "checks": guardrail_result.checks,
            "summary": action_plan.get("summary"),
        },
    )
