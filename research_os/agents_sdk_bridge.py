from __future__ import annotations

from pathlib import Path
from typing import Any


def build_agents_sdk_runtime(project_dir: str | Path) -> dict[str, Any]:
    """
    Optional bridge for teams that want to re-host the controller/specialists
    on top of the OpenAI Agents SDK.

    The local workspace state remains the source of truth. This bridge only
    exposes read tools plus a suggested agent decomposition so the SDK can be
    layered on top without replacing the canonical state/runtime model.
    """
    try:
        from agents import Agent, Runner, function_tool  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency only
        raise RuntimeError(
            "OpenAI Agents SDK is not installed in this environment. "
            "Use the local runtime directly or install the SDK before calling build_agents_sdk_runtime()."
        ) from exc

    @function_tool
    def get_workspace_summary() -> str:
        from .workspace import WorkspaceSnapshot
        from .planner import build_plan

        workspace = WorkspaceSnapshot.load(project_dir)
        plan = build_plan(workspace, persist=False)
        return str({"project": workspace.project, "stage_state": workspace.stage_state, "plan": plan})

    @function_tool
    def get_run_registry() -> str:
        from .workspace import WorkspaceSnapshot

        workspace = WorkspaceSnapshot.load(project_dir)
        return str(workspace.run_registry)

    @function_tool
    def get_evaluations() -> str:
        from .workspace import WorkspaceSnapshot

        workspace = WorkspaceSnapshot.load(project_dir)
        return str(workspace.evaluation_registry)

    @function_tool
    def get_scheduler_snapshot() -> str:
        from .workspace import WorkspaceSnapshot
        from .scheduler import build_scheduler_snapshot

        workspace = WorkspaceSnapshot.load(project_dir)
        return str(build_scheduler_snapshot(workspace, worker_labels=[]))

    controller = Agent(
        name="Research Lead",
        instructions=(
            "Use get_workspace_summary to decide whether to hand off, request a gate, or transition stages. "
            "Treat the local workspace state as canonical."
        ),
        tools=[get_workspace_summary, get_run_registry, get_evaluations, get_scheduler_snapshot],
    )

    execution = Agent(
        name="Experiment Operator",
        instructions=(
            "Use get_run_registry and get_evaluations to inspect runtime backlog, retries, approvals and evaluation failures. "
            "Do not assume runs are safe just because they exist."
        ),
        tools=[get_workspace_summary, get_run_registry, get_evaluations, get_scheduler_snapshot],
    )
    return {"controller": controller, "execution": execution, "runner": Runner}
