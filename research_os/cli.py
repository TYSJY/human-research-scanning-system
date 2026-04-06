from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bootstrap import copy_demo_project, create_project_from_template
from .common import now_iso
from .executors import approve_run, cancel_run, ingest_run_output, reap_expired_leases, retry_run, run_one, run_worker
from .migrate import migrate_v3_project, upgrade_v4_1_project
from .orchestrator import run_once, run_workloop
from .planner import build_plan
from .reporting import build_audit_report, build_showcase_package
from .scheduler import build_scheduler_snapshot
from .sqlite_sync import sync_project_sqlite
from .tools import execute_tool
from .ux import (
    APP_NAME,
    APP_VERSION,
    detect_default_owner,
    doctor_report,
    humanize_exception,
    next_available_name,
    pick_pending_approval,
    project_dashboard,
    render_doctor_text,
    render_home_text,
    render_project_text,
    render_run_text,
)
from .validation import validate_workspace
from .webapp import serve_ui
from .workspace import WorkspaceSnapshot


class FriendlyArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"\n我没能理解这个命令：{message}", file=sys.stderr)
        print("先试试：ros quickstart  或  ros --help", file=sys.stderr)
        raise SystemExit(2)



def _json_arg(value: str, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)



def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))



def _success_lines(title: str, extra: list[str] | None = None) -> None:
    print(title)
    if extra:
        for item in extra:
            print(item)



def _post_create_message(project_dir: str | Path) -> None:
    dashboard = project_dashboard(project_dir)
    print(render_project_text(dashboard))



def _resolve_project_root(args: argparse.Namespace) -> str:
    return getattr(args, "root", "projects") or "projects"



def cmd_home(_: argparse.Namespace | None = None) -> int:
    print(render_home_text())
    return 0



def cmd_init(args: argparse.Namespace) -> int:
    root = args.root or "projects"
    title = (args.title or "My First Research Project").strip()
    name = (args.name or "").strip()
    if not name:
        name = next_available_name(root, title)
    target = create_project_from_template(
        root,
        name,
        title,
        owner=(args.owner or detect_default_owner()).strip() or detect_default_owner(),
        venue=(args.venue or "未设定").strip() or "未设定",
    )
    print(f"已创建新项目：{target}\n")
    _post_create_message(target)
    if args.launch_ui:
        serve_ui(str(target), root=root, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0



def cmd_demo(args: argparse.Namespace) -> int:
    root = args.root or "projects"
    base_name = (args.name or "").strip() or "research-os-demo"
    name = next_available_name(root, base_name)
    target = copy_demo_project(root, name, title=args.title or None, owner=args.owner or None, venue=args.venue or None)
    print(f"已复制演示项目：{target}\n")
    _post_create_message(target)
    if args.launch_ui:
        serve_ui(str(target), root=root, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0



def cmd_quickstart(args: argparse.Namespace) -> int:
    if args.blank:
        inner = argparse.Namespace(
            root=args.root,
            name=args.name,
            title=args.title or "My First Research Project",
            owner=args.owner,
            venue=args.venue,
            launch_ui=args.launch_ui,
            host=args.host,
            port=args.port,
            no_browser=args.no_browser,
        )
        return cmd_init(inner)
    inner = argparse.Namespace(
        root=args.root,
        name=args.name,
        title=args.title,
        owner=args.owner,
        venue=args.venue,
        launch_ui=args.launch_ui,
        host=args.host,
        port=args.port,
        no_browser=args.no_browser,
    )
    print("正在准备一个可直接体验的科研助手演示项目...\n")
    return cmd_demo(inner)



def cmd_doctor(args: argparse.Namespace) -> int:
    report = doctor_report(args.project_dir, root=_resolve_project_root(args))
    print(render_doctor_text(report))
    return 1 if report["overall"] == "fail" else 0



def cmd_status(args: argparse.Namespace) -> int:
    if not args.project_dir:
        print(render_home_text(_resolve_project_root(args)))
        return 0
    dashboard = project_dashboard(args.project_dir)
    print(render_project_text(dashboard))
    return 0



def cmd_run(args: argparse.Namespace) -> int:
    if args.steps and args.steps > 1:
        result = run_workloop(
            args.project_dir,
            provider_name=args.provider,
            steps=args.steps,
            config_path=args.config,
            auto_execute=not args.no_auto_execute,
            user_context={"note": args.note} if args.note else None,
        )
    else:
        result = run_once(
            args.project_dir,
            provider_name=args.provider,
            agent_name=None,
            profile=None,
            config_path=args.config,
            apply=True,
            dry_run=False,
            auto_execute=not args.no_auto_execute,
            user_context={"note": args.note} if args.note else None,
        )
    print(render_run_text(args.project_dir, result))
    return 0



def cmd_approve(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    if args.run_id:
        payload = approve_run(workspace, args.run_id, by=args.by, note=args.note, queue_after=not args.no_queue_after)
        print(f"已批准任务：{args.run_id}")
        if payload.get("queued"):
            print("该任务已自动继续排队。")
        return 0
    if args.gate_id:
        workspace.update_gate(args.gate_id, status="approved", approved_by=args.by, approved_note=args.note, approved_at=now_iso())
        sync_project_sqlite(args.project_dir)
        print(f"已批准人工确认：{args.gate_id}")
        return 0

    pending = pick_pending_approval(workspace)
    if pending is None:
        print("当前没有待确认事项。")
        print("你可以继续运行 ros run <项目路径>，或打开 ros ui <项目路径> 查看下一步。")
        return 0

    if pending["kind"] == "run":
        payload = approve_run(workspace, pending["id"], by=args.by, note=args.note or "Approved from ros approve", queue_after=not args.no_queue_after)
        print(f"已批准任务：{pending['title']}")
        if payload.get("queued"):
            print("该任务已自动继续排队。")
        return 0

    workspace.update_gate(pending["id"], status="approved", approved_by=args.by, approved_note=args.note or "Approved from ros approve", approved_at=now_iso())
    sync_project_sqlite(args.project_dir)
    print(f"已批准人工确认：{pending['title']}")
    return 0



def cmd_audit(args: argparse.Namespace) -> int:
    out = build_audit_report(args.project_dir, args.output)
    report = doctor_report(args.project_dir, root=_resolve_project_root(args))
    print(f"已生成审计报告：{out}\n")
    print(render_doctor_text(report))
    return 1 if report["overall"] == "fail" else 0


def cmd_showcase(args: argparse.Namespace) -> int:
    outputs = build_showcase_package(args.project_dir, args.output_dir)
    print("已导出研究成果物：")
    for key, path in outputs.items():
        print(f"- {key}: {path}")
    return 0



def cmd_ui(args: argparse.Namespace) -> int:
    serve_ui(args.project_dir, root=args.root, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0



def cmd_summary(args: argparse.Namespace) -> int:
    return cmd_status(args)



def cmd_plan(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    plan = build_plan(workspace)
    _emit(plan)
    return 0



def cmd_scheduler(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    snapshot = build_scheduler_snapshot(workspace, worker_labels=args.worker_labels or [])
    _emit(snapshot)
    return 0



def cmd_orchestrate(args: argparse.Namespace) -> int:
    result = run_once(
        args.project_dir,
        provider_name=args.provider,
        agent_name=args.agent,
        profile=args.profile,
        config_path=args.config,
        apply=not args.no_apply,
        dry_run=args.dry_run,
        auto_execute=args.auto_execute,
        user_context={"note": args.note} if args.note else None,
    )
    _emit(result)
    return 0



def cmd_workloop(args: argparse.Namespace) -> int:
    result = run_workloop(
        args.project_dir,
        provider_name=args.provider,
        steps=args.steps,
        config_path=args.config,
        auto_execute=args.auto_execute,
        user_context={"note": args.note} if args.note else None,
    )
    _emit(result)
    return 0



def cmd_create_run(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    manifest = {
        "run_id": args.run_id,
        "question": args.question,
        "model": args.model,
        "dataset": args.dataset,
        "baselines": args.baselines,
        "metrics": args.metrics,
        "hardware": args.hardware,
        "status": "planned",
        "created_at": now_iso(),
    }
    request = {
        "executor": args.executor,
        "command": _json_arg(args.command_json, []),
        "executor_profile": args.executor_profile or None,
        "timeout_sec": args.timeout_sec if args.timeout_sec and args.timeout_sec > 0 else None,
        "metrics_output": args.metrics_output,
        "register_results": _json_arg(args.register_results_json, []),
        "expected_artifacts": _json_arg(args.expected_artifacts_json, []),
        "resource_budget": {
            "estimated_gpu_hours": args.estimated_gpu_hours,
            "estimated_tokens": args.estimated_tokens,
        },
        "approval": {
            "required": args.approval_required,
            "reason": args.approval_reason,
            "risk_tags": _json_arg(args.risk_tags_json, []),
        },
        "task_id": args.task_id or None,
        "depends_on_runs": args.depends_on_runs or [],
        "queue_group": args.queue_group or None,
        "reasoning_profile": args.reasoning_profile or None,
        "worker_requirements": {"labels": args.worker_labels or []},
        "selector": {
            "group": args.selector_group or args.queue_group or args.run_id,
            "min_score_to_promote": args.selector_min_score,
            "stop_after_preferred": args.selector_stop_after_preferred,
        },
        "created_from_session_id": args.created_from_session_id or None,
        "notes": args.request_note,
    }
    execute_tool(
        workspace,
        "create_run",
        {
            "run_id": args.run_id,
            "task_id": args.task_id or None,
            "queue_group": args.queue_group or None,
            "reasoning_profile": args.reasoning_profile or None,
            "depends_on_runs": args.depends_on_runs or [],
            "worker_requirements": {"labels": args.worker_labels or []},
            "selector": {
                "group": args.selector_group or args.queue_group or args.run_id,
                "min_score_to_promote": args.selector_min_score,
                "stop_after_preferred": args.selector_stop_after_preferred,
            },
            "created_from_session_id": args.created_from_session_id or None,
            "manifest": manifest,
            "request": request,
            "priority": args.priority,
        },
        actor="human",
        profile="manual",
    )
    if args.queue_after:
        execute_tool(workspace, "queue_run", {"run_id": args.run_id, "priority": args.priority}, actor="human", profile="manual")
    sync_project_sqlite(args.project_dir)
    print(f"[OK] Run created: {args.run_id}")
    return 0



def cmd_queue_run(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    message = execute_tool(workspace, "queue_run", {"run_id": args.run_id, "priority": args.priority}, actor="human", profile="manual")
    sync_project_sqlite(args.project_dir)
    print(f"[OK] {message}")
    return 0



def cmd_run_worker(args: argparse.Namespace) -> int:
    if args.run_id and args.run_id != "*":
        workspace = WorkspaceSnapshot.load(args.project_dir)
        result = [run_one(workspace, args.run_id, dry_run=args.dry_run, worker_id=args.worker_id, worker_labels=args.worker_labels or [])]
    else:
        result = run_worker(args.project_dir, worker_id=args.worker_id, max_runs=args.max_runs, dry_run=args.dry_run, worker_labels=args.worker_labels or [])
    _emit(result)
    return 0



def cmd_validate(args: argparse.Namespace) -> int:
    report = doctor_report(args.project_dir, root=_resolve_project_root(args))
    print(render_doctor_text(report))
    return 1 if report["overall"] == "fail" else 0



def cmd_approve_gate(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    workspace.update_gate(
        args.gate_id,
        status="approved",
        approved_by=args.by,
        approved_note=args.note,
        approved_at=now_iso(),
    )
    sync_project_sqlite(args.project_dir)
    print(f"[OK] Gate approved: {args.gate_id}")
    return 0



def cmd_approve_run(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    payload = approve_run(workspace, args.run_id, by=args.by, note=args.note, queue_after=args.queue_after)
    _emit(payload)
    return 0



def cmd_cancel_run(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    payload = cancel_run(workspace, args.run_id, by=args.by, note=args.note)
    _emit(payload)
    return 0



def cmd_retry_run(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    payload = retry_run(workspace, args.run_id, by=args.by, reset_attempts=args.reset_attempts)
    _emit(payload)
    return 0



def cmd_ingest_run_output(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    payload = ingest_run_output(
        workspace,
        run_id=args.run_id,
        status=args.status,
        metrics_file=args.metrics_file,
        exit_code=args.exit_code,
        additional_artifacts=args.additional_artifacts,
        note=args.note,
    )
    _emit(payload)
    return 0



def cmd_reap_leases(args: argparse.Namespace) -> int:
    workspace = WorkspaceSnapshot.load(args.project_dir)
    count = reap_expired_leases(workspace)
    print(f"[OK] Reaped leases: {count}")
    return 0



def cmd_sync_sqlite(args: argparse.Namespace) -> int:
    out = sync_project_sqlite(args.project_dir, args.output)
    print(f"[OK] SQLite synced: {out}")
    return 0



def cmd_migrate_v3(args: argparse.Namespace) -> int:
    target = migrate_v3_project(args.v3_project_dir, args.output)
    print(f"[OK] Migrated to: {target}")
    return 0



def cmd_upgrade_v4_1(args: argparse.Namespace) -> int:
    target = upgrade_v4_1_project(args.v4_1_project_dir, args.output)
    print(f"[OK] Upgraded to V4.8 at: {target}")
    return 0



def build_parser() -> argparse.ArgumentParser:
    parser = FriendlyArgumentParser(
        description=f"{APP_NAME} {APP_VERSION} · 专业级 AI 科研助手：文献综述、研究设计、学术写作与可复现研究工作流",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "新手优先命令：\n"
            "  ros quickstart\n"
            "  ros init\n"
            "  ros demo\n"
            "  ros ui [项目路径]\n"
            "  ros run <项目路径>\n"
            "  ros approve <项目路径>\n"
            "  ros doctor [项目路径]\n\n"
            "高级命令仍然保留，但第一次使用时建议先围绕 evidence、claim、run 和 deliverable 来理解系统。"
        ),
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=False)

    # New user-facing entry points
    p = sub.add_parser("quickstart", help="一键准备第一次成功体验。默认复制官方科研助手演示项目。")
    p.add_argument("--blank", action="store_true", help="改为创建空项目，而不是复制演示项目。")
    p.add_argument("--root", default="projects")
    p.add_argument("--name", default="")
    p.add_argument("--title", default="")
    p.add_argument("--owner", default="")
    p.add_argument("--venue", default="")
    p.add_argument("--launch-ui", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_quickstart)

    p = sub.add_parser("init", aliases=["init-project"], help="创建一个新的空项目。")
    p.add_argument("--root", default="projects")
    p.add_argument("--name", default="")
    p.add_argument("--title", default="My First Research Project")
    p.add_argument("--owner", default="")
    p.add_argument("--venue", default="未设定")
    p.add_argument("--launch-ui", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("demo", help="复制一个内置科研助手演示项目，立刻开始体验。")
    p.add_argument("--root", default="projects")
    p.add_argument("--name", default="")
    p.add_argument("--title", default="")
    p.add_argument("--owner", default="")
    p.add_argument("--venue", default="")
    p.add_argument("--launch-ui", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("status", aliases=["summary"], help="用普通用户能看懂的方式查看项目状态。")
    p.add_argument("project_dir", nargs="?")
    p.add_argument("--root", default="projects")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="检查环境或项目问题，并给出修复建议。")
    p.add_argument("project_dir", nargs="?")
    p.add_argument("--root", default="projects")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("run", help="让系统自动推进下一步。默认会自动执行安全任务。")
    p.add_argument("project_dir")
    p.add_argument("--provider", default="mock", choices=["mock", "openai"])
    p.add_argument("--steps", type=int, default=1)
    p.add_argument("--config", default=None)
    p.add_argument("--note", default="")
    p.add_argument("--no-auto-execute", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("approve", help="批准下一个待确认项，或显式批准某个 gate/run。")
    p.add_argument("project_dir")
    p.add_argument("--gate", dest="gate_id", default="")
    p.add_argument("--run", dest="run_id", default="")
    p.add_argument("--by", default="human")
    p.add_argument("--note", default="")
    p.add_argument("--no-queue-after", action="store_true")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("audit", aliases=["audit-report"], help="生成审计报告，并告诉你项目是否健康。")
    p.add_argument("project_dir")
    p.add_argument("--output", default=None)
    p.add_argument("--root", default="projects")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("showcase", help="导出 research brief、evidence matrix 和 deliverable index。")
    p.add_argument("project_dir")
    p.add_argument("--output-dir", default=None)
    p.set_defaults(func=cmd_showcase)

    p = sub.add_parser("ui", help="启动浏览器工作台。")
    p.add_argument("project_dir", nargs="?")
    p.add_argument("--root", default="projects")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_ui)

    # Advanced commands kept for power users
    p = sub.add_parser("plan", help="[高级] 输出 planner JSON。")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("scheduler", help="[高级] 输出 scheduler 快照。")
    p.add_argument("project_dir")
    p.add_argument("--worker-labels", nargs="*", default=[])
    p.set_defaults(func=cmd_scheduler)

    p = sub.add_parser("orchestrate", help="[高级] 运行一次底层 provider 编排循环。")
    p.add_argument("project_dir")
    p.add_argument("--provider", default="mock", choices=["mock", "openai"])
    p.add_argument("--agent", default=None, choices=["controller", "scan", "design", "execution", "writing", "audit"])
    p.add_argument("--profile", default=None, choices=["think", "pro", "deep_research"])
    p.add_argument("--config", default=None)
    p.add_argument("--no-apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--auto-execute", action="store_true")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_orchestrate)

    p = sub.add_parser("workloop", help="[高级] 连续运行多步底层编排。")
    p.add_argument("project_dir")
    p.add_argument("--provider", default="mock", choices=["mock", "openai"])
    p.add_argument("--steps", type=int, default=3)
    p.add_argument("--config", default=None)
    p.add_argument("--auto-execute", action="store_true")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_workloop)

    p = sub.add_parser("create-run", help="[高级] 手动创建 run。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--question", default="replace-me")
    p.add_argument("--model", default="replace-me")
    p.add_argument("--dataset", default="replace-me")
    p.add_argument("--baselines", nargs="*", default=[])
    p.add_argument("--metrics", nargs="*", default=[])
    p.add_argument("--hardware", default="replace-me")
    p.add_argument("--executor", default="manual", choices=["manual", "shell", "external"])
    p.add_argument("--executor-profile", default="")
    p.add_argument("--command-json", default="")
    p.add_argument("--timeout-sec", type=int, default=None)
    p.add_argument("--metrics-output", default="metrics.json")
    p.add_argument("--register-results-json", default="")
    p.add_argument("--expected-artifacts-json", default="")
    p.add_argument("--estimated-gpu-hours", type=float, default=0.0)
    p.add_argument("--estimated-tokens", type=int, default=0)
    p.add_argument("--approval-required", action="store_true")
    p.add_argument("--approval-reason", default="")
    p.add_argument("--risk-tags-json", default="")
    p.add_argument("--request-note", default="")
    p.add_argument("--task-id", default="")
    p.add_argument("--depends-on-runs", nargs="*", default=[])
    p.add_argument("--queue-group", default="")
    p.add_argument("--reasoning-profile", default="")
    p.add_argument("--worker-labels", nargs="*", default=[])
    p.add_argument("--selector-group", default="")
    p.add_argument("--selector-min-score", type=float, default=75.0)
    p.add_argument("--selector-stop-after-preferred", action="store_true")
    p.add_argument("--created-from-session-id", default="")
    p.add_argument("--queue-after", action="store_true")
    p.add_argument("--priority", default="normal", choices=["critical", "high", "normal", "low"])
    p.set_defaults(func=cmd_create_run)

    p = sub.add_parser("queue-run", help="[高级] 手动排队一个 run。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--priority", default="normal", choices=["critical", "high", "normal", "low"])
    p.set_defaults(func=cmd_queue_run)

    p = sub.add_parser("run-worker", help="[高级] 启动 worker 处理队列。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", default="*")
    p.add_argument("--worker-id", default="worker-local")
    p.add_argument("--max-runs", type=int, default=1)
    p.add_argument("--worker-labels", nargs="*", default=[])
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_run_worker)

    p = sub.add_parser("run-executor", help="[高级] run-worker 的兼容别名。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", default="*")
    p.add_argument("--worker-id", default="worker-local")
    p.add_argument("--max-runs", type=int, default=1)
    p.add_argument("--worker-labels", nargs="*", default=[])
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_run_worker)

    p = sub.add_parser("approve-gate", help="[高级] 直接批准一个 gate。")
    p.add_argument("project_dir")
    p.add_argument("--gate-id", required=True)
    p.add_argument("--by", default="human")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_approve_gate)

    p = sub.add_parser("approve-run", help="[高级] 直接批准一个 run。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--by", default="human")
    p.add_argument("--note", default="")
    p.add_argument("--queue-after", action="store_true")
    p.set_defaults(func=cmd_approve_run)

    p = sub.add_parser("cancel-run", help="[高级] 取消一个 run。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--by", default="human")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_cancel_run)

    p = sub.add_parser("retry-run", help="[高级] 重试一个失败或被阻塞的 run。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--by", default="human")
    p.add_argument("--reset-attempts", action="store_true")
    p.set_defaults(func=cmd_retry_run)

    p = sub.add_parser("ingest-run-output", help="[高级] 回灌外部产出的结果。")
    p.add_argument("project_dir")
    p.add_argument("--run-id", required=True)
    p.add_argument("--status", default="succeeded", choices=["succeeded", "failed", "cancelled", "blocked"])
    p.add_argument("--metrics-file", default=None)
    p.add_argument("--exit-code", type=int, default=0)
    p.add_argument("--additional-artifacts", nargs="*", default=[])
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_ingest_run_output)

    p = sub.add_parser("reap-leases", help="[高级] 清理过期 lease。")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_reap_leases)

    p = sub.add_parser("validate", help="[高级] 验证项目结构（现已输出人性化说明）。")
    p.add_argument("project_dir")
    p.add_argument("--root", default="projects")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("sync-sqlite", help="[高级] 重建 SQLite 镜像。")
    p.add_argument("project_dir")
    p.add_argument("--output", default=None)
    p.set_defaults(func=cmd_sync_sqlite)

    p = sub.add_parser("migrate-v3", help="[高级] 从 V3 迁移到当前布局。")
    p.add_argument("v3_project_dir")
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_migrate_v3)

    p = sub.add_parser("upgrade-v4_1", help="[高级] 升级现有 V4.1 项目。")
    p.add_argument("v4_1_project_dir")
    p.add_argument("--output", default=None)
    p.set_defaults(func=cmd_upgrade_v4_1)

    return parser



def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        return cmd_home(None)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已停止。")
        return 130
    except Exception as exc:
        print(humanize_exception(exc, getattr(args, "cmd", None)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
