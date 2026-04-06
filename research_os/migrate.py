from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .bootstrap import create_project_from_template
from .common import load_json, now_iso, save_json
from .evaluators import evaluate_run
from .planner import sync_task_graph
from .sqlite_sync import sync_project_sqlite
from .workspace import CURRENT_VERSION, WorkspaceSnapshot


def _copy_text_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _infer_stage_from_legacy_task(task: dict[str, Any]) -> str:
    agent = task.get("agent", "")
    mapping = {
        "scan": "scan",
        "design": "design",
        "execution": "execute",
        "writing": "write",
        "audit": "audit",
        "controller": "scan",
    }
    return mapping.get(agent, "scan")


def _normalize_claims(workspace: WorkspaceSnapshot) -> None:
    for claim in workspace.claims.get("claims", []):
        claim.setdefault("status", "draft")
        claim.setdefault("evidence_refs", [])
        claim.setdefault("risk_refs", [])
        claim.setdefault("acceptance_checks", [])
        if not claim.get("acceptance_checks") and claim.get("success_metric"):
            claim["acceptance_checks"] = [{"check_id": f"{claim.get('claim_id','claim')}.default", "metric": claim["success_metric"], "operator": "informational", "threshold": None}]
    workspace.save_state("claims")


def _normalize_run_registry(workspace: WorkspaceSnapshot) -> None:
    # loading the workspace already hydrates from legacy run_queue/manifest state when needed.
    for run in workspace.run_registry.get("runs", []):
        run.setdefault("status", "planned")
        run.setdefault("priority", "normal")
        run.setdefault("approval", {"required": False, "status": "not_required", "reason": "", "risk_tags": []})
        run.setdefault("lease", {})
        run.setdefault("attempts", [])
        run.setdefault("attempt_count", len(run.get("attempts", [])))
        run.setdefault("max_attempts", 1)
        run.setdefault("retry_count", 0)
        run.setdefault("evaluation_status", "pending")
        run.setdefault("resource_budget", {})
        run.setdefault("result_ids", [r.get("result_id") for r in workspace.results_registry.get("results", []) if r.get("run_id") == run.get("run_id")])
    workspace.save_state("run_registry")


def _normalize_runtime(workspace: WorkspaceSnapshot) -> None:
    workspace.project.setdefault("version", CURRENT_VERSION)
    workspace.project.setdefault("budgets", {})
    workspace.project["version"] = CURRENT_VERSION
    workspace.runtime.setdefault("continuations", {})
    workspace.runtime.setdefault("workloop_runs", 0)
    workspace.runtime.setdefault("last_session_id", None)
    workspace.save_state("project")
    workspace.save_state("runtime")


def _backfill_evaluations(workspace: WorkspaceSnapshot) -> None:
    existing = {(item.get("target_type"), item.get("target_id")) for item in workspace.evaluation_registry.get("evaluations", [])}
    for run in workspace.run_registry.get("runs", []):
        if run.get("status") != "succeeded":
            continue
        key = ("run", run.get("run_id"))
        if key in existing:
            continue
        try:
            evaluate_run(workspace, run.get("run_id"))
        except Exception:
            # Migration should be best-effort; validation can surface any remaining issues.
            continue


def upgrade_v4_1_project(v4_1_project_dir: str | Path, output_dir: str | Path | None = None) -> Path:
    source = Path(v4_1_project_dir).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    target = Path(output_dir).resolve() if output_dir else source
    if target != source:
        if target.exists():
            raise FileExistsError(f"Target already exists: {target}")
        shutil.copytree(source, target)

    workspace = WorkspaceSnapshot.load(target)
    workspace.ensure_layout()
    _normalize_claims(workspace)
    _normalize_run_registry(workspace)
    _normalize_runtime(workspace)
    sync_task_graph(workspace)
    _backfill_evaluations(workspace)
    workspace.save_all()
    sync_project_sqlite(target)
    workspace.log_event("project_upgraded", from_version="0.4.1", to_version=CURRENT_VERSION)
    return target


def migrate_v3_project(v3_project_dir: str | Path, output_dir: str | Path) -> Path:
    legacy_root = Path(v3_project_dir).resolve()
    manifest_path = legacy_root / "00_admin" / "project_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"V3 project manifest not found: {manifest_path}")
    manifest = load_json(manifest_path, {})
    workflow = load_json(legacy_root / "00_admin" / "workflow_state.json", {})
    title = manifest.get("title", legacy_root.name)
    owner = manifest.get("owner", "replace-me")
    venue = manifest.get("target_venue", "replace-me")

    output_path = Path(output_dir).resolve()
    out_root = output_path.parent
    out_name = output_path.name
    created = create_project_from_template(out_root, out_name, title=title, owner=owner, venue=venue)
    workspace = WorkspaceSnapshot.load(created)

    workspace.project.update(
        {
            "project_slug": out_name,
            "title": title,
            "owner": owner,
            "target_venue": venue,
            "current_goal": manifest.get("current_goal", "migrated from V3"),
            "constraints": manifest.get("constraints", {}),
            "autonomy_policy": manifest.get("autonomy_policy", workspace.project.get("autonomy_policy", {})),
            "reasoning_policy": manifest.get("reasoning_profiles", workspace.project.get("reasoning_policy", {})),
        }
    )
    workspace.project.setdefault("budgets", {})
    workspace.project["budgets"].update(load_json(legacy_root / "00_admin" / "execution_budget.json", {}))

    stage = manifest.get("stage") or workflow.get("current_stage") or "scan"
    order = ["scan", "design", "execute", "write", "audit"]
    stage_index = order.index(stage) if stage in order else 0
    workspace.stage_state["current_stage"] = stage
    workspace.stage_state["stage_status"] = {
        name: ("done" if idx < stage_index else "active" if idx == stage_index else "blocked") for idx, name in enumerate(order)
    }
    legacy_gates = load_json(legacy_root / "00_admin" / "human_gates.json", {"gates": []})
    if legacy_gates.get("gates"):
        workspace.stage_state["gates"] = legacy_gates["gates"]

    workspace.states["evidence_registry"] = load_json(legacy_root / "01_scan" / "evidence_registry.json", {"items": []})
    workspace.states["baseline_registry"] = load_json(legacy_root / "01_scan" / "baseline_registry.json", {"items": []})
    workspace.states["claims"] = load_json(legacy_root / "02_design" / "claim_graph.json", {"claims": [], "edges": []})
    workspace.states["mvp"] = load_json(legacy_root / "02_design" / "mvp_definition.json", {})
    workspace.states["results_registry"] = load_json(legacy_root / "04_results" / "results_registry.json", {"results": []})
    workspace.states["artifact_registry"] = load_json(legacy_root / "06_artifacts" / "artifact_registry.json", {"items": []})
    workspace.states["figure_plan"] = load_json(legacy_root / "05_paper" / "figure_plan.json", {"figures": []})

    legacy_backlog = load_json(legacy_root / "00_admin" / "backlog.json", {"tasks": []})
    migrated_tasks = []
    for idx, task in enumerate(legacy_backlog.get("tasks", []), start=1):
        migrated_tasks.append(
            {
                "task_id": task.get("task_id") or f"legacy.T{idx:03d}",
                "title": task.get("title", f"legacy task {idx}"),
                "stage": _infer_stage_from_legacy_task(task),
                "kind": "legacy",
                "agent": task.get("agent", "controller"),
                "profile": task.get("profile", "think"),
                "priority": task.get("priority", "P1"),
                "status": task.get("status", "todo"),
                "depends_on": task.get("depends_on", []),
                "requires_gate": task.get("requires_gate"),
                "notes": f"Migrated from V3 backlog: {task.get('reason', '')}",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
    workspace.task_graph["tasks"] = migrated_tasks

    workspace.runtime.update(
        {
            "last_agent": workflow.get("last_agent"),
            "last_profile": workflow.get("recommended_profile"),
            "last_summary": workflow.get("last_summary"),
            "last_run_at": workflow.get("last_run_at"),
        }
    )

    note_mapping = {
        legacy_root / "01_scan" / "literature_scan.md": created / "notes" / "scan.md",
        legacy_root / "01_scan" / "novelty_audit.md": created / "notes" / "novelty_audit.md",
        legacy_root / "01_scan" / "reviewer_priors.md": created / "notes" / "reviewer_priors.md",
        legacy_root / "02_design" / "claim_evidence_map.md": created / "notes" / "claim_evidence_map.md",
        legacy_root / "02_design" / "experiment_plan.md": created / "notes" / "experiment_plan.md",
        legacy_root / "02_design" / "implementation_plan.md": created / "notes" / "implementation_plan.md",
        legacy_root / "04_results" / "synthesis.md": created / "notes" / "results_synthesis.md",
        legacy_root / "05_paper" / "title_abstract.md": created / "notes" / "title_abstract.md",
        legacy_root / "05_paper" / "outline.md": created / "notes" / "outline.md",
        legacy_root / "05_paper" / "rebuttal_notes.md": created / "notes" / "rebuttal_notes.md",
        legacy_root / "05_paper" / "contribution_constraints.md": created / "notes" / "contribution_constraints.md",
        legacy_root / "06_artifacts" / "release_checklist.md": created / "notes" / "release_checklist.md",
        legacy_root / "06_artifacts" / "reproducibility_checklist.md": created / "notes" / "reproducibility_checklist.md",
        legacy_root / "06_artifacts" / "package_inventory.md": created / "notes" / "package_inventory.md",
        legacy_root / "00_admin" / "weekly_status.md": created / "notes" / "admin_weekly_status.md",
        legacy_root / "00_admin" / "risks.md": created / "notes" / "risks.md",
        legacy_root / "00_admin" / "decisions.md": created / "notes" / "legacy_decisions.md",
    }
    for src, dst in note_mapping.items():
        _copy_text_if_exists(src, dst)

    trace_src = legacy_root / "07_agent" / "orchestration_trace.jsonl"
    if trace_src.exists():
        shutil.copy2(trace_src, created / "logs" / "trace.jsonl")

    legacy_runs_root = legacy_root / "03_runs"
    if legacy_runs_root.exists():
        for run_dir in legacy_runs_root.iterdir():
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            new_run_dir = created / "runs" / run_id
            new_run_dir.mkdir(parents=True, exist_ok=True)
            legacy_manifest = load_json(run_dir / "run_manifest.json", {})
            if legacy_manifest:
                legacy_manifest["run_id"] = run_id
                save_json(new_run_dir / "manifest.json", legacy_manifest)
            request = {
                "executor": "manual",
                "command": [],
                "timeout_sec": 0,
                "metrics_output": "metrics.json",
                "register_results": [],
                "approval": {"required": True, "reason": "Migrated manual run; bind a real runner or ingest external outputs.", "risk_tags": ["migrated_manual"]},
                "notes": "Migrated from V3. Fill with a real shell command or bind an external runner.",
            }
            save_json(new_run_dir / "request.json", request)
            metrics = load_json(run_dir / "metrics.json", {"metrics": {}})
            save_json(new_run_dir / "metrics.json", metrics)
            _copy_text_if_exists(run_dir / "notes.md", new_run_dir / "notes.md")
            _copy_text_if_exists(run_dir / "expected_vs_actual.md", new_run_dir / "expected_vs_actual.md")
            save_json(new_run_dir / "output_manifest.json", {"run_id": run_id, "generated_at": now_iso(), "files": [], "missing": []})

    workspace.append_log(
        "decisions.jsonl",
        {
            "timestamp": now_iso(),
            "actor": "migration",
            "profile": "n/a",
            "decision": "migrate_v3_to_v4_3",
            "why": "Unify runtime state, add run_registry/evaluation/session registries, and prepare worker lifecycle integration.",
            "impact": f"V3 stage drift resolved in favor of project_manifest.stage={stage}; workflow_state.current_stage={workflow.get('current_stage')}",
        },
    )

    _normalize_claims(workspace)
    _normalize_run_registry(workspace)
    _normalize_runtime(workspace)
    sync_task_graph(workspace)
    workspace.save_all()
    _backfill_evaluations(workspace)
    sync_project_sqlite(created)
    return created
