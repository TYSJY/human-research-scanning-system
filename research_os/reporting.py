from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .common import now_iso, write_text
from .planner import build_plan
from .scheduler import build_scheduler_snapshot
from .validation import validate_workspace
from .workspace import WorkspaceSnapshot


CLAIM_STATUS_LABELS = {
    "draft": "草稿",
    "candidate": "候选",
    "promoted": "已提升",
    "locked": "已锁定",
    "archived": "已归档",
}


def build_audit_report(project_dir: str | Path, output: str | Path | None = None) -> Path:
    workspace = WorkspaceSnapshot.load(project_dir)
    plan = build_plan(workspace)
    scheduler = build_scheduler_snapshot(workspace, worker_labels=[])
    errors, warnings = validate_workspace(project_dir)
    out = Path(output).resolve() if output else workspace.reports_dir / "runtime_audit_report.md"

    failing_evals = [item for item in workspace.evaluation_registry.get("evaluations", []) if item.get("status") == "fail"]
    active_runs = [item for item in workspace.run_registry.get("runs", []) if item.get("status") in {"queued", "leased", "running", "retryable", "blocked"}]
    dispatchable_runs = scheduler.get("dispatchable", [])
    sessions = workspace.session_registry.get("sessions", [])[-5:]

    lines = [
        "# Runtime Audit Report\n",
        f"- Generated at: {now_iso()}",
        f"- Project: {workspace.project.get('title')} ({workspace.project.get('project_slug')})",
        f"- Version: {workspace.project.get('version')}",
        f"- Stage: {workspace.current_stage}",
        "",
        "## Metrics",
    ]
    for key, value in plan["metrics"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Planner", f"- Recommended agent: {plan['recommended_agent']} ({plan['recommended_profile']})", f"- Handoff reason: {plan['handoff_reason']}", f"- Scheduler: {scheduler.get('summary', {})}"])
    if plan["blocking"]:
        lines.append("- Blocking:")
        for item in plan["blocking"]:
            lines.append(f"  - {item}")

    lines.extend(["", "## Active Runtime Backlog"])
    if dispatchable_runs:
        lines.append("### Dispatchable")
        for run in dispatchable_runs:
            lines.append(f"- {run.get('run_id')}: score={run.get('score')} labels={run.get('required_labels')} group={run.get('queue_group')}")
    if active_runs:
        lines.append("### Active / Waiting")
        for run in active_runs:
            approval = run.get("approval", {})
            lines.append(
                f"- {run.get('run_id')}: status={run.get('status')} priority={run.get('priority')} approval={approval.get('status')} blocked_reason={run.get('blocked_reason')} last_error={run.get('last_error')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Failing Evaluations"])
    if failing_evals:
        for item in failing_evals:
            lines.append(f"- {item.get('evaluation_id')}: target={item.get('target_type')}:{item.get('target_id')} evaluator={item.get('evaluator')} summary={item.get('summary')}")
    else:
        lines.append("- none")

    lines.extend(["", "## Recent Sessions"])
    if sessions:
        for item in sessions:
            lines.append(f"- {item.get('session_id')}: {item.get('provider')} {item.get('agent')}/{item.get('profile')} status={item.get('status')} handoff_reason={item.get('handoff_reason')}")
    else:
        lines.append("- none")

    lines.extend(["", "## Validation"])
    if errors:
        lines.append("### Errors")
        for item in errors:
            lines.append(f"- {item}")
    else:
        lines.append("### Errors\n- none")
    if warnings:
        lines.append("### Warnings")
        for item in warnings:
            lines.append(f"- {item}")
    else:
        lines.append("### Warnings\n- none")

    write_text(out, "\n".join(lines) + "\n")
    return out


def _claim_status_label(status: str | None) -> str:
    return CLAIM_STATUS_LABELS.get(status or "draft", status or "draft")


def _result_map_by_claim(workspace: WorkspaceSnapshot) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in workspace.results_registry.get("results", []):
        claim_id = item.get("claim_id") or "unlinked"
        buckets.setdefault(claim_id, []).append(item)
    return buckets


def _artifact_lines(workspace: WorkspaceSnapshot) -> list[str]:
    lines: list[str] = []
    for item in workspace.artifact_registry.get("items", [])[:20]:
        name = item.get("name") or item.get("path") or "unnamed"
        status = item.get("status") or "unknown"
        note = item.get("notes") or ""
        lines.append(f"- {name} · {status}" + (f" · {note}" if note else ""))
    return lines or ["- none"]


def build_research_brief(project_dir: str | Path, output: str | Path | None = None) -> Path:
    workspace = WorkspaceSnapshot.load(project_dir)
    plan = build_plan(workspace, persist=False)
    out = Path(output).resolve() if output else workspace.reports_dir / "research_brief.md"

    evidence_index = {item.get("evidence_id"): item for item in workspace.evidence_registry.get("items", [])}
    result_map = _result_map_by_claim(workspace)
    open_tasks = plan.get("open_tasks", [])[:5]

    lines = [
        "# Research Brief\n",
        f"- Generated at: {now_iso()}",
        f"- Project: {workspace.project.get('title')}",
        f"- Stage: {workspace.current_stage}",
        f"- Target venue: {workspace.project.get('target_venue') or 'unspecified'}",
        f"- Owner: {workspace.project.get('owner') or 'unspecified'}",
        "",
        "## Project goal",
        workspace.project.get("workflow_brief") or workspace.project.get("current_goal") or "No project goal recorded.",
        "",
        "## Current research question / MVP",
        f"- MVP name: {workspace.mvp.get('mvp_name') or '-'}",
        f"- Question: {workspace.mvp.get('question') or '-'}",
        f"- Model: {workspace.mvp.get('model') or '-'}",
        f"- Dataset: {workspace.mvp.get('dataset') or '-'}",
        "",
        "## Evidence snapshot",
    ]
    evidence_items = workspace.evidence_registry.get("items", [])
    if evidence_items:
        for item in evidence_items[:8]:
            refs = ", ".join(item.get("source_refs", [])[:3]) if item.get("source_refs") else ""
            line = f"- {item.get('evidence_id')}: {item.get('title') or '(untitled)'} · {item.get('kind') or 'unknown'}"
            if item.get("notes"):
                line += f" · {item.get('notes')}"
            if refs:
                line += f" · refs: {refs}"
            lines.append(line)
    else:
        lines.append("- none")

    lines.extend(["", "## Claims and traceability"])
    claims = workspace.claims.get("claims", [])
    if claims:
        for claim in claims:
            claim_id = claim.get("claim_id") or "claim"
            lines.append(f"### {claim_id} · {_claim_status_label(claim.get('status'))}")
            lines.append(claim.get("text") or "(no text)")
            lines.append("")
            lines.append(f"- Success metric: {claim.get('success_metric') or '-'}")
            refs = claim.get("evidence_refs", [])
            if refs:
                ref_titles = []
                for ref in refs:
                    title = (evidence_index.get(ref) or {}).get("title") or ref
                    ref_titles.append(f"{ref} ({title})")
                lines.append(f"- Evidence refs: {', '.join(ref_titles)}")
            else:
                lines.append("- Evidence refs: none")
            checks = claim.get("acceptance_checks", [])
            if checks:
                lines.append("- Acceptance checks:")
                for check in checks:
                    lines.append(f"  - {check.get('metric')} {check.get('comparator')} {check.get('threshold')}")
            results = result_map.get(claim_id, [])
            if results:
                lines.append("- Registered results:")
                for result in results:
                    lines.append(f"  - {result.get('metric')}: {result.get('value')} ({result.get('validation_status') or 'unchecked'})")
            lines.append("")
    else:
        lines.append("- none")

    lines.extend(["## Deliverables", *_artifact_lines(workspace), "", "## Recommended next actions"])
    if open_tasks:
        for task in open_tasks:
            lines.append(f"- {task.get('task_id')}: {task.get('title')} · {task.get('priority')} · {task.get('status')}")
    else:
        lines.append("- no open tasks")

    if plan.get("blocking"):
        lines.extend(["", "## Current blockers"])
        for item in plan.get("blocking", [])[:8]:
            lines.append(f"- {item}")

    write_text(out, "\n".join(lines) + "\n")
    return out


def build_evidence_matrix(project_dir: str | Path, output: str | Path | None = None) -> Path:
    workspace = WorkspaceSnapshot.load(project_dir)
    out = Path(output).resolve() if output else workspace.reports_dir / "evidence_matrix.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["evidence_id", "title", "kind", "notes", "source_refs"])
        for item in workspace.evidence_registry.get("items", []):
            writer.writerow([
                item.get("evidence_id") or "",
                item.get("title") or "",
                item.get("kind") or "",
                item.get("notes") or "",
                json.dumps(item.get("source_refs", []), ensure_ascii=False),
            ])
    return out


def build_deliverable_index(project_dir: str | Path, output: str | Path | None = None) -> Path:
    workspace = WorkspaceSnapshot.load(project_dir)
    out = Path(output).resolve() if output else workspace.reports_dir / "deliverable_index.md"
    runs = workspace.run_registry.get("runs", [])
    notes = sorted(workspace.notes_dir.glob("*.md"))
    lines = [
        "# Deliverable Index\n",
        f"- Generated at: {now_iso()}",
        f"- Project: {workspace.project.get('title')}",
        "",
        "## Registered artifacts",
    ]
    lines.extend(_artifact_lines(workspace))
    lines.extend(["", "## Notes"])
    if notes:
        for note in notes:
            lines.append(f"- {note.relative_to(workspace.root)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Runs"])
    if runs:
        for run in runs[:20]:
            result_ids = ", ".join(run.get("result_ids", [])[:6]) if run.get("result_ids") else "-"
            lines.append(f"- {run.get('run_id')}: status={run.get('status')} priority={run.get('priority')} results={result_ids}")
    else:
        lines.append("- none")
    write_text(out, "\n".join(lines) + "\n")
    return out


def build_showcase_package(project_dir: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
    workspace = WorkspaceSnapshot.load(project_dir)
    base = Path(output_dir).resolve() if output_dir else workspace.reports_dir
    base.mkdir(parents=True, exist_ok=True)
    brief = build_research_brief(project_dir, base / "research_brief.md")
    matrix = build_evidence_matrix(project_dir, base / "evidence_matrix.csv")
    index = build_deliverable_index(project_dir, base / "deliverable_index.md")
    return {
        "research_brief": brief,
        "evidence_matrix": matrix,
        "deliverable_index": index,
    }
