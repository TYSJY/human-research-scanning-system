from __future__ import annotations

from typing import Any

from .common import coerce_str_list, load_json, lookup_path, now_iso, resource_path
from .workspace import WorkspaceSnapshot


DEFAULT_WEIGHTS = {
    "metrics_presence": 10,
    "result_value_presence": 15,
    "artifact_integrity": 15,
    "claim_result_consistency": 30,
    "evidence_coverage": 15,
    "provenance_completeness": 15,
}


def load_evaluator_registry() -> dict[str, Any]:
    return load_json(resource_path("control_plane", "workflows", "evaluator_registry.json"), {"evaluators": []})


def _compare(actual: Any, comparator: str | None, expected: Any) -> bool:
    if comparator in {None, "informational"}:
        return actual is not None
    if actual is None:
        return False
    if comparator == ">":
        return actual > expected
    if comparator == ">=":
        return actual >= expected
    if comparator == "<":
        return actual < expected
    if comparator == "<=":
        return actual <= expected
    if comparator == "==":
        return actual == expected
    if comparator == "!=":
        return actual != expected
    raise ValueError(f"Unsupported comparator: {comparator}")


def _record(records: list[dict[str, Any]], evaluator: str, status: str, summary: str, score: float | None = None, details: dict[str, Any] | None = None) -> None:
    weight = DEFAULT_WEIGHTS.get(evaluator, 10)
    if score is None:
        score = 100.0 if status == "pass" else 60.0 if status == "warn" else 0.0
    records.append(
        {
            "evaluator": evaluator,
            "status": status,
            "summary": summary,
            "score": float(score),
            "weight": weight,
            "details": details or {},
        }
    )


def _aggregate_status(records: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in records}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _aggregate_score(records: list[dict[str, Any]]) -> float:
    total_weight = sum(float(item.get("weight", 0) or 0) for item in records)
    if total_weight <= 0:
        return 0.0
    weighted = sum(float(item.get("score", 0) or 0) * float(item.get("weight", 0) or 0) for item in records)
    return round(weighted / total_weight, 2)


def _involved_claims(workspace: WorkspaceSnapshot, run_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
    claim_ids = {item.get("claim_id") for item in workspace.results_registry.get("results", []) if item.get("run_id") == run_id and item.get("claim_id")}
    for spec in request.get("register_results", []):
        if spec.get("claim_id"):
            claim_ids.add(spec["claim_id"])
    return [claim for claim in workspace.claims.get("claims", []) if claim.get("claim_id") in claim_ids]


def _expected_artifact_paths(request: dict[str, Any]) -> list[str]:
    expected_paths: list[str] = []
    for item in request.get("expected_artifacts", []) or []:
        if isinstance(item, str):
            expected_paths.append(item)
        elif isinstance(item, dict) and item.get("path"):
            expected_paths.append(item["path"])
    if not expected_paths:
        expected_paths = ["stdout.log", "stderr.log", request.get("metrics_output", "metrics.json")]
    return list(dict.fromkeys(expected_paths))


def _selector_group(run: dict[str, Any], request: dict[str, Any]) -> str:
    return lookup_path(run, "selection.group") or run.get("queue_group") or lookup_path(run, "selector.group") or request.get("queue_group") or lookup_path(request, "selector.group") or run.get("task_id") or run.get("run_id")


def _selector_min_score(run: dict[str, Any], request: dict[str, Any]) -> float:
    value = lookup_path(run, "selector.min_score_to_promote", lookup_path(request, "selector.min_score_to_promote", 75))
    try:
        return float(value)
    except Exception:
        return 75.0


def _update_run_selection(workspace: WorkspaceSnapshot) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    requests: dict[str, dict[str, Any]] = {}
    for run in workspace.run_registry.get("runs", []):
        run_id = run.get("run_id")
        if not run_id:
            continue
        request = workspace.load_run_request(run_id)
        requests[run_id] = request
        group = _selector_group(run, request)
        run.setdefault("selection", {})
        run["selection"].setdefault("group", group)
        groups.setdefault(group, []).append(run)

    for group, runs in groups.items():
        eligible = [
            run
            for run in runs
            if run.get("status") == "succeeded"
            and run.get("evaluation_status") in {"pass", "warn"}
            and lookup_path(run, "selection.score") is not None
        ]
        eligible.sort(
            key=lambda run: (
                -float(lookup_path(run, "selection.score", 0) or 0),
                0 if run.get("evaluation_status") == "pass" else 1,
                int(run.get("attempt_count", 0) or 0),
                run.get("ended_at") or "",
                run.get("run_id") or "",
            )
        )
        winner = eligible[0] if eligible else None
        winner_min_score = _selector_min_score(winner, requests.get(winner.get("run_id"), {})) if winner else 75.0
        for run in runs:
            selection = run.setdefault("selection", {})
            selection.setdefault("group", group)
            selection.setdefault("score", None)
            selection.setdefault("score_breakdown", {})
            selection["best_in_group"] = bool(winner and run.get("run_id") == winner.get("run_id"))
            if run.get("status") != "succeeded":
                selection["status"] = "pending" if run.get("status") not in {"failed", "cancelled"} else "rejected"
            elif run.get("evaluation_status") == "fail":
                selection["status"] = "rejected"
            elif winner and run.get("run_id") == winner.get("run_id"):
                selection["status"] = "preferred" if float(selection.get("score") or 0) >= winner_min_score and run.get("evaluation_status") == "pass" else "candidate"
            else:
                floor = _selector_min_score(run, requests.get(run.get("run_id"), {})) * 0.8
                selection["status"] = "candidate" if float(selection.get("score") or 0) >= floor and run.get("evaluation_status") in {"pass", "warn"} else "rejected"
            selection["updated_at"] = now_iso()
    workspace.runtime["scoreboard_refreshed_at"] = now_iso()
    workspace.save_state("runtime")
    workspace.save_state("run_registry")


def evaluate_run(workspace: WorkspaceSnapshot, run_id: str, persist: bool = True) -> dict[str, Any]:
    run = workspace.get_run(run_id)
    request = workspace.load_run_request(run_id)
    metrics = workspace.load_run_metrics(run_id)
    output_manifest = workspace.load_run_output_manifest(run_id)
    evaluator_names = coerce_str_list(request.get("evaluators"))
    if not evaluator_names:
        evaluator_names = [item.get("name") for item in load_evaluator_registry().get("evaluators", []) if item.get("name")]
    records: list[dict[str, Any]] = []

    metrics_root = metrics.get("metrics")
    if "metrics_presence" in evaluator_names:
        if isinstance(metrics_root, dict) and metrics_root:
            _record(records, "metrics_presence", "pass", "metrics.json contains a non-empty metrics object.")
        else:
            _record(records, "metrics_presence", "fail", "metrics.json is missing or empty.", 0.0, {"metrics_path": f"runs/{run_id}/metrics.json"})

    if "result_value_presence" in evaluator_names:
        missing_result_paths: list[dict[str, Any]] = []
        total_specs = len(request.get("register_results", []))
        for spec in request.get("register_results", []):
            value = lookup_path(metrics, spec.get("value_path", ""))
            if value is None:
                missing_result_paths.append({"result_id": spec.get("result_id"), "value_path": spec.get("value_path")})
        if missing_result_paths:
            coverage = max(total_specs - len(missing_result_paths), 0) / max(total_specs, 1) * 100.0
            _record(records, "result_value_presence", "fail", "Some register_results value_path entries could not be resolved from metrics.json.", coverage, {"missing": missing_result_paths})
        else:
            _record(records, "result_value_presence", "pass", "All register_results value_path entries resolved from metrics.json.")

    files_by_path = {item.get("path"): item for item in output_manifest.get("files", [])}
    if "artifact_integrity" in evaluator_names:
        expected_artifacts = _expected_artifact_paths(request)
        missing_artifacts = [path for path in expected_artifacts if path not in files_by_path]
        if missing_artifacts:
            coverage = max(len(expected_artifacts) - len(missing_artifacts), 0) / max(len(expected_artifacts), 1) * 100.0
            _record(records, "artifact_integrity", "fail", "Expected run artifacts are missing from output_manifest.json.", coverage, {"missing_artifacts": missing_artifacts})
        else:
            _record(records, "artifact_integrity", "pass", "Expected run artifacts are present and hashed in output_manifest.json.")

    claims = _involved_claims(workspace, run_id, request)
    if "claim_result_consistency" in evaluator_names or "evidence_coverage" in evaluator_names:
        if not claims:
            if "claim_result_consistency" in evaluator_names:
                _record(records, "claim_result_consistency", "warn", "No claim-linked results were associated with this run.", 60.0)
            if "evidence_coverage" in evaluator_names:
                _record(records, "evidence_coverage", "warn", "No claim-linked results were associated with this run.", 60.0)
        else:
            results_by_metric = {
                item.get("metric"): item
                for item in workspace.results_registry.get("results", [])
                if item.get("run_id") == run_id and item.get("metric")
            }
            claim_failures: list[dict[str, Any]] = []
            coverage_failures: list[dict[str, Any]] = []
            coverage_warnings: list[dict[str, Any]] = []
            checks_total = 0
            checks_passed = 0
            min_evidence_refs = load_json(resource_path("control_plane", "workflows", "guardrail_policy.json"), {}).get("min_evidence_refs_per_claim", 2)
            known_evidence_ids = {item.get("evidence_id") for item in workspace.evidence_registry.get("items", [])}
            for claim in claims:
                checks = claim.get("acceptance_checks", [])
                if not checks:
                    claim_failures.append({"claim_id": claim.get("claim_id"), "reason": "missing_acceptance_checks"})
                for check in checks:
                    checks_total += 1
                    metric = check.get("metric")
                    result = results_by_metric.get(metric)
                    if result is None:
                        claim_failures.append({"claim_id": claim.get("claim_id"), "metric": metric, "reason": "missing_result"})
                        continue
                    actual = result.get("value")
                    comparator = check.get("comparator", check.get("operator", ">="))
                    threshold = check.get("threshold")
                    if threshold is None and comparator != "informational":
                        claim_failures.append({"claim_id": claim.get("claim_id"), "metric": metric, "reason": "missing_threshold"})
                        continue
                    if _compare(actual, comparator, threshold):
                        checks_passed += 1
                    else:
                        claim_failures.append(
                            {
                                "claim_id": claim.get("claim_id"),
                                "metric": metric,
                                "actual": actual,
                                "comparator": comparator,
                                "threshold": threshold,
                            }
                        )

                evidence_refs = claim.get("evidence_refs", [])
                existing_refs = [ref for ref in evidence_refs if ref in known_evidence_ids]
                if len(existing_refs) < min_evidence_refs:
                    item = {"claim_id": claim.get("claim_id"), "existing_refs": existing_refs, "required": min_evidence_refs}
                    if claim.get("status") in {"promoted", "locked"}:
                        coverage_failures.append(item)
                    else:
                        coverage_warnings.append(item)

            if "claim_result_consistency" in evaluator_names:
                score = (checks_passed / max(checks_total, 1)) * 100.0 if checks_total else 40.0
                if claim_failures:
                    _record(records, "claim_result_consistency", "fail", "At least one claim acceptance check failed or could not be evaluated.", score, {"failures": claim_failures, "checks_passed": checks_passed, "checks_total": checks_total})
                else:
                    _record(records, "claim_result_consistency", "pass", "All available claim acceptance checks passed for this run.", score or 100.0, {"checks_passed": checks_passed, "checks_total": checks_total})

            if "evidence_coverage" in evaluator_names:
                total_claims = max(len(claims), 1)
                passed_claims = len(claims) - len(coverage_failures) - len(coverage_warnings)
                score = max(passed_claims / total_claims * 100.0, 0.0)
                if coverage_failures:
                    _record(records, "evidence_coverage", "fail", "Promoted or locked claims are missing sufficient evidence coverage.", score, {"failures": coverage_failures})
                elif coverage_warnings:
                    _record(records, "evidence_coverage", "warn", "Some draft claims still have weak evidence coverage.", max(score, 60.0), {"warnings": coverage_warnings})
                else:
                    _record(records, "evidence_coverage", "pass", "Claim evidence coverage meets the configured minimum.", score or 100.0)

    if "provenance_completeness" in evaluator_names:
        run_results = [item for item in workspace.results_registry.get("results", []) if item.get("run_id") == run_id]
        missing_fields: list[dict[str, Any]] = []
        required_fields = ["source", "run_id", "metrics_output", "metrics_sha256", "output_manifest_path"]
        for result in run_results:
            provenance = result.get("provenance", {})
            missing = [field for field in required_fields if not provenance.get(field)]
            if missing:
                missing_fields.append({"result_id": result.get("result_id"), "missing": missing})
        if missing_fields:
            score = max(len(run_results) - len(missing_fields), 0) / max(len(run_results), 1) * 100.0
            _record(records, "provenance_completeness", "fail", "Some registered results are missing required provenance fields.", score, {"missing": missing_fields})
        else:
            _record(records, "provenance_completeness", "pass", "All run-linked results have the required provenance fields.")

    overall = _aggregate_status(records)
    overall_score = _aggregate_score(records)
    payload = {
        "run_id": run_id,
        "evaluated_at": now_iso(),
        "overall_status": overall,
        "overall_score": overall_score,
        "records": records,
    }

    if persist and run is not None:
        for record in records:
            workspace.upsert_evaluation(
                {
                    "target_type": "run",
                    "target_id": run_id,
                    "evaluator": record["evaluator"],
                    "status": record["status"],
                    "score": record.get("score"),
                    "weight": record.get("weight"),
                    "summary": record["summary"],
                    "details": record["details"],
                    "checks": record["details"].get("checks", []),
                    "created_at": payload["evaluated_at"],
                }
            )
        run["evaluation_status"] = overall
        run["last_evaluated_at"] = payload["evaluated_at"]
        run.setdefault("selection", {})
        run["selection"].update(
            {
                "group": _selector_group(run, request),
                "score": overall_score,
                "score_breakdown": {record["evaluator"]: {"status": record["status"], "score": record.get("score"), "weight": record.get("weight")} for record in records},
                "updated_at": payload["evaluated_at"],
            }
        )
        workspace.save_state("run_registry")
        _update_run_selection(workspace)
    return payload
