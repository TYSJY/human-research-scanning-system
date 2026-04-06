from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import apply_action_plan
from .common import json_hash, now_iso
from .executors import run_worker
from .planner import build_plan
from .providers import MockProvider, OpenAIResponsesProvider
from .workspace import WorkspaceSnapshot


def make_provider(name: str, config_path: str | None = None):
    if name == "mock":
        return MockProvider()
    if name == "openai":
        return OpenAIResponsesProvider(config_path=config_path)
    raise ValueError(f"Unsupported provider: {name}")


def _next_session_id(workspace: WorkspaceSnapshot) -> str:
    next_seq = int(workspace.runtime.get("session_sequence", 0) or 0) + 1
    return f"S{next_seq:04d}"


def _create_session(
    workspace: WorkspaceSnapshot,
    provider_name: str,
    agent_name: str,
    profile: str,
    initial_plan: dict[str, Any],
    user_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = workspace.add_session(
        {
            "session_id": _next_session_id(workspace),
            "provider": provider_name,
            "agent": agent_name,
            "profile": profile,
            "status": "running",
            "started_at": now_iso(),
            "handoff_reason": initial_plan.get("handoff_reason"),
            "current_stage": initial_plan.get("current_stage"),
            "parent_session_id": workspace.runtime.get("last_session_id"),
            "initial_plan_hash": json_hash(initial_plan),
            "user_context": user_context or {},
            "provider_meta": {},
            "result": {},
            "tool_call_count": 0,
            "apply_change_count": 0,
            "executor_run_count": 0,
        }
    )
    workspace.runtime["last_session_id"] = session["session_id"]
    workspace.save_state("runtime")
    workspace.log_event(
        "session_started",
        session_id=session["session_id"],
        provider=provider_name,
        agent=agent_name,
        profile=profile,
        handoff_reason=initial_plan.get("handoff_reason"),
        parent_session_id=session.get("parent_session_id"),
    )
    return session


def _finish_session(workspace: WorkspaceSnapshot, session_id: str, status: str, payload: dict[str, Any]) -> None:
    workspace.update_session(session_id, status=status, ended_at=now_iso(), result=payload)
    workspace.log_event("session_finished", session_id=session_id, status=status)


def run_once(
    project_dir: str | Path,
    provider_name: str = "mock",
    agent_name: str | None = None,
    profile: str | None = None,
    config_path: str | None = None,
    apply: bool = True,
    dry_run: bool = False,
    auto_execute: bool = False,
    user_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = WorkspaceSnapshot.load(project_dir)
    initial_plan = build_plan(workspace)
    resolved_agent = agent_name or initial_plan["recommended_agent"]
    resolved_profile = profile or initial_plan["recommended_profile"]
    session = _create_session(workspace, provider_name, resolved_agent, resolved_profile, initial_plan, user_context=user_context)

    provider = make_provider(provider_name, config_path=config_path)
    provider_result = provider.run(
        resolved_agent,
        workspace,
        resolved_profile,
        user_context={
            **(user_context or {}),
            "session_id": session["session_id"],
            "parent_session_id": session.get("parent_session_id"),
            "handoff_reason": initial_plan.get("handoff_reason"),
            "current_stage": workspace.current_stage,
            "last_plan_hash": workspace.runtime.get("last_plan_hash"),
        },
    )
    action_plan = provider_result["action_plan"]
    provider_meta = provider_result.get("provider_meta", {"provider": provider_name})
    provider_meta.setdefault("session_id", session["session_id"])
    workspace.update_session(session["session_id"], provider_meta=provider_meta)

    apply_result = None
    executor_results: list[dict[str, Any]] = []
    session_status = "completed"
    try:
        if apply:
            apply_result = apply_action_plan(
                workspace,
                action_plan,
                expected_agent=resolved_agent,
                provider_meta=provider_meta,
                dry_run=dry_run,
            )

        if auto_execute and apply and not dry_run:
            executor_results = run_worker(
                project_dir,
                max_runs=1,
                worker_id=f"orchestrator:{session['session_id']}",
                dry_run=False,
                worker_labels=["local", "shell"],
            )
    except Exception as exc:
        session_status = "failed"
        failed_workspace = WorkspaceSnapshot.load(project_dir)
        failed_workspace.update_session(
            session["session_id"],
            status=session_status,
            ended_at=now_iso(),
            final_plan_hash=failed_workspace.runtime.get("last_plan_hash"),
            result={
                "error": str(exc),
                "provider_meta": provider_meta,
            },
        )
        failed_workspace.log_event("session_finished", session_id=session["session_id"], status=session_status)
        raise

    final_workspace = WorkspaceSnapshot.load(project_dir)
    final_plan = build_plan(final_workspace)
    final_workspace.update_session(
        session["session_id"],
        status=session_status,
        ended_at=now_iso(),
        final_plan_hash=json_hash(final_plan),
        tool_call_count=len(action_plan.get("tool_calls", [])),
        apply_change_count=0 if not apply_result else len(apply_result.get("changes", [])),
        executor_run_count=len(executor_results),
        result={
            "provider_meta": provider_meta,
            "apply_change_count": 0 if not apply_result else len(apply_result.get("changes", [])),
            "executor_run_count": len(executor_results),
            "final_stage": final_plan.get("current_stage"),
            "advance_ready": final_plan.get("advance_ready"),
            "recommended_agent": final_plan.get("recommended_agent"),
        },
    )
    final_workspace.log_event("session_finished", session_id=session["session_id"], status=session_status)

    return {
        "project_dir": str(Path(project_dir).resolve()),
        "provider": provider_name,
        "agent": resolved_agent,
        "profile": resolved_profile,
        "session_id": session["session_id"],
        "initial_plan": initial_plan,
        "action_plan": action_plan,
        "provider_meta": provider_meta,
        "apply_result": apply_result,
        "executor_results": executor_results,
        "final_plan": final_plan,
    }


def run_workloop(
    project_dir: str | Path,
    provider_name: str = "mock",
    steps: int = 3,
    config_path: str | None = None,
    auto_execute: bool = True,
    user_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    for _ in range(max(1, steps)):
        workspace = WorkspaceSnapshot.load(project_dir)
        plan = build_plan(workspace)
        if not plan["open_tasks"] and not plan["advance_ready"] and not plan["runtime_backlog"] and not plan["requested_gates"]:
            break
        result = run_once(
            project_dir,
            provider_name=provider_name,
            agent_name=None,
            profile=None,
            config_path=config_path,
            apply=True,
            dry_run=False,
            auto_execute=auto_execute,
            user_context=user_context,
        )
        history.append(result)
        fresh = WorkspaceSnapshot.load(project_dir)
        fresh.runtime["workloop_runs"] = int(fresh.runtime.get("workloop_runs", 0) or 0) + 1
        fresh.save_state("runtime")
        new_plan = build_plan(fresh)
        if result.get("apply_result") and not result["apply_result"].get("changes") and not result.get("executor_results"):
            break
        if not new_plan["open_tasks"] and not new_plan["requested_gates"] and not new_plan["runtime_backlog"] and not new_plan["advance_ready"]:
            break
    final_plan = build_plan(WorkspaceSnapshot.load(project_dir))
    return {"history": history, "final_plan": final_plan}
