from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .common import clamp_int, ensure_dir, iso_in, lookup_path, now_iso, parse_iso, save_json, sha256_file
from .evaluators import _update_run_selection, evaluate_run
from .scheduler import build_scheduler_snapshot, load_runtime_policy as load_scheduler_runtime_policy, select_dispatchable_runs
from .sqlite_sync import sync_project_sqlite
from .tools import execute_tool, queue_run as queue_run_tool
from .workspace import WorkspaceSnapshot


def load_runtime_policy() -> dict[str, Any]:
    return load_scheduler_runtime_policy()


def _load_executor_profiles(config_path: str | Path | None = None) -> dict[str, Any]:
    # Keep the public signature stable while defaulting to the checked-in profile file.
    resolved = Path(config_path).resolve() if config_path else Path(__file__).resolve().parents[1] / "configs" / "executor_profiles.example.json"
    try:
        return json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": {}}


def _merge_executor_profile(request: dict[str, Any], config_path: str | Path | None = None) -> dict[str, Any]:
    resolved = dict(request)
    profile_name = request.get("executor_profile")
    if not profile_name:
        return resolved
    profiles = _load_executor_profiles(config_path).get("profiles", {})
    profile = profiles.get(profile_name, {})
    env = dict(profile.get("env", {}))
    env.update(request.get("env", {}))
    resolved["env"] = env
    if not resolved.get("cwd_mode") and profile.get("cwd_mode"):
        resolved["cwd_mode"] = profile["cwd_mode"]
    if not resolved.get("timeout_sec") and profile.get("default_timeout_sec"):
        resolved["timeout_sec"] = profile["default_timeout_sec"]
    if not resolved.get("lease_ttl_sec") and profile.get("lease_ttl_sec"):
        resolved["lease_ttl_sec"] = profile["lease_ttl_sec"]
    if not resolved.get("heartbeat_sec") and profile.get("heartbeat_sec"):
        resolved["heartbeat_sec"] = profile["heartbeat_sec"]
    return resolved


def _resolved_retry_policy(workspace: WorkspaceSnapshot, request: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    base = dict(workspace.project.get("budgets", {}).get("runtime", {}).get("default_retry_policy", {}))
    base.update(run.get("retry_policy", {}))
    base.update(request.get("retry_policy", {}))
    base.setdefault("max_attempts", max(1, int(run.get("max_attempts", 1) or 1)))
    base.setdefault("retry_on", [])
    base.setdefault("backoff_sec", 0)
    base.setdefault("fail_on_evaluation_error", True)
    return base


def _reload_run_entry(project_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    fresh = WorkspaceSnapshot.load(project_dir)
    return fresh.get_run(run_id)


def _expected_artifact_specs(request: dict[str, Any], additional_paths: list[str] | None = None) -> list[dict[str, Any]]:
    raw_items = list(request.get("expected_artifacts", []) or [])
    specs: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, str):
            kind = "metrics" if item.endswith(".json") else "log" if item.endswith(".log") else "artifact"
            specs.append(
                {
                    "path": item,
                    "kind": kind,
                    "required": True,
                    "promote_to_artifact_registry": kind not in {"log"},
                }
            )
            continue
        if isinstance(item, dict) and item.get("path"):
            payload = dict(item)
            payload.setdefault("kind", "artifact")
            payload.setdefault("required", True)
            payload.setdefault("promote_to_artifact_registry", payload.get("kind") not in {"log"})
            specs.append(payload)
    if not specs:
        metrics_output = request.get("metrics_output", "metrics.json")
        specs = [
            {"path": "stdout.log", "kind": "log", "required": True, "promote_to_artifact_registry": False},
            {"path": "stderr.log", "kind": "log", "required": True, "promote_to_artifact_registry": False},
            {"path": metrics_output, "kind": "metrics", "required": True, "promote_to_artifact_registry": True},
        ]
    seen = {item.get("path") for item in specs}
    for rel in additional_paths or []:
        if rel and rel not in seen:
            specs.append({"path": rel, "kind": "artifact", "required": False, "promote_to_artifact_registry": True})
            seen.add(rel)
    return specs


def _build_output_manifest(
    workspace: WorkspaceSnapshot,
    run_id: str,
    request: dict[str, Any],
    *,
    worker_id: str | None = None,
    additional_paths: list[str] | None = None,
) -> dict[str, Any]:
    run_dir = workspace.run_dir(run_id)
    specs = _expected_artifact_specs(request, additional_paths=additional_paths)
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    generated_at = now_iso()
    for spec in specs:
        rel = spec.get("path")
        if not rel:
            continue
        path = run_dir / rel
        if path.exists() and path.is_file():
            files.append(
                {
                    "path": rel,
                    "kind": spec.get("kind", "artifact"),
                    "required": bool(spec.get("required", True)),
                    "promote_to_artifact_registry": bool(spec.get("promote_to_artifact_registry", False)),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "provenance": {
                        "run_id": run_id,
                        "worker_id": worker_id,
                        "generated_at": generated_at,
                    },
                }
            )
        elif spec.get("required", True):
            missing.append(rel)
    payload = {"run_id": run_id, "generated_at": generated_at, "files": files, "missing": missing}
    workspace.save_run_output_manifest(run_id, payload)
    return payload


def _promote_artifacts(
    workspace: WorkspaceSnapshot,
    run_id: str,
    output_manifest: dict[str, Any],
    worker_id: str,
) -> list[str]:
    promoted: list[str] = []
    for item in output_manifest.get("files", []):
        if not item.get("promote_to_artifact_registry"):
            continue
        name = f"{run_id}:{item.get('path')}"
        payload = {
            "name": name,
            "status": "ready",
            "owner": worker_id,
            "notes": f"Promoted from run {run_id}",
            "kind": item.get("kind"),
            "path": f"runs/{run_id}/{item.get('path')}",
            "run_id": run_id,
            "provenance": {
                "source": "run_output_manifest",
                "run_id": run_id,
                "worker_id": worker_id,
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
                "generated_at": output_manifest.get("generated_at"),
                "output_manifest_path": f"runs/{run_id}/output_manifest.json",
            },
        }
        execute_tool(workspace, "register_artifact", payload, actor="worker", profile="runtime")
        promoted.append(name)
    return promoted


def _heartbeat(workspace: WorkspaceSnapshot, run: dict[str, Any], worker_id: str, lease_ttl_sec: int) -> None:
    run["lease"] = {
        "worker_id": worker_id,
        "heartbeat_at": now_iso(),
        "lease_expires_at": iso_in(lease_ttl_sec),
    }
    run["last_heartbeat_at"] = run["lease"]["heartbeat_at"]
    workspace.save_state("run_registry")


def _update_last_attempt(run: dict[str, Any], **patch: Any) -> None:
    attempts = run.setdefault("attempts", [])
    if not attempts:
        attempts.append({"attempt": 1})
    attempts[-1].update(patch)
    run["attempt_count"] = len(attempts)


def _schedule_retry(workspace: WorkspaceSnapshot, run: dict[str, Any], reason: str, retry_policy: dict[str, Any]) -> str:
    max_attempts = clamp_int(retry_policy.get("max_attempts", run.get("max_attempts", 1)), default=1, minimum=1)
    backoff_sec = clamp_int(retry_policy.get("backoff_sec", 0), default=0, minimum=0)
    can_retry = int(run.get("attempt_count", 0) or 0) < max_attempts
    retry_keys = set(retry_policy.get("retry_on", []))
    if can_retry and reason in retry_keys:
        run["status"] = "retryable"
        run["retry_count"] = int(run.get("attempt_count", 0) or 0)
        run["retry_at"] = iso_in(backoff_sec)
        run["last_error"] = reason
        run["lease"] = {}
        workspace.save_state("run_registry")
        return "retryable"
    run["status"] = "failed"
    run["retry_at"] = None
    run["last_error"] = reason
    run["lease"] = {}
    workspace.save_state("run_registry")
    return "failed"


def reap_expired_leases(workspace: WorkspaceSnapshot) -> int:
    changed = 0
    now_dt = parse_iso(now_iso())
    for run in workspace.run_registry.get("runs", []):
        if run.get("status") not in {"leased", "running"}:
            continue
        lease = run.get("lease", {})
        expires_at = parse_iso(lease.get("lease_expires_at"))
        if not expires_at or not now_dt or expires_at > now_dt:
            continue
        request = _merge_executor_profile(workspace.load_run_request(run["run_id"]))
        retry_policy = _resolved_retry_policy(workspace, request, run)
        _update_last_attempt(run, ended_at=now_iso(), status="lease_expired", error="lease_expired")
        _schedule_retry(workspace, run, "lease_expired", retry_policy)
        run["ended_at"] = now_iso()
        changed += 1
    if changed:
        workspace.log_event("lease_reaped", count=changed)
        sync_project_sqlite(workspace.root)
    return changed


def lease_next_run(workspace: WorkspaceSnapshot, worker_id: str, worker_labels: list[str] | None = None) -> dict[str, Any] | None:
    reap_expired_leases(workspace)
    dispatchable = select_dispatchable_runs(workspace, worker_labels=worker_labels or [], limit=1)
    if not dispatchable:
        return None
    selected = dispatchable[0]
    run = workspace.get_run(selected["run_id"])
    if run is None:
        return None
    request = _merge_executor_profile(workspace.load_run_request(run["run_id"]))
    lease_ttl_sec = clamp_int(
        request.get("lease_ttl_sec", workspace.project.get("budgets", {}).get("runtime", {}).get("lease_ttl_sec", 30)),
        default=30,
        minimum=5,
    )
    run["status"] = "leased"
    run["lease"] = {
        "worker_id": worker_id,
        "worker_labels": sorted(set(worker_labels or [])),
        "leased_at": now_iso(),
        "lease_expires_at": iso_in(lease_ttl_sec),
        "heartbeat_at": now_iso(),
        "dispatch_score": selected.get("score"),
        "dispatch_group": selected.get("queue_group"),
    }
    run["last_heartbeat_at"] = run["lease"]["heartbeat_at"]
    workspace.save_state("run_registry")
    workspace.runtime["last_worker_id"] = worker_id
    workspace.runtime["last_scheduler_summary"] = build_scheduler_snapshot(workspace, worker_labels=worker_labels or []).get("summary", {})
    workspace.save_state("runtime")
    workspace.log_event(
        "run_leased",
        run_id=run["run_id"],
        worker_id=worker_id,
        worker_labels=sorted(set(worker_labels or [])),
        dispatch_score=selected.get("score"),
        queue_group=selected.get("queue_group"),
    )
    return run


def _register_results_from_metrics(workspace: WorkspaceSnapshot, run_id: str, request: dict[str, Any], output_manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    metrics = workspace.load_run_metrics(run_id)
    registered: list[str] = []
    missing: list[str] = []
    output_files = {item.get("path"): item for item in output_manifest.get("files", [])}
    metrics_entry = output_files.get(request.get("metrics_output", "metrics.json"), {})
    for spec in request.get("register_results", []):
        value = lookup_path(metrics, spec.get("value_path", ""))
        if value is None:
            missing.append(spec.get("result_id", "missing"))
            continue
        payload = {
            "result_id": spec["result_id"],
            "run_id": run_id,
            "claim_id": spec.get("claim_id"),
            "metric": spec["metric"],
            "value": value,
            "notes": spec.get("notes", ""),
            "provenance": {
                "source": "executor_metrics",
                "value_path": spec["value_path"],
                "run_id": run_id,
                "metrics_output": request.get("metrics_output", "metrics.json"),
                "metrics_sha256": metrics_entry.get("sha256"),
                "output_manifest_path": f"runs/{run_id}/output_manifest.json",
            },
            "validation_status": "pass",
            "registered_at": now_iso(),
        }
        execute_tool(workspace, "register_result", payload, actor="worker", profile="runtime")
        registered.append(payload["result_id"])
    return registered, missing


def _resolved_cwd(workspace: WorkspaceSnapshot, run_id: str, request: dict[str, Any]) -> Path:
    mode = request.get("cwd_mode", "run_dir")
    if mode == "run_dir":
        return workspace.run_dir(run_id)
    if mode == "project_root":
        return workspace.root
    return Path(mode).resolve()


def _run_shell(workspace: WorkspaceSnapshot, run: dict[str, Any], worker_id: str, worker_labels: list[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    run_id = run["run_id"]
    request = _merge_executor_profile(workspace.load_run_request(run_id))
    retry_policy = _resolved_retry_policy(workspace, request, run)
    timeout_sec = clamp_int(request.get("timeout_sec", workspace.project.get("budgets", {}).get("runtime", {}).get("default_timeout_sec", 1800)), default=1800, minimum=1)
    heartbeat_sec = clamp_int(request.get("heartbeat_sec", workspace.project.get("budgets", {}).get("runtime", {}).get("heartbeat_sec", 2)), default=2, minimum=1)
    lease_ttl_sec = clamp_int(request.get("lease_ttl_sec", workspace.project.get("budgets", {}).get("runtime", {}).get("lease_ttl_sec", 30)), default=30, minimum=5)
    command = request.get("command", [])
    cwd = _resolved_cwd(workspace, run_id, request)
    env = os.environ.copy()
    env.update(request.get("env", {}))

    if dry_run:
        return {"run_id": run_id, "status": "dry_run", "command": command, "cwd": str(cwd), "worker_labels": sorted(set(worker_labels or []))}

    run["status"] = "running"
    run["started_at"] = run.get("started_at") or now_iso()
    run["lease"] = {
        "worker_id": worker_id,
        "worker_labels": sorted(set(worker_labels or [])),
        "leased_at": run.get("lease", {}).get("leased_at") or now_iso(),
        "lease_expires_at": iso_in(lease_ttl_sec),
        "heartbeat_at": now_iso(),
    }
    run["last_heartbeat_at"] = run["lease"]["heartbeat_at"]
    attempt_no = int(run.get("attempt_count", 0) or 0) + 1
    run.setdefault("attempts", []).append(
        {
            "attempt": attempt_no,
            "status": "running",
            "started_at": now_iso(),
            "worker_id": worker_id,
            "worker_labels": sorted(set(worker_labels or [])),
            "executor": "shell",
            "cwd": str(cwd),
        }
    )
    run["attempt_count"] = len(run.get("attempts", []))
    workspace.save_state("run_registry")
    workspace.log_event("run_started", run_id=run_id, worker_id=worker_id, worker_labels=sorted(set(worker_labels or [])), executor="shell", command=command)

    stdout_path = workspace.run_dir(run_id) / "stdout.log"
    stderr_path = workspace.run_dir(run_id) / "stderr.log"
    ensure_dir(stdout_path.parent)
    reason = None
    exit_code = None
    start_monotonic = time.monotonic()
    next_heartbeat = start_monotonic + heartbeat_sec

    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            shell=isinstance(command, str),
        )
        while True:
            current = proc.poll()
            if current is not None:
                exit_code = current
                break
            now_monotonic = time.monotonic()
            if now_monotonic >= next_heartbeat:
                _heartbeat(workspace, run, worker_id, lease_ttl_sec)
                next_heartbeat = now_monotonic + heartbeat_sec
            fresh = _reload_run_entry(workspace.root, run_id)
            if fresh and fresh.get("cancel_requested"):
                reason = "cancel_requested"
                proc.terminate()
                break
            if now_monotonic - start_monotonic > timeout_sec:
                reason = "timeout"
                proc.terminate()
                break
            time.sleep(0.25)

        if reason in {"cancel_requested", "timeout"} and proc.poll() is None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        if exit_code is None:
            exit_code = proc.poll()

    metrics_rel = request.get("metrics_output", "metrics.json")
    metrics_path = workspace.run_dir(run_id) / metrics_rel
    if not metrics_path.exists():
        save_json(metrics_path, {"metrics": {}})
    output_manifest = _build_output_manifest(workspace, run_id, request, worker_id=worker_id)
    promoted_artifacts = _promote_artifacts(workspace, run_id, output_manifest, worker_id=worker_id)
    registered_results, missing_results = _register_results_from_metrics(workspace, run_id, request, output_manifest)
    eval_summary = evaluate_run(workspace, run_id, persist=True)
    run = workspace.get_run(run_id) or run

    final_status = "succeeded"
    if reason == "cancel_requested":
        run["status"] = "cancelled"
        final_status = "cancelled"
    elif reason == "timeout":
        final_status = _schedule_retry(workspace, run, "timeout", retry_policy)
    elif int(exit_code or 0) != 0:
        final_status = _schedule_retry(workspace, run, "non_zero_exit", retry_policy)
    elif missing_results:
        final_status = _schedule_retry(workspace, run, "evaluator_fail", retry_policy) if "evaluator_fail" in set(retry_policy.get("retry_on", [])) else "failed"
        if final_status == "failed":
            run["status"] = "failed"
    elif eval_summary["overall_status"] == "fail" and retry_policy.get("fail_on_evaluation_error", True):
        final_status = _schedule_retry(workspace, run, "evaluator_fail", retry_policy)
    else:
        run["status"] = "succeeded"

    run["ended_at"] = now_iso()
    run["lease"] = {}
    run["last_error"] = None if run.get("status") == "succeeded" else reason or ("non_zero_exit" if int(exit_code or 0) != 0 else "evaluator_fail")
    run["result_ids"] = sorted(set(run.get("result_ids", []) + registered_results))
    run["evaluation_status"] = eval_summary["overall_status"]
    _update_last_attempt(
        run,
        ended_at=run["ended_at"],
        status=run.get("status") if final_status == "succeeded" else final_status,
        exit_code=exit_code,
        error=run.get("last_error"),
        stdout_path="stdout.log",
        stderr_path="stderr.log",
        output_manifest_path="output_manifest.json",
        registered_results=registered_results,
        promoted_artifacts=promoted_artifacts,
    )
    if run.get("status") in {"succeeded", "cancelled", "failed"}:
        run["retry_at"] = None
    workspace.save_state("run_registry")
    _update_run_selection(workspace)
    workspace.log_event(
        "run_finished",
        run_id=run_id,
        worker_id=worker_id,
        worker_labels=sorted(set(worker_labels or [])),
        status=run.get("status"),
        exit_code=exit_code,
        reason=reason,
        registered_results=registered_results,
        promoted_artifacts=promoted_artifacts,
        evaluation_status=eval_summary["overall_status"],
        evaluation_score=eval_summary.get("overall_score"),
    )
    sync_project_sqlite(workspace.root)
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "exit_code": exit_code,
        "reason": reason,
        "registered_results": registered_results,
        "missing_results": missing_results,
        "promoted_artifacts": promoted_artifacts,
        "evaluation": eval_summary,
    }


def _dispatch_external(workspace: WorkspaceSnapshot, run: dict[str, Any], worker_id: str, worker_labels: list[str] | None = None) -> dict[str, Any]:
    run_id = run["run_id"]
    request = _merge_executor_profile(workspace.load_run_request(run_id))
    dispatch = {
        "run_id": run_id,
        "manifest": workspace.load_run_manifest(run_id),
        "request": request,
        "dispatched_at": now_iso(),
        "worker_id": worker_id,
        "worker_labels": sorted(set(worker_labels or [])),
    }
    save_json(workspace.run_dir(run_id) / "dispatch.json", dispatch)
    output_manifest = _build_output_manifest(workspace, run_id, request, worker_id=worker_id, additional_paths=["dispatch.json"])
    promoted_artifacts = _promote_artifacts(workspace, run_id, output_manifest, worker_id=worker_id)
    run["status"] = "blocked"
    run["blocked_reason"] = "awaiting_external_completion"
    run["lease"] = {}
    run.setdefault("attempts", []).append(
        {
            "attempt": int(run.get("attempt_count", 0) or 0) + 1,
            "status": "dispatched_external",
            "started_at": now_iso(),
            "ended_at": now_iso(),
            "worker_id": worker_id,
            "worker_labels": sorted(set(worker_labels or [])),
            "dispatch_path": "dispatch.json",
            "promoted_artifacts": promoted_artifacts,
        }
    )
    run["attempt_count"] = len(run.get("attempts", []))
    workspace.save_state("run_registry")
    workspace.log_event("run_dispatched_external", run_id=run_id, worker_id=worker_id, worker_labels=sorted(set(worker_labels or [])))
    sync_project_sqlite(workspace.root)
    return {"run_id": run_id, "status": "blocked", "reason": "awaiting_external_completion", "promoted_artifacts": promoted_artifacts}


def run_one(
    workspace: WorkspaceSnapshot,
    run_id: str,
    dry_run: bool = False,
    worker_id: str = "worker-local",
    worker_labels: list[str] | None = None,
) -> dict[str, Any]:
    reap_expired_leases(workspace)
    run = workspace.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Run not found: {run_id}")

    if run.get("status") not in {"leased", "queued", "retryable"}:
        return {"run_id": run_id, "status": run.get("status"), "message": "run not executable in current status"}

    if run.get("status") != "leased":
        dispatchable = {item.get("run_id"): item for item in select_dispatchable_runs(workspace, worker_labels=worker_labels or [], limit=50)}
        if run_id not in dispatchable:
            snapshot = build_scheduler_snapshot(workspace, worker_labels=worker_labels or [])
            waiting = {item.get("run_id"): item for item in snapshot.get("waiting", [])}
            return {
                "run_id": run_id,
                "status": run.get("status"),
                "message": "run is not dispatchable for this worker",
                "reasons": waiting.get(run_id, {}).get("reasons", ["not_dispatchable"]),
            }
        leased = lease_next_run(workspace, worker_id=worker_id, worker_labels=worker_labels or [])
        if not leased or leased.get("run_id") != run_id:
            return {"run_id": run_id, "status": run.get("status"), "message": "another run was leased first"}
        workspace = WorkspaceSnapshot.load(workspace.root)
        run = workspace.get_run(run_id) or run

    request = _merge_executor_profile(workspace.load_run_request(run_id))
    executor = request.get("executor", "manual")
    if executor == "manual":
        run["status"] = "blocked"
        run["blocked_reason"] = "manual_execution_required"
        run["lease"] = {}
        workspace.save_state("run_registry")
        workspace.log_event("run_blocked_manual", run_id=run_id)
        sync_project_sqlite(workspace.root)
        return {"run_id": run_id, "status": "blocked", "reason": "manual_execution_required"}

    if executor == "external":
        return _dispatch_external(workspace, run, worker_id=worker_id, worker_labels=worker_labels)

    return _run_shell(workspace, run, worker_id=worker_id, worker_labels=worker_labels, dry_run=dry_run)


def run_worker(
    project_dir: str | Path,
    worker_id: str = "worker-local",
    max_runs: int = 1,
    dry_run: bool = False,
    worker_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for _ in range(max_runs):
        workspace = WorkspaceSnapshot.load(project_dir)
        leased = lease_next_run(workspace, worker_id=worker_id, worker_labels=worker_labels or [])
        if not leased:
            break
        workspace = WorkspaceSnapshot.load(project_dir)
        results.append(run_one(workspace, leased["run_id"], dry_run=dry_run, worker_id=worker_id, worker_labels=worker_labels or []))
    return results


def run_pending(project_dir: str | Path, max_runs: int = 1, dry_run: bool = False) -> list[dict[str, Any]]:
    return run_worker(project_dir, worker_id="worker-local", max_runs=max_runs, dry_run=dry_run, worker_labels=[])


def approve_run(workspace: WorkspaceSnapshot, run_id: str, by: str = "human", note: str = "", queue_after: bool = False) -> dict[str, Any]:
    run = workspace.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown run_id: {run_id}")
    run.setdefault("approval", {})
    run["approval"].update({"status": "approved", "approved_by": by, "approved_at": now_iso(), "approved_note": note})
    if run.get("status") == "blocked" and run.get("blocked_reason") == "approval_required":
        run["status"] = "planned"
        run["blocked_reason"] = None
    workspace.save_state("run_registry")
    _update_run_selection(workspace)
    workspace.log_event("run_approved", run_id=run_id, by=by)
    if queue_after:
        queue_run_tool(workspace, {"run_id": run_id, "priority": run.get("priority", "normal")}, actor=by, profile="manual")
    sync_project_sqlite(workspace.root)
    return {"run_id": run_id, "approval_status": "approved", "queued": queue_after}


def cancel_run(workspace: WorkspaceSnapshot, run_id: str, by: str = "human", note: str = "") -> dict[str, Any]:
    run = workspace.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown run_id: {run_id}")
    run["cancel_requested"] = True
    run["cancel_requested_at"] = now_iso()
    run["cancel_requested_by"] = by
    if run.get("status") in {"planned", "queued", "retryable", "blocked", "leased"}:
        run["status"] = "cancelled"
        run["lease"] = {}
        run["blocked_reason"] = note or run.get("blocked_reason")
    workspace.save_state("run_registry")
    _update_run_selection(workspace)
    workspace.log_event("run_cancel_requested", run_id=run_id, by=by, note=note)
    sync_project_sqlite(workspace.root)
    return {"run_id": run_id, "status": run.get("status"), "cancel_requested": True}


def retry_run(workspace: WorkspaceSnapshot, run_id: str, by: str = "human", reset_attempts: bool = False) -> dict[str, Any]:
    run = workspace.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown run_id: {run_id}")
    if run.get("status") in {"running", "leased"}:
        raise ValueError(f"Run is active and cannot be retried now: {run_id}")
    run["cancel_requested"] = False
    run["cancel_requested_at"] = None
    run["blocked_reason"] = None
    run["last_error"] = None
    run["retry_at"] = None
    if reset_attempts:
        run["attempts"] = []
        run["attempt_count"] = 0
    run["status"] = "queued"
    run["queued_at"] = now_iso()
    workspace.save_state("run_registry")
    _update_run_selection(workspace)
    workspace.log_event("run_requeued", run_id=run_id, by=by)
    sync_project_sqlite(workspace.root)
    return {"run_id": run_id, "status": "queued"}


def ingest_run_output(
    workspace: WorkspaceSnapshot,
    run_id: str,
    status: str = "succeeded",
    metrics_file: str | Path | None = None,
    exit_code: int = 0,
    additional_artifacts: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    run = workspace.get_run(run_id)
    if run is None:
        raise ValueError(f"Unknown run_id: {run_id}")
    request = _merge_executor_profile(workspace.load_run_request(run_id))
    if metrics_file:
        src = Path(metrics_file).resolve()
        dst = workspace.run_dir(run_id) / request.get("metrics_output", "metrics.json")
        shutil.copy2(src, dst)
    output_manifest = _build_output_manifest(workspace, run_id, request, worker_id="external-ingest", additional_paths=additional_artifacts or [])
    promoted_artifacts = _promote_artifacts(workspace, run_id, output_manifest, worker_id="external-ingest")
    registered_results, missing_results = _register_results_from_metrics(workspace, run_id, request, output_manifest)
    eval_summary = evaluate_run(workspace, run_id, persist=True)
    run = workspace.get_run(run_id) or run
    run["status"] = status
    run["ended_at"] = now_iso()
    run["last_error"] = None if status == "succeeded" else note or "external_status"
    run["result_ids"] = sorted(set(run.get("result_ids", []) + registered_results))
    run["evaluation_status"] = eval_summary["overall_status"]
    run["lease"] = {}
    if not run.get("attempts"):
        run["attempts"] = [
            {
                "attempt": 1,
                "status": status,
                "started_at": run.get("started_at") or now_iso(),
                "ended_at": run["ended_at"],
                "exit_code": exit_code,
                "worker_id": "external-ingest",
                "promoted_artifacts": promoted_artifacts,
            }
        ]
    else:
        _update_last_attempt(
            run,
            status=status,
            ended_at=run["ended_at"],
            exit_code=exit_code,
            error=run.get("last_error"),
            promoted_artifacts=promoted_artifacts,
        )
    workspace.save_state("run_registry")
    _update_run_selection(workspace)
    workspace.log_event(
        "run_ingested",
        run_id=run_id,
        status=status,
        registered_results=registered_results,
        promoted_artifacts=promoted_artifacts,
        evaluation_status=eval_summary["overall_status"],
    )
    sync_project_sqlite(workspace.root)
    return {
        "run_id": run_id,
        "status": status,
        "registered_results": registered_results,
        "missing_results": missing_results,
        "promoted_artifacts": promoted_artifacts,
        "evaluation": eval_summary,
    }
