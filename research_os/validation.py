from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import load_json, lookup_path, sha256_file
from .planner import build_plan, load_stage_machine, sync_task_graph
from .scheduler import build_scheduler_snapshot
from .workspace import LEGACY_STATE_FILES, STATE_FILES, WorkspaceSnapshot


VALID_RUN_STATUSES = {"planned", "queued", "leased", "running", "retryable", "blocked", "succeeded", "failed", "cancelled"}
VALID_EVAL_STATUSES = {"pass", "fail", "warn", "informational", None}


def _unique(seq: list[Any]) -> set[Any]:
    return {item for item in seq if item is not None}


def _validate_expected_artifacts(run_id: str, request: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    items = request.get("expected_artifacts", []) or []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            path = item
        elif isinstance(item, dict):
            path = item.get("path")
            if item.get("required") is not None and not isinstance(item.get("required"), bool):
                errors.append(f"Run {run_id} expected_artifacts.required must be boolean")
            if item.get("promote_to_artifact_registry") is not None and not isinstance(item.get("promote_to_artifact_registry"), bool):
                errors.append(f"Run {run_id} expected_artifacts.promote_to_artifact_registry must be boolean")
        else:
            errors.append(f"Run {run_id} expected_artifacts entries must be strings or objects")
            continue
        if not path:
            errors.append(f"Run {run_id} expected_artifacts entry missing path")
            continue
        if path in seen:
            warnings.append(f"Run {run_id} has duplicate expected_artifacts path {path}")
        seen.add(path)


def validate_workspace(project_dir: str | Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    root = Path(project_dir).resolve()

    for rel in ["state", "notes", "logs", "runs", "db", "reports"]:
        if not (root / rel).exists():
            errors.append(f"Missing directory: {rel}")

    workspace = WorkspaceSnapshot.load(root)
    for key, rel in STATE_FILES.items():
        if not (root / rel).exists():
            errors.append(f"Missing state file: {rel}")

    legacy_queue_path = root / LEGACY_STATE_FILES["run_queue"]
    if legacy_queue_path.exists():
        warnings.append("Legacy state/run_queue.json still exists. V4.8 uses state/run_registry.json as the canonical runtime state.")

    stage_machine = load_stage_machine()
    stage_names = {item["stage"] for item in stage_machine.get("stages", [])}
    if workspace.current_stage not in stage_names:
        errors.append(f"Unknown current_stage: {workspace.current_stage}")

    # task graph
    all_task_ids = [task.get("task_id") for task in workspace.task_graph.get("tasks", [])]
    known_tasks = _unique(all_task_ids)
    if len(known_tasks) != len([tid for tid in all_task_ids if tid]):
        errors.append("Duplicate or missing task_id found in task_graph.")
    for task in workspace.task_graph.get("tasks", []):
        task_id = task.get("task_id")
        if not task_id:
            errors.append("Task missing task_id")
            continue
        if task.get("stage") not in stage_names:
            errors.append(f"Task {task_id} has unknown stage {task.get('stage')}")
        for dep in task.get("depends_on", []):
            if dep not in known_tasks:
                errors.append(f"Task {task_id} depends on unknown task {dep}")

    # claims/results/evidence consistency
    claim_ids = _unique([item.get("claim_id") for item in workspace.claims.get("claims", [])])
    evidence_ids = _unique([item.get("evidence_id") for item in workspace.evidence_registry.get("items", [])])
    result_ids = _unique([item.get("result_id") for item in workspace.results_registry.get("results", [])])

    for claim in workspace.claims.get("claims", []):
        cid = claim.get("claim_id")
        for ref in claim.get("evidence_refs", []):
            if ref not in evidence_ids:
                warnings.append(f"Claim {cid} references missing evidence_id {ref}")
        if claim.get("status") in {"promoted", "locked"}:
            preferred_support = [run for run in workspace.run_registry.get("runs", []) if claim.get("claim_id") in run.get("claims_under_test", []) and run.get("selection", {}).get("status") == "preferred"]
            if not preferred_support:
                warnings.append(f"Claim {cid} is {claim.get('status')} but no preferred supporting run is recorded")

    # runs
    run_ids = workspace.list_runs()
    if len(set(run_ids)) != len(run_ids):
        errors.append("Duplicate run_id detected across run registry or run directories.")

    registry_ids = _unique([run.get("run_id") for run in workspace.run_registry.get("runs", [])])
    for run in workspace.run_registry.get("runs", []):
        run_id = run.get("run_id")
        if not run_id:
            errors.append("Run registry entry missing run_id")
            continue
        if run.get("status") not in VALID_RUN_STATUSES:
            errors.append(f"Run {run_id} has invalid status {run.get('status')}")
        if run.get("approval", {}).get("status") in {"pending", "requested", "rejected"} and run.get("status") == "queued":
            errors.append(f"Run {run_id} is queued even though approval is not cleared")
        if run.get("status") in {"leased", "running"} and not lookup_path(run, "lease.worker_id"):
            errors.append(f"Run {run_id} is {run.get('status')} but has no lease.worker_id")
        if run.get("cancel_requested") and run.get("status") in {"queued", "planned", "retryable"}:
            warnings.append(f"Run {run_id} has cancel_requested=true and should soon settle to cancelled")
        if run.get("status") == "succeeded" and run.get("evaluation_status") == "fail":
            warnings.append(f"Run {run_id} succeeded but its evaluation_status is fail")
        if run.get("task_id") and run.get("task_id") not in known_tasks:
            warnings.append(f"Run {run_id} references unknown task_id {run.get('task_id')}")
        for dep_id in run.get("depends_on_runs", []) or []:
            if dep_id not in run_ids:
                errors.append(f"Run {run_id} depends_on_runs unknown run_id {dep_id}")
        if not all(isinstance(label, str) for label in lookup_path(run, "worker_requirements.labels", [])):
            errors.append(f"Run {run_id} worker_requirements.labels must contain only strings")
        selector = run.get("selector", {}) or {}
        selection = run.get("selection", {}) or {}
        if selector and selector.get("group") in {None, ""}:
            errors.append(f"Run {run_id} selector.group missing")
        if selection.get("status") == "preferred" and run.get("status") != "succeeded":
            warnings.append(f"Run {run_id} is marked preferred but status is {run.get('status')}")
        if selection.get("group") in {None, ""}:
            warnings.append(f"Run {run_id} selection.group missing")

        manifest_path = root / run.get("manifest_path", f"runs/{run_id}/manifest.json")
        request_path = root / run.get("request_path", f"runs/{run_id}/request.json")
        metrics_path = root / run.get("metrics_path", f"runs/{run_id}/metrics.json")
        output_manifest_path = root / run.get("output_manifest_path", f"runs/{run_id}/output_manifest.json")
        if not manifest_path.exists():
            errors.append(f"Run missing manifest.json: {run_id}")
        if not request_path.exists():
            warnings.append(f"Run missing request.json: {run_id}")
            request = {}
        else:
            request = load_json(request_path, {})
            _validate_expected_artifacts(run_id, request, errors, warnings)
        if run.get("status") == "succeeded" and not metrics_path.exists():
            warnings.append(f"Succeeded run missing metrics.json: {run_id}")
        if output_manifest_path.exists():
            output_manifest = load_json(output_manifest_path, {"files": []})
            for file_item in output_manifest.get("files", []):
                path = root / "runs" / run_id / file_item.get("path", "")
                if path.exists() and file_item.get("sha256"):
                    actual = sha256_file(path)
                    if actual != file_item.get("sha256"):
                        errors.append(f"Run {run_id} output_manifest sha256 mismatch for {file_item.get('path')}")
                elif file_item.get("path"):
                    warnings.append(f"Run {run_id} output_manifest references missing file {file_item.get('path')}")
                if file_item.get("promote_to_artifact_registry") and not file_item.get("provenance"):
                    warnings.append(f"Run {run_id} promoted artifact {file_item.get('path')} missing provenance in output_manifest")

        for rid in run.get("result_ids", []):
            if rid not in result_ids:
                warnings.append(f"Run {run_id} references missing result_id {rid}")

    for run_id in run_ids:
        if run_id not in registry_ids:
            warnings.append(f"Run directory {run_id} exists but run_registry has no entry. Workspace will attempt to hydrate it dynamically.")

    # results and provenance
    for result in workspace.results_registry.get("results", []):
        rid = result.get("result_id")
        if result.get("claim_id") and result["claim_id"] not in claim_ids:
            warnings.append(f"Result {rid} references missing claim_id {result['claim_id']}")
        if result.get("run_id") and result["run_id"] not in run_ids:
            warnings.append(f"Result {rid} references missing run_id {result['run_id']}")
        if not result.get("provenance"):
            warnings.append(f"Result {rid} has no provenance block")

    # evaluations
    seen_eval_keys: set[tuple[str, str, str]] = set()
    for evaluation in workspace.evaluation_registry.get("evaluations", []):
        target_type = evaluation.get("target_type")
        target_id = evaluation.get("target_id")
        key = (str(target_type), str(target_id), str(evaluation.get("evaluator")))
        if key in seen_eval_keys:
            warnings.append(f"Duplicate evaluation key detected: {key}")
        seen_eval_keys.add(key)
        if target_type == "run" and target_id not in run_ids:
            warnings.append(f"Evaluation {evaluation.get('evaluation_id')} references missing run {target_id}")
        if evaluation.get("status") not in VALID_EVAL_STATUSES:
            warnings.append(f"Evaluation {evaluation.get('evaluation_id')} has unexpected status {evaluation.get('status')}")

    # artifacts
    for artifact in workspace.artifact_registry.get("items", []):
        if artifact.get("run_id") and artifact.get("run_id") not in run_ids:
            warnings.append(f"Artifact {artifact.get('name')} references missing run_id {artifact.get('run_id')}")
        if artifact.get("path") and not (root / artifact.get("path")).exists():
            warnings.append(f"Artifact {artifact.get('name')} path not found on disk: {artifact.get('path')}")

    # sessions
    session_ids = [item.get("session_id") for item in workspace.session_registry.get("sessions", [])]
    if len(_unique(session_ids)) != len([sid for sid in session_ids if sid]):
        errors.append("Duplicate or missing session_id found in session_registry")
    known_session_ids = _unique(session_ids)
    for session in workspace.session_registry.get("sessions", []):
        if session.get("parent_session_id") and session.get("parent_session_id") not in known_session_ids:
            warnings.append(f"Session {session.get('session_id')} parent_session_id not found: {session.get('parent_session_id')}")

    if workspace.current_stage in {"write", "audit"} and workspace.metrics_summary()["result_count"] < 1:
        warnings.append("Project is in write/audit but results_registry is empty.")
    if workspace.current_stage in {"write", "audit"} and workspace.metrics_summary()["evaluation_failures"] > 0:
        warnings.append("Project is in write/audit while there are failing run evaluations.")

    sync_task_graph(workspace)
    plan = build_plan(workspace, persist=False)
    scheduler = build_scheduler_snapshot(workspace, worker_labels=[])
    if plan["requested_gates"]:
        warnings.append("There are requested gates pending approval.")
    if plan["runtime_backlog"]:
        warnings.append("Runtime backlog is non-empty; some queued/leased/running/retryable/blocked runs still need attention.")
    if scheduler.get("summary", {}).get("dispatchable_runs", 0) > 0 and plan.get("recommended_agent") != "execution":
        warnings.append("Scheduler has dispatchable runs but planner did not prioritize execution; inspect handoff heuristics.")

    return errors, warnings
