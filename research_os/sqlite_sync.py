from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .common import load_jsonl
from .workspace import WorkspaceSnapshot


SCHEMA = [
    "CREATE TABLE project (project_slug TEXT, title TEXT, owner TEXT, target_venue TEXT, current_goal TEXT, current_stage TEXT, version TEXT)",
    "CREATE TABLE gates (gate_id TEXT PRIMARY KEY, title TEXT, status TEXT, requested_at TEXT, approved_at TEXT, requested_by TEXT, approved_by TEXT)",
    "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, title TEXT, stage TEXT, agent TEXT, profile TEXT, priority TEXT, status TEXT, requires_gate TEXT, closure_rule TEXT, depends_on_json TEXT, notes TEXT, updated_at TEXT)",
    "CREATE TABLE evidence (evidence_id TEXT PRIMARY KEY, title TEXT, kind TEXT, notes TEXT, source_refs_json TEXT, recorded_at TEXT)",
    "CREATE TABLE baselines (baseline_id TEXT PRIMARY KEY, name TEXT, kind TEXT, notes TEXT, recorded_at TEXT)",
    "CREATE TABLE claims (claim_id TEXT PRIMARY KEY, text TEXT, status TEXT, success_metric TEXT, evidence_refs_json TEXT, acceptance_checks_json TEXT)",
    "CREATE TABLE runs (run_id TEXT PRIMARY KEY, status TEXT, priority TEXT, executor TEXT, task_id TEXT, queue_group TEXT, reasoning_profile TEXT, depends_on_runs_json TEXT, worker_requirements_json TEXT, created_at TEXT, created_by TEXT, created_from_session_id TEXT, queued_at TEXT, started_at TEXT, ended_at TEXT, attempt_count INTEGER, max_attempts INTEGER, retry_count INTEGER, retry_at TEXT, approval_required INTEGER, approval_status TEXT, approval_reason TEXT, risk_tags_json TEXT, blocked_reason TEXT, last_error TEXT, evaluation_status TEXT, last_evaluated_at TEXT, result_ids_json TEXT, claims_under_test_json TEXT, manifest_path TEXT, request_path TEXT, metrics_path TEXT, output_manifest_path TEXT, resource_budget_json TEXT, retry_policy_json TEXT, selector_json TEXT, selection_json TEXT, lease_json TEXT)",
    "CREATE TABLE run_attempts (run_id TEXT, attempt INTEGER, status TEXT, worker_id TEXT, started_at TEXT, ended_at TEXT, exit_code INTEGER, error TEXT, stdout_path TEXT, stderr_path TEXT, details_json TEXT, PRIMARY KEY (run_id, attempt))",
    "CREATE TABLE results (result_id TEXT PRIMARY KEY, run_id TEXT, claim_id TEXT, metric TEXT, value_json TEXT, notes TEXT, validation_status TEXT, provenance_json TEXT, registered_at TEXT)",
    "CREATE TABLE evaluations (evaluation_id TEXT PRIMARY KEY, target_type TEXT, target_id TEXT, evaluator TEXT, status TEXT, score REAL, weight REAL, summary TEXT, checks_json TEXT, details_json TEXT, created_at TEXT)",
    "CREATE TABLE artifacts (name TEXT PRIMARY KEY, status TEXT, owner TEXT, kind TEXT, path TEXT, run_id TEXT, notes TEXT, provenance_json TEXT, updated_at TEXT)",
    "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, sequence INTEGER, parent_session_id TEXT, provider TEXT, agent TEXT, profile TEXT, status TEXT, current_stage TEXT, handoff_reason TEXT, guardrail_status TEXT, action_plan_hash TEXT, initial_plan_hash TEXT, final_plan_hash TEXT, tool_call_count INTEGER, apply_change_count INTEGER, executor_run_count INTEGER, started_at TEXT, ended_at TEXT, user_context_json TEXT, provider_meta_json TEXT, result_json TEXT)",
    "CREATE TABLE events (timestamp TEXT, event_type TEXT, payload_json TEXT)",
    "CREATE TABLE traces (timestamp TEXT, session_id TEXT, agent TEXT, profile TEXT, summary TEXT, changes_json TEXT, warnings_json TEXT, provider_meta_json TEXT, stage_decision_json TEXT, guardrails_json TEXT, action_plan_hash TEXT)",
]


def _j(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def sync_project_sqlite(project_dir: str | Path, output: str | Path | None = None) -> Path:
    workspace = WorkspaceSnapshot.load(project_dir)
    out = Path(output).resolve() if output else workspace.root / "db" / "project.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    conn = sqlite3.connect(out)
    cur = conn.cursor()
    for stmt in SCHEMA:
        cur.execute(stmt)

    cur.execute(
        "INSERT INTO project VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            workspace.project.get("project_slug"),
            workspace.project.get("title"),
            workspace.project.get("owner"),
            workspace.project.get("target_venue"),
            workspace.project.get("current_goal"),
            workspace.current_stage,
            workspace.project.get("version"),
        ),
    )

    for gate in workspace.stage_state.get("gates", []):
        cur.execute(
            "INSERT INTO gates VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                gate.get("gate_id"),
                gate.get("title"),
                gate.get("status"),
                gate.get("requested_at"),
                gate.get("approved_at"),
                gate.get("requested_by"),
                gate.get("approved_by"),
            ),
        )

    for task in workspace.task_graph.get("tasks", []):
        cur.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.get("task_id"),
                task.get("title"),
                task.get("stage"),
                task.get("agent"),
                task.get("profile"),
                task.get("priority"),
                task.get("status"),
                task.get("requires_gate"),
                task.get("closure_rule"),
                _j(task.get("depends_on", [])),
                task.get("notes"),
                task.get("updated_at"),
            ),
        )

    for item in workspace.evidence_registry.get("items", []):
        cur.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.get("evidence_id"),
                item.get("title"),
                item.get("kind"),
                item.get("notes"),
                _j(item.get("source_refs", [])),
                item.get("recorded_at"),
            ),
        )

    for item in workspace.baseline_registry.get("items", []):
        cur.execute(
            "INSERT INTO baselines VALUES (?, ?, ?, ?, ?)",
            (
                item.get("baseline_id"),
                item.get("name"),
                item.get("kind"),
                item.get("notes"),
                item.get("recorded_at"),
            ),
        )

    for claim in workspace.claims.get("claims", []):
        cur.execute(
            "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?)",
            (
                claim.get("claim_id"),
                claim.get("text"),
                claim.get("status"),
                claim.get("success_metric"),
                _j(claim.get("evidence_refs", [])),
                _j(claim.get("acceptance_checks", [])),
            ),
        )

    for run in workspace.run_registry.get("runs", []):
        approval = run.get("approval", {})
        cur.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.get("run_id"),
                run.get("status"),
                run.get("priority"),
                run.get("executor"),
                run.get("task_id"),
                run.get("queue_group"),
                run.get("reasoning_profile"),
                _j(run.get("depends_on_runs", [])),
                _j(run.get("worker_requirements", {})),
                run.get("created_at"),
                run.get("created_by"),
                run.get("created_from_session_id"),
                run.get("queued_at"),
                run.get("started_at"),
                run.get("ended_at"),
                run.get("attempt_count"),
                run.get("max_attempts"),
                run.get("retry_count"),
                run.get("retry_at"),
                1 if approval.get("required") else 0,
                approval.get("status"),
                approval.get("reason"),
                _j(approval.get("risk_tags", [])),
                run.get("blocked_reason"),
                run.get("last_error"),
                run.get("evaluation_status"),
                run.get("last_evaluated_at"),
                _j(run.get("result_ids", [])),
                _j(run.get("claims_under_test", [])),
                run.get("manifest_path"),
                run.get("request_path"),
                run.get("metrics_path"),
                run.get("output_manifest_path"),
                _j(run.get("resource_budget", {})),
                _j(run.get("retry_policy", {})),
                _j(run.get("selector", {})),
                _j(run.get("selection", {})),
                _j(run.get("lease", {})),
            ),
        )
        for attempt in run.get("attempts", []):
            cur.execute(
                "INSERT OR REPLACE INTO run_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.get("run_id"),
                    attempt.get("attempt"),
                    attempt.get("status"),
                    attempt.get("worker_id"),
                    attempt.get("started_at"),
                    attempt.get("ended_at"),
                    attempt.get("exit_code"),
                    attempt.get("error"),
                    attempt.get("stdout_path"),
                    attempt.get("stderr_path"),
                    _j(attempt),
                ),
            )

    for result in workspace.results_registry.get("results", []):
        cur.execute(
            "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.get("result_id"),
                result.get("run_id"),
                result.get("claim_id"),
                result.get("metric"),
                _j(result.get("value")),
                result.get("notes"),
                result.get("validation_status"),
                _j(result.get("provenance", {})),
                result.get("registered_at"),
            ),
        )

    for item in workspace.evaluation_registry.get("evaluations", []):
        cur.execute(
            "INSERT INTO evaluations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.get("evaluation_id"),
                item.get("target_type"),
                item.get("target_id"),
                item.get("evaluator"),
                item.get("status"),
                item.get("score"),
                item.get("weight"),
                item.get("summary"),
                _j(item.get("checks", [])),
                _j(item.get("details", {})),
                item.get("created_at"),
            ),
        )

    for item in workspace.artifact_registry.get("items", []):
        cur.execute(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.get("name"),
                item.get("status"),
                item.get("owner"),
                item.get("kind"),
                item.get("path"),
                item.get("run_id"),
                item.get("notes"),
                _j(item.get("provenance", {})),
                item.get("updated_at"),
            ),
        )

    for session in workspace.session_registry.get("sessions", []):
        cur.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.get("session_id"),
                session.get("sequence"),
                session.get("parent_session_id"),
                session.get("provider"),
                session.get("agent"),
                session.get("profile"),
                session.get("status"),
                session.get("current_stage"),
                session.get("handoff_reason"),
                session.get("guardrail_status"),
                session.get("action_plan_hash"),
                session.get("initial_plan_hash"),
                session.get("final_plan_hash"),
                session.get("tool_call_count"),
                session.get("apply_change_count"),
                session.get("executor_run_count"),
                session.get("started_at"),
                session.get("ended_at"),
                _j(session.get("user_context", {})),
                _j(session.get("provider_meta", {})),
                _j(session.get("result", {})),
            ),
        )

    for item in load_jsonl(workspace.root / "logs" / "event_log.jsonl"):
        cur.execute("INSERT INTO events VALUES (?, ?, ?)", (item.get("timestamp"), item.get("event_type"), _j(item)))

    for item in load_jsonl(workspace.root / "logs" / "trace.jsonl"):
        cur.execute(
            "INSERT INTO traces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.get("timestamp"),
                item.get("session_id"),
                item.get("agent"),
                item.get("profile"),
                item.get("summary"),
                _j(item.get("changes", [])),
                _j(item.get("warnings", [])),
                _j(item.get("provider_meta", {})),
                _j(item.get("stage_decision", {})),
                _j(item.get("guardrails", {})),
                item.get("action_plan_hash"),
            ),
        )

    conn.commit()
    conn.close()
    return out
