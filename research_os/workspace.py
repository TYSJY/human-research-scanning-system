from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import append_jsonl, coerce_str_list, ensure_dir, load_json, now_iso, read_text, save_json, write_text


CURRENT_VERSION = "0.6.6"
DEFAULT_RUNTIME_BUDGET = {
    "max_concurrent_runs": 1,
    "lease_ttl_sec": 30,
    "heartbeat_sec": 2,
    "default_timeout_sec": 1800,
    "default_retry_policy": {
        "max_attempts": 2,
        "retry_on": ["timeout", "non_zero_exit", "lease_expired", "evaluator_fail"],
        "backoff_sec": 5,
        "fail_on_evaluation_error": True,
    },
}
DEFAULT_AUTONOMY_POLICY = {
    "level": "supervised",
    "auto_execute_safe_runs": False,
    "never_auto_approve": ["claim_lock", "submission_ready", "budget_expand"],
}
DEFAULT_REASONING_POLICY = {"default": "think", "critical": "pro", "deep_research": "deep_research"}
DEFAULT_GATES = [
    {"gate_id": "track_selected", "title": "Confirm primary research track", "status": "pending"},
    {"gate_id": "claim_lock", "title": "Lock promoted core claims", "status": "pending"},
    {"gate_id": "budget_expand", "title": "Approve larger compute or token budget", "status": "pending"},
    {"gate_id": "submission_ready", "title": "Approve final submission posture", "status": "pending"},
]

STATE_DEFAULTS: dict[str, Any] = {
    "project": {
        "project_slug": "replace-me",
        "title": "replace-me",
        "owner": "replace-me",
        "target_venue": "replace-me",
        "version": CURRENT_VERSION,
        "current_goal": "scan the topic, lock claims, run the MVP, validate claims, then write conservatively",
        "constraints": {},
        "budgets": {
            "max_active_or_queued_runs_without_budget_expand": 2,
            "token_budget": "replace-me",
            "compute_budget": "replace-me",
            "runtime": deepcopy(DEFAULT_RUNTIME_BUDGET),
        },
        "autonomy_policy": deepcopy(DEFAULT_AUTONOMY_POLICY),
        "reasoning_policy": deepcopy(DEFAULT_REASONING_POLICY),
    },
    "stage_state": {
        "current_stage": "scan",
        "stage_status": {"scan": "active", "design": "blocked", "execute": "blocked", "write": "blocked", "audit": "blocked"},
        "gates": deepcopy(DEFAULT_GATES),
    },
    "task_graph": {"tasks": []},
    "evidence_registry": {"items": []},
    "baseline_registry": {"items": []},
    "claims": {"claims": [], "edges": []},
    "mvp": {},
    "results_registry": {"results": []},
    "artifact_registry": {"items": []},
    "run_registry": {"runs": []},
    "evaluation_registry": {"evaluations": []},
    "session_registry": {"sessions": []},
    "runtime": {
        "last_agent": None,
        "last_profile": None,
        "last_provider": None,
        "last_summary": None,
        "last_run_at": None,
        "last_session_id": None,
        "last_worker_id": None,
        "last_plan_hash": None,
        "session_sequence": 0,
        "continuations": {},
        "workloop_runs": 0,
        "scoreboard_refreshed_at": None,
        "last_scheduler_summary": {},
    },
    "figure_plan": {"figures": []},
    "studio": {},
}

STATE_FILES = {
    "project": "state/project.json",
    "stage_state": "state/stage_state.json",
    "task_graph": "state/task_graph.json",
    "evidence_registry": "state/evidence_registry.json",
    "baseline_registry": "state/baseline_registry.json",
    "claims": "state/claims.json",
    "mvp": "state/mvp.json",
    "results_registry": "state/results_registry.json",
    "artifact_registry": "state/artifact_registry.json",
    "run_registry": "state/run_registry.json",
    "evaluation_registry": "state/evaluation_registry.json",
    "session_registry": "state/session_registry.json",
    "runtime": "state/runtime.json",
    "figure_plan": "state/figure_plan.json",
    "studio": "state/studio.json",
}

LEGACY_STATE_FILES = {"run_queue": "state/run_queue.json"}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
ACTIVE_RUN_STATUSES = {"leased", "running"}


def _map_legacy_run_status(queue_status: str | None, manifest_status: str | None) -> str:
    status = queue_status or manifest_status or "planned"
    mapping = {
        "planned": "planned",
        "queued": "queued",
        "running": "running",
        "done": "succeeded",
        "failed": "failed",
        "manual": "blocked",
    }
    return mapping.get(status, status)


@dataclass
class WorkspaceSnapshot:
    root: Path
    states: dict[str, Any]

    @classmethod
    def load(cls, root: str | Path) -> "WorkspaceSnapshot":
        root_path = Path(root).resolve()
        states: dict[str, Any] = {}
        for key, rel_path in STATE_FILES.items():
            states[key] = load_json(root_path / rel_path, deepcopy(STATE_DEFAULTS[key]))
        snapshot = cls(root=root_path, states=states)
        snapshot.ensure_layout()
        snapshot._hydrate_legacy_run_registry()
        snapshot._normalize_loaded_state()
        return snapshot

    def ensure_layout(self) -> None:
        from .studio import ensure_studio_layout

        for rel in ["state", "notes", "logs", "runs", "db", "reports"]:
            ensure_dir(self.root / rel)
        ensure_studio_layout(self.root)
        for key in STATE_FILES:
            path = self.root / STATE_FILES[key]
            if not path.exists():
                save_json(path, self.states[key])

    def _hydrate_legacy_run_registry(self) -> None:
        if self.run_registry.get("runs"):
            return
        legacy_queue = load_json(self.root / LEGACY_STATE_FILES["run_queue"], {"items": []})
        queue_by_run = {item.get("run_id"): item for item in legacy_queue.get("items", [])}
        discovered: list[dict[str, Any]] = []
        for run_id in self.list_run_dirs():
            manifest = self.load_run_manifest(run_id)
            request = self.load_run_request(run_id)
            q = queue_by_run.get(run_id, {})
            status = _map_legacy_run_status(q.get("status"), manifest.get("status"))
            claims_under_test = sorted({spec.get("claim_id") for spec in request.get("register_results", []) if spec.get("claim_id")})
            discovered.append(
                {
                    "run_id": run_id,
                    "status": status,
                    "priority": q.get("priority", "normal"),
                    "executor": request.get("executor", "manual"),
                    "task_id": q.get("task_id"),
                    "queue_group": q.get("queue_group") or request.get("queue_group"),
                    "reasoning_profile": request.get("reasoning_profile", self.project.get("reasoning_policy", {}).get("default", "think")),
                    "depends_on_runs": coerce_str_list(request.get("depends_on_runs")),
                    "worker_requirements": request.get("worker_requirements", {"labels": []}),
                    "created_at": manifest.get("created_at") or q.get("requested_at") or now_iso(),
                    "created_by": q.get("created_by"),
                    "created_from_session_id": q.get("created_from_session_id"),
                    "queued_at": q.get("requested_at"),
                    "started_at": manifest.get("started_at") or q.get("started_at"),
                    "ended_at": manifest.get("ended_at") or q.get("finished_at"),
                    "attempt_count": 1 if manifest.get("started_at") else 0,
                    "max_attempts": request.get("retry_policy", {}).get("max_attempts", 1),
                    "retry_count": 0,
                    "retry_at": None,
                    "approval": {"required": False, "status": "not_required", "reason": "", "risk_tags": []},
                    "lease": {},
                    "cancel_requested": False,
                    "last_error": q.get("error"),
                    "blocked_reason": None,
                    "evaluation_status": "pending",
                    "result_ids": [r.get("result_id") for r in self.results_registry.get("results", []) if r.get("run_id") == run_id],
                    "claims_under_test": claims_under_test,
                    "manifest_path": f"runs/{run_id}/manifest.json",
                    "request_path": f"runs/{run_id}/request.json",
                    "metrics_path": f"runs/{run_id}/metrics.json",
                    "output_manifest_path": f"runs/{run_id}/output_manifest.json",
                    "resource_budget": request.get("resource_budget", {}),
                    "retry_policy": request.get("retry_policy", {}),
                    "selection": {"group": request.get("queue_group") or run_id, "status": "unscored", "score": None, "best_in_group": False, "updated_at": None},
                    "attempts": [],
                }
            )
            if discovered[-1]["attempt_count"]:
                discovered[-1]["attempts"].append(
                    {
                        "attempt": 1,
                        "status": status,
                        "started_at": discovered[-1]["started_at"],
                        "ended_at": discovered[-1]["ended_at"],
                        "exit_code": manifest.get("exit_code"),
                        "worker_id": q.get("worker_id"),
                        "error": discovered[-1]["last_error"],
                    }
                )
        if discovered:
            self.run_registry["runs"] = discovered
            self.save_state("run_registry")

    def _normalize_loaded_state(self) -> None:
        changed: set[str] = set()

        project = self.project
        if project.get("version") != CURRENT_VERSION:
            project["version"] = CURRENT_VERSION
            changed.add("project")
        if "created_at" not in project:
            project["created_at"] = now_iso()
            changed.add("project")
        project.setdefault("constraints", {})
        project.setdefault("budgets", {})
        project.setdefault("autonomy_policy", {})
        project.setdefault("reasoning_policy", {})
        if not project["autonomy_policy"]:
            project["autonomy_policy"] = deepcopy(DEFAULT_AUTONOMY_POLICY)
            changed.add("project")
        else:
            for key, value in DEFAULT_AUTONOMY_POLICY.items():
                if key not in project["autonomy_policy"]:
                    project["autonomy_policy"][key] = deepcopy(value)
                    changed.add("project")
        if not project["reasoning_policy"]:
            project["reasoning_policy"] = deepcopy(DEFAULT_REASONING_POLICY)
            changed.add("project")
        else:
            for key, value in DEFAULT_REASONING_POLICY.items():
                if key not in project["reasoning_policy"]:
                    project["reasoning_policy"][key] = deepcopy(value)
                    changed.add("project")
        from .studio import normalize_studio

        project.setdefault("workflow_brief", project.get("current_goal"))
        if normalize_studio(self.studio, project):
            changed.add("studio")
        budgets = project["budgets"]
        budgets.setdefault("max_active_or_queued_runs_without_budget_expand", 2)
        budgets.setdefault("token_budget", "replace-me")
        budgets.setdefault("compute_budget", "replace-me")
        budgets.setdefault("runtime", {})
        for key, value in DEFAULT_RUNTIME_BUDGET.items():
            if key not in budgets["runtime"]:
                budgets["runtime"][key] = deepcopy(value)
                changed.add("project")
        if isinstance(budgets["runtime"].get("default_retry_policy"), dict):
            for key, value in DEFAULT_RUNTIME_BUDGET["default_retry_policy"].items():
                if key not in budgets["runtime"]["default_retry_policy"]:
                    budgets["runtime"]["default_retry_policy"][key] = deepcopy(value)
                    changed.add("project")

        stage_state = self.stage_state
        stage_state.setdefault("current_stage", "scan")
        stage_state.setdefault("stage_status", {"scan": "active", "design": "blocked", "execute": "blocked", "write": "blocked", "audit": "blocked"})
        stage_state.setdefault("gates", [])
        known_gates = {gate.get("gate_id"): gate for gate in stage_state.get("gates", []) if gate.get("gate_id")}
        for gate in DEFAULT_GATES:
            existing = known_gates.get(gate["gate_id"])
            if existing is None:
                stage_state["gates"].append(deepcopy(gate))
                changed.add("stage_state")
                continue
            if "title" not in existing:
                existing["title"] = gate["title"]
                changed.add("stage_state")
            existing.setdefault("status", "pending")
        
        runtime = self.runtime
        for key, value in STATE_DEFAULTS["runtime"].items():
            if key not in runtime:
                runtime[key] = deepcopy(value)
                changed.add("runtime")
        runtime["session_sequence"] = max(int(runtime.get("session_sequence", 0) or 0), len(self.session_registry.get("sessions", [])))
        if runtime.get("scoreboard_refreshed_at", None) is None:
            runtime["scoreboard_refreshed_at"] = None
        if not isinstance(runtime.get("last_scheduler_summary"), dict):
            runtime["last_scheduler_summary"] = {}
            changed.add("runtime")

        self.task_graph.setdefault("tasks", [])
        self.evidence_registry.setdefault("items", [])
        self.baseline_registry.setdefault("items", [])
        self.claims.setdefault("claims", [])
        self.claims.setdefault("edges", [])
        self.results_registry.setdefault("results", [])
        self.artifact_registry.setdefault("items", [])
        self.run_registry.setdefault("runs", [])
        self.evaluation_registry.setdefault("evaluations", [])
        self.session_registry.setdefault("sessions", [])
        self.figure_plan.setdefault("figures", [])

        task_ids = {task.get("task_id"): task for task in self.task_graph.get("tasks", []) if task.get("task_id")}
        results_by_run: dict[str, list[str]] = {}
        for result in self.results_registry.get("results", []):
            result.setdefault("validation_status", "pending")
            result.setdefault("provenance", {})
            result.setdefault("registered_at", now_iso())
            if result.get("run_id"):
                results_by_run.setdefault(result["run_id"], []).append(result.get("result_id"))

        for item in self.artifact_registry.get("items", []):
            if "updated_at" not in item:
                item["updated_at"] = now_iso()
                changed.add("artifact_registry")
            item.setdefault("path", None)
            item.setdefault("kind", None)
            item.setdefault("run_id", None)
            item.setdefault("provenance", {})

        for run in self.run_registry.get("runs", []):
            run_id = run.get("run_id")
            if not run_id:
                continue
            request = self.load_run_request(run_id)
            manifest = self.load_run_manifest(run_id)
            run.setdefault("status", "planned")
            run.setdefault("priority", "normal")
            if run.get("executor") in {None, ""}:
                run["executor"] = request.get("executor", manifest.get("executor", "manual"))
                changed.add("run_registry")
            if run.get("task_id") in {None, ""}:
                run["task_id"] = request.get("task_id")
                if request.get("task_id") is not None:
                    changed.add("run_registry")
            if run.get("queue_group") in {None, ""}:
                run["queue_group"] = request.get("queue_group") or run.get("task_id") or run_id
                changed.add("run_registry")
            if run.get("reasoning_profile") in {None, ""}:
                run["reasoning_profile"] = request.get("reasoning_profile", self.project.get("reasoning_policy", {}).get("default", "think"))
                changed.add("run_registry")
            if not isinstance(run.get("depends_on_runs"), list):
                run["depends_on_runs"] = coerce_str_list(request.get("depends_on_runs"))
                changed.add("run_registry")
            if not isinstance(run.get("worker_requirements"), dict):
                run["worker_requirements"] = request.get("worker_requirements", {"labels": []})
                changed.add("run_registry")
            run.setdefault("created_at", manifest.get("created_at") or now_iso())
            run.setdefault("created_by", None)
            run.setdefault("created_from_session_id", request.get("created_from_session_id"))
            run.setdefault("queued_at", None)
            run.setdefault("started_at", manifest.get("started_at"))
            run.setdefault("ended_at", manifest.get("ended_at"))
            run.setdefault("attempt_count", len(run.get("attempts", [])))
            run.setdefault("max_attempts", int(request.get("retry_policy", {}).get("max_attempts", 1) or 1))
            run.setdefault("retry_count", 0)
            run.setdefault("retry_at", None)
            run.setdefault("approval", {})
            run["approval"].setdefault("required", False)
            run["approval"].setdefault("status", "pending" if run["approval"].get("required") else "not_required")
            run["approval"].setdefault("reason", "")
            run["approval"].setdefault("risk_tags", [])
            run.setdefault("lease", {})
            run.setdefault("cancel_requested", False)
            run.setdefault("cancel_requested_at", None)
            run.setdefault("blocked_reason", None)
            run.setdefault("last_error", None)
            run.setdefault("evaluation_status", "pending")
            run.setdefault("last_evaluated_at", None)
            run.setdefault("result_ids", sorted(set(results_by_run.get(run_id, []) + [rid for rid in run.get("result_ids", []) if rid])))
            run.setdefault("claims_under_test", sorted({spec.get("claim_id") for spec in request.get("register_results", []) if spec.get("claim_id")}))
            run.setdefault("manifest_path", f"runs/{run_id}/manifest.json")
            run.setdefault("request_path", f"runs/{run_id}/request.json")
            run.setdefault("metrics_path", f"runs/{run_id}/metrics.json")
            run.setdefault("output_manifest_path", f"runs/{run_id}/output_manifest.json")
            run.setdefault("resource_budget", request.get("resource_budget", {}))
            run.setdefault("retry_policy", request.get("retry_policy", deepcopy(DEFAULT_RUNTIME_BUDGET["default_retry_policy"])))
            run.setdefault("selector", request.get("selector", {"group": run.get("queue_group") or run_id, "min_score_to_promote": 75, "stop_after_preferred": False}))
            run.setdefault("selection", {"group": run.get("queue_group") or run_id, "status": "unscored", "score": None, "best_in_group": False, "updated_at": None, "score_breakdown": {}})
            run.setdefault("attempts", [])
            if run["selection"].get("group") in {None, ""}:
                run["selection"]["group"] = run.get("queue_group") or run_id
                changed.add("run_registry")
            if run.get("status") == "succeeded" and run.get("evaluation_status") == "pending":
                run["evaluation_status"] = "warn"
                changed.add("run_registry")
            if run.get("cancel_requested") and run.get("status") in {"planned", "queued", "retryable"}:
                run["status"] = "cancelled"
                changed.add("run_registry")
            if run.get("attempt_count") != len(run.get("attempts", [])):
                run["attempt_count"] = len(run.get("attempts", []))
                changed.add("run_registry")
            if run.get("task_id") and run.get("task_id") not in task_ids:
                run["task_id"] = None
                changed.add("run_registry")

        for evaluation in self.evaluation_registry.get("evaluations", []):
            evaluation.setdefault("score", None)
            evaluation.setdefault("weight", None)
            evaluation.setdefault("details", {})
            evaluation.setdefault("checks", evaluation.get("details", {}).get("checks", []))
            evaluation.setdefault("created_at", now_iso())

        for idx, session in enumerate(self.session_registry.get("sessions", []), start=1):
            if not session.get("session_id"):
                session["session_id"] = f"S{idx:04d}"
                changed.add("session_registry")
            session.setdefault("status", "completed")
            session.setdefault("parent_session_id", None)
            session.setdefault("sequence", idx)
            session.setdefault("handoff_reason", None)
            session.setdefault("current_stage", self.current_stage)
            session.setdefault("user_context", {})
            session.setdefault("provider_meta", {})
            session.setdefault("result", {})
            session.setdefault("guardrail_status", None)
            session.setdefault("action_plan_hash", None)
            session.setdefault("initial_plan_hash", None)
            session.setdefault("final_plan_hash", None)
            session.setdefault("tool_call_count", 0)
            session.setdefault("apply_change_count", 0)
            session.setdefault("executor_run_count", 0)
            session.setdefault("started_at", now_iso())

        if changed:
            for key in changed:
                self.save_state(key)

    def state_path(self, key: str) -> Path:
        return self.root / STATE_FILES[key]

    def save_state(self, key: str) -> None:
        save_json(self.state_path(key), self.states[key])

    def save_all(self) -> None:
        for key in STATE_FILES:
            self.save_state(key)

    @property
    def project(self) -> dict[str, Any]:
        return self.states["project"]

    @property
    def stage_state(self) -> dict[str, Any]:
        return self.states["stage_state"]

    @property
    def task_graph(self) -> dict[str, Any]:
        return self.states["task_graph"]

    @property
    def evidence_registry(self) -> dict[str, Any]:
        return self.states["evidence_registry"]

    @property
    def baseline_registry(self) -> dict[str, Any]:
        return self.states["baseline_registry"]

    @property
    def claims(self) -> dict[str, Any]:
        return self.states["claims"]

    @property
    def mvp(self) -> dict[str, Any]:
        return self.states["mvp"]

    @property
    def results_registry(self) -> dict[str, Any]:
        return self.states["results_registry"]

    @property
    def artifact_registry(self) -> dict[str, Any]:
        return self.states["artifact_registry"]

    @property
    def run_registry(self) -> dict[str, Any]:
        return self.states["run_registry"]

    @property
    def evaluation_registry(self) -> dict[str, Any]:
        return self.states["evaluation_registry"]

    @property
    def session_registry(self) -> dict[str, Any]:
        return self.states["session_registry"]

    @property
    def runtime(self) -> dict[str, Any]:
        return self.states["runtime"]

    @property
    def figure_plan(self) -> dict[str, Any]:
        return self.states["figure_plan"]

    @property
    def studio(self) -> dict[str, Any]:
        return self.states["studio"]

    @property
    def current_stage(self) -> str:
        return self.stage_state.get("current_stage", "scan")

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    def note_path(self, rel_path: str) -> Path:
        return self.root / rel_path

    def read_note(self, rel_path: str) -> str:
        return read_text(self.note_path(rel_path), "")

    def write_note(self, rel_path: str, content: str, mode: str = "replace") -> None:
        path = self.note_path(rel_path)
        existing = read_text(path, "")
        if mode == "replace":
            write_text(path, content)
            return
        if mode == "append":
            write_text(path, existing + content)
            return
        if mode == "replace_if_placeholder":
            lower = existing.strip().lower()
            if not existing.strip() or "replace-me" in lower or "todo" in lower or "tbd" in lower:
                write_text(path, content)
            return
        raise ValueError(f"Unsupported note write mode: {mode}")

    def append_log(self, file_name: str, payload: dict[str, Any]) -> None:
        append_jsonl(self.logs_dir / file_name, payload)

    def log_event(self, event_type: str, **fields: Any) -> None:
        payload = {"timestamp": now_iso(), "event_type": event_type}
        payload.update(fields)
        self.append_log("event_log.jsonl", payload)

    def gate_status(self, gate_id: str) -> str:
        for gate in self.stage_state.get("gates", []):
            if gate.get("gate_id") == gate_id:
                return gate.get("status", "pending")
        return "missing"

    def update_gate(self, gate_id: str, **patch: Any) -> None:
        for gate in self.stage_state.get("gates", []):
            if gate.get("gate_id") == gate_id:
                gate.update(patch)
                self.save_state("stage_state")
                return
        self.stage_state.setdefault("gates", []).append({"gate_id": gate_id, **patch})
        self.save_state("stage_state")

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def list_run_dirs(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        return sorted(p.name for p in self.runs_dir.iterdir() if p.is_dir())

    def list_runs(self) -> list[str]:
        run_ids = {item.get("run_id") for item in self.run_registry.get("runs", []) if item.get("run_id")}
        run_ids.update(self.list_run_dirs())
        return sorted(run_ids)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        for item in self.run_registry.get("runs", []):
            if item.get("run_id") == run_id:
                return item
        return None

    def upsert_run(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_run(run_id)
        if existing is None:
            existing = {"run_id": run_id}
            self.run_registry.setdefault("runs", []).append(existing)
        existing.update(payload)
        self.save_state("run_registry")
        return existing

    def append_run_attempt(self, run_id: str, payload: dict[str, Any]) -> None:
        run = self.get_run(run_id)
        if run is None:
            run = self.upsert_run(run_id, {})
        run.setdefault("attempts", []).append(payload)
        run["attempt_count"] = len(run.get("attempts", []))
        self.save_state("run_registry")

    def load_run_manifest(self, run_id: str) -> dict[str, Any]:
        return load_json(self.run_dir(run_id) / "manifest.json", {})

    def save_run_manifest(self, run_id: str, payload: dict[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        ensure_dir(run_dir)
        save_json(run_dir / "manifest.json", payload)

    def load_run_request(self, run_id: str) -> dict[str, Any]:
        return load_json(self.run_dir(run_id) / "request.json", {})

    def save_run_request(self, run_id: str, payload: dict[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        ensure_dir(run_dir)
        save_json(run_dir / "request.json", payload)

    def load_run_metrics(self, run_id: str) -> dict[str, Any]:
        return load_json(self.run_dir(run_id) / "metrics.json", {"metrics": {}})

    def save_run_metrics(self, run_id: str, payload: dict[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        ensure_dir(run_dir)
        save_json(run_dir / "metrics.json", payload)

    def load_run_output_manifest(self, run_id: str) -> dict[str, Any]:
        return load_json(self.run_dir(run_id) / "output_manifest.json", {"files": [], "missing": []})

    def save_run_output_manifest(self, run_id: str, payload: dict[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        ensure_dir(run_dir)
        save_json(run_dir / "output_manifest.json", payload)

    def write_run_log(self, run_id: str, file_name: str, content: str) -> None:
        path = self.run_dir(run_id) / file_name
        write_text(path, content)

    def upsert_evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        evaluations = self.evaluation_registry.setdefault("evaluations", [])
        key = (payload.get("target_type"), payload.get("target_id"), payload.get("evaluator"))
        for item in evaluations:
            item_key = (item.get("target_type"), item.get("target_id"), item.get("evaluator"))
            if item_key == key:
                item.update(payload)
                if not item.get("evaluation_id"):
                    item["evaluation_id"] = f"EV{evaluations.index(item) + 1:04d}"
                self.save_state("evaluation_registry")
                return item
        if not payload.get("evaluation_id"):
            payload["evaluation_id"] = f"EV{len(evaluations) + 1:04d}"
        evaluations.append(payload)
        self.save_state("evaluation_registry")
        return payload

    def add_evaluation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.upsert_evaluation(payload)

    def evaluations_for_target(self, target_type: str, target_id: str) -> list[dict[str, Any]]:
        return [item for item in self.evaluation_registry.get("evaluations", []) if item.get("target_type") == target_type and item.get("target_id") == target_id]

    def add_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        sessions = self.session_registry.setdefault("sessions", [])
        if not payload.get("session_id"):
            payload["session_id"] = f"S{len(sessions) + 1:04d}"
        payload.setdefault("sequence", len(sessions) + 1)
        payload.setdefault("started_at", now_iso())
        sessions.append(payload)
        self.runtime["session_sequence"] = max(int(self.runtime.get("session_sequence", 0) or 0), len(sessions))
        self.save_state("session_registry")
        self.save_state("runtime")
        return payload

    def update_session(self, session_id: str, **patch: Any) -> None:
        for session in self.session_registry.get("sessions", []):
            if session.get("session_id") == session_id:
                session.update(patch)
                self.save_state("session_registry")
                return

    def metrics_summary(self) -> dict[str, int]:
        status_counts = {status: 0 for status in ["planned", "queued", "leased", "running", "retryable", "blocked", "succeeded", "failed", "cancelled"]}
        pending_run_approvals = 0
        evaluation_failures = 0
        evaluation_warns = 0
        preferred_runs = 0
        candidate_runs = 0
        for run in self.run_registry.get("runs", []):
            status = run.get("status", "planned")
            if status in status_counts:
                status_counts[status] += 1
            approval = run.get("approval", {})
            if approval.get("status") in {"pending", "requested"}:
                pending_run_approvals += 1
            if run.get("evaluation_status") == "fail":
                evaluation_failures += 1
            if run.get("evaluation_status") == "warn":
                evaluation_warns += 1
            selection_status = run.get("selection", {}).get("status")
            if selection_status == "preferred":
                preferred_runs += 1
            elif selection_status == "candidate":
                candidate_runs += 1

        return {
            "evidence_items": len(self.evidence_registry.get("items", [])),
            "baseline_items": len(self.baseline_registry.get("items", [])),
            "claim_count": len(self.claims.get("claims", [])),
            "result_count": len(self.results_registry.get("results", [])),
            "artifact_items": len(self.artifact_registry.get("items", [])),
            "run_count": len(self.run_registry.get("runs", [])),
            "succeeded_runs": status_counts["succeeded"],
            "completed_runs": status_counts["succeeded"],
            "queued_runs": status_counts["queued"],
            "leased_runs": status_counts["leased"],
            "running_runs": status_counts["running"],
            "retryable_runs": status_counts["retryable"],
            "blocked_runs": status_counts["blocked"],
            "failed_runs": status_counts["failed"],
            "cancelled_runs": status_counts["cancelled"],
            "queued_or_running_runs": status_counts["queued"] + status_counts["leased"] + status_counts["running"],
            "pending_run_approvals": pending_run_approvals,
            "evaluation_failures": evaluation_failures,
            "evaluation_warns": evaluation_warns,
            "preferred_runs": preferred_runs,
            "candidate_runs": candidate_runs,
            "session_count": len(self.session_registry.get("sessions", [])),
        }
