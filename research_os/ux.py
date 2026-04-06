from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from .common import parse_iso, read_text, slugify
from .planner import build_plan, load_stage_machine
from .validation import validate_workspace
from .workspace import WorkspaceSnapshot


APP_NAME = "Research OS"
APP_VERSION = "0.6.5"

STAGE_SEQUENCE = ["scan", "design", "execute", "write", "audit"]
STAGE_STATUS_LABELS = {
    "done": "已完成",
    "active": "当前阶段",
    "blocked": "尚未开始",
    "pending": "等待中",
}

NOTE_PRIORITY = [
    "scan.md",
    "novelty_audit.md",
    "experiment_plan.md",
    "results_synthesis.md",
    "title_abstract.md",
    "outline.md",
    "reproducibility_checklist.md",
    "release_checklist.md",
]

STAGE_LABELS: dict[str, dict[str, str]] = {
    "scan": {
        "title": "文献与证据",
        "description": "先补齐 evidence、baseline、相关工作与方向风险。",
        "goal": "让项目从空白状态进入可讨论、可追溯状态。",
    },
    "design": {
        "title": "研究设计",
        "description": "把核心主张、验收条件和 MVP 收敛成可执行方案。",
        "goal": "让项目从想法变成结构化研究计划。",
    },
    "execute": {
        "title": "实验执行",
        "description": "创建并执行 run，回收结果并完成结构化检查。",
        "goal": "让项目拿到第一批可信研究结果。",
    },
    "write": {
        "title": "学术写作",
        "description": "把通过检查的结果整理成摘要、outline 和研究 brief。",
        "goal": "让项目从结果集合变成可交付叙述。",
    },
    "audit": {
        "title": "证据审计",
        "description": "确认输出文件、证据覆盖、复现性和结果一致性都准备好了。",
        "goal": "让项目从草稿进入可审计、可交付状态。",
    },
}

RUN_STATUS_LABELS = {
    "planned": "已创建，未开始",
    "queued": "等待开始",
    "leased": "执行器已接手",
    "running": "正在执行",
    "retryable": "可重试",
    "blocked": "需要你处理",
    "succeeded": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}

EVAL_STATUS_LABELS = {
    None: "未检查",
    "pending": "待检查",
    "pass": "检查通过",
    "warn": "有提醒",
    "fail": "检查失败",
    "informational": "信息提示",
}

GATE_LABELS = {
    "track_selected": "确认研究方向",
    "claim_lock": "确认核心主张",
    "budget_expand": "批准追加预算",
    "submission_ready": "确认可以交付",
}

TERM_MAP = [
    {"technical": "stage", "friendly": "项目阶段", "note": "用来表示项目现在处于哪一步。"},
    {"technical": "task graph", "friendly": "待办清单", "note": "系统自动维护的任务列表。"},
    {"technical": "gate", "friendly": "人工确认", "note": "某些关键节点需要人点头。"},
    {"technical": "run", "friendly": "一次实验 / 一次任务", "note": "每个 run 都会记录执行和结果。"},
    {"technical": "worker", "friendly": "本地执行器", "note": "真正拿起任务去执行的进程。"},
    {"technical": "evaluation", "friendly": "结果检查", "note": "判断结果是否完整、是否可信。"},
    {"technical": "artifact", "friendly": "输出文件", "note": "配置、表格、日志、结果文件等。"},
    {"technical": "scheduler", "friendly": "任务排队器", "note": "决定什么任务可以先开始。"},
    {"technical": "selector", "friendly": "优先结果选择器", "note": "帮助从多个 run 里挑出更好的那个。"},
]

NOTE_LABELS = {
    "scan.md": "扫描与背景",
    "novelty_audit.md": "创新与风险",
    "experiment_plan.md": "实验计划",
    "results_synthesis.md": "结果总结",
    "title_abstract.md": "标题与摘要",
    "outline.md": "正文大纲",
    "reproducibility_checklist.md": "复现清单",
    "release_checklist.md": "发布清单",
}


class UXError(RuntimeError):
    """Raised when a user-facing flow cannot continue safely."""



def detect_default_owner() -> str:
    for key in ["RESEARCH_OS_OWNER", "USER", "USERNAME"]:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return "you"



def next_available_name(root: str | Path, base_name: str) -> str:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    candidate = slugify(base_name)
    if not (root_path / candidate).exists():
        return candidate
    index = 2
    while (root_path / f"{candidate}-{index}").exists():
        index += 1
    return f"{candidate}-{index}"



def stage_title(stage: str) -> str:
    return STAGE_LABELS.get(stage, {}).get("title", stage)



def stage_description(stage: str) -> str:
    return STAGE_LABELS.get(stage, {}).get("description", "")



def stage_goal(stage: str) -> str:
    return STAGE_LABELS.get(stage, {}).get("goal", "")



def gate_title(gate_id: str, fallback: str | None = None) -> str:
    return GATE_LABELS.get(gate_id, fallback or gate_id)



def run_status_title(status: str | None) -> str:
    return RUN_STATUS_LABELS.get(status or "planned", status or "未开始")



def eval_status_title(status: str | None) -> str:
    return EVAL_STATUS_LABELS.get(status, status or "未检查")



def project_exists(path: str | Path) -> bool:
    root = Path(path).resolve()
    return (root / "state" / "project.json").exists()



def list_projects(root: str | Path = "projects") -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    if not root_path.exists():
        return []
    projects: list[dict[str, Any]] = []
    for child in sorted(root_path.iterdir()):
        if not child.is_dir() or not project_exists(child):
            continue
        try:
            workspace = WorkspaceSnapshot.load(child)
            plan = build_plan(workspace, persist=False)
            health = workspace_health(child)
            readiness = _stage_readiness(workspace, plan, health)
            experience = _experience_state(workspace, plan, health, readiness)
            progress = _progress_summary(workspace, plan)
            next_steps = build_next_steps(workspace, plan, health)
            projects.append(
                {
                    "path": str(child),
                    "name": child.name,
                    "title": workspace.project.get("title") or child.name,
                    "stage": workspace.current_stage,
                    "stage_title": stage_title(workspace.current_stage),
                    "health": health,
                    "progress": progress,
                    "experience": experience,
                    "next_step": next_steps[0] if next_steps else None,
                }
            )
        except Exception as exc:  # pragma: no cover - damaged projects should still be listed
            projects.append(
                {
                    "path": str(child),
                    "name": child.name,
                    "title": child.name,
                    "stage": "unknown",
                    "stage_title": "无法读取",
                    "health": {"level": "fail", "state": "needs_repair", "summary": f"项目读取失败：{exc}", "errors": [str(exc)], "warnings": []},
                    "progress": {"pct": 0, "label": "无法读取"},
                    "experience": {"mode": "repair", "label": "需要修复", "summary": "这个项目当前无法读取。"},
                    "next_step": None,
                }
            )
    severity_rank = {"needs_repair": 0, "needs_attention": 1, "needs_decision": 2, "active": 3, "healthy": 4}
    projects.sort(key=lambda item: (severity_rank.get(item.get("health", {}).get("state"), 5), -item.get("progress", {}).get("pct", 0), item["title"]))
    return projects



def _recent_sort_key(item: dict[str, Any], *fields: str) -> tuple[int, float]:
    for field in fields:
        value = parse_iso(item.get(field))
        if value is not None:
            return (1, value.timestamp())
    return (0, 0.0)



def translate_validation_issue(issue: str, severity: str = "error") -> dict[str, str]:
    level = severity
    raw = issue.strip()
    if raw.startswith("Missing directory:"):
        rel = raw.split(":", 1)[1].strip()
        return {
            "level": level,
            "title": f"项目目录不完整：缺少 {rel}/",
            "detail": "这通常表示你传入的不是项目根目录，或者项目文件被删掉了。",
            "fix": "请确认你传入的是项目最外层目录；如果这是新项目，重新运行 ros init。",
            "raw": raw,
        }
    if raw.startswith("Missing state file:"):
        rel = raw.split(":", 1)[1].strip()
        return {
            "level": level,
            "title": f"项目缺少关键状态文件：{rel}",
            "detail": "系统需要这些文件来保存项目进度。",
            "fix": "若项目刚创建失败，请重新运行 ros init；若是旧项目，请恢复文件或先升级。",
            "raw": raw,
        }
    if raw.startswith("Unknown current_stage:"):
        return {
            "level": level,
            "title": "项目阶段信息无法识别",
            "detail": "state/stage_state.json 里的 current_stage 不是系统认识的值。",
            "fix": "先用 ros demo 验证安装正常，再检查或恢复该项目的 stage_state.json。",
            "raw": raw,
        }
    if "depends on unknown task" in raw:
        return {
            "level": level,
            "title": "待办清单里有断开的依赖关系",
            "detail": "某个任务引用了不存在的前置任务。",
            "fix": "检查 state/task_graph.json，或从最近的正确版本恢复。",
            "raw": raw,
        }
    if "depends_on_runs unknown run_id" in raw:
        return {
            "level": level,
            "title": "有任务依赖了不存在的实验",
            "detail": "至少一个 run 依赖了并不存在的另一个 run。",
            "fix": "先确认相关 run 是否真的创建过，必要时删除错误依赖后重试。",
            "raw": raw,
        }
    if raw.startswith("Run missing manifest.json"):
        run_id = raw.split(":", 1)[1].strip()
        return {
            "level": level,
            "title": f"实验 {run_id} 缺少说明文件",
            "detail": "run 目录存在，但缺少 manifest.json。",
            "fix": "如果这个 run 不再需要，可以移除目录；否则从备份恢复。",
            "raw": raw,
        }
    if raw.startswith("Run missing request.json"):
        run_id = raw.split(":", 1)[1].strip()
        return {
            "level": level,
            "title": f"实验 {run_id} 缺少请求文件",
            "detail": "系统无法知道这个实验当时是如何配置的。",
            "fix": "恢复 runs/<run_id>/request.json，或重新创建该实验。",
            "raw": raw,
        }
    if "Legacy state/run_queue.json still exists" in raw:
        return {
            "level": level,
            "title": "项目里还保留了旧版队列文件",
            "detail": "这不会立刻阻止使用，但说明项目可能来自旧版本。",
            "fix": "建议先运行 ros doctor 和 ros ui 检查项目，再决定是否迁移。",
            "raw": raw,
        }
    if "references missing" in raw:
        return {
            "level": level,
            "title": "项目里有跨文件引用失效",
            "detail": "某条 claim、result、evidence 或 run 指向了不存在的对象。",
            "fix": "打开可视化界面查看具体项，或恢复最近一次完整状态。",
            "raw": raw,
        }
    if "queued even though approval is not cleared" in raw:
        return {
            "level": level,
            "title": "有任务未经批准就进入了队列",
            "detail": "系统发现审批状态和执行状态不一致。",
            "fix": "先在 ros ui 或 ros approve 中处理审批，再重新排队。",
            "raw": raw,
        }
    if "There are requested gates pending approval." in raw:
        return {
            "level": level,
            "title": "项目正在等待你的人工确认",
            "detail": "这不是系统损坏，而是某个关键节点需要你点击批准后才能继续。",
            "fix": "运行 ros approve <项目路径>，或在 ros ui 里点“批准下一项”。",
            "raw": raw,
            "category": "decision",
            "health_impact": "neutral",
        }
    if "Runtime backlog is non-empty" in raw:
        return {
            "level": level,
            "title": "还有任务没有处理完",
            "detail": "队列里仍有等待开始、执行中、可重试或被阻塞的任务。",
            "fix": "先打开 ros ui 查看阻塞项；如果只是想继续推进，可以再运行 ros run <项目路径>。",
            "raw": raw,
            "category": "activity",
            "health_impact": "neutral",
        }
    if "Scheduler has dispatchable runs" in raw:
        return {
            "level": level,
            "title": "系统判断有任务可以开始，但当前没有自动推进",
            "detail": "这通常表示项目里存在可运行任务，但这一步没有被优先执行。",
            "fix": "重新执行 ros run <项目路径>；如果仍重复出现，再打开 ros ui 查看待办和审批项。",
            "raw": raw,
            "category": "activity",
            "health_impact": "neutral",
        }
    return {
        "level": level,
        "title": raw,
        "detail": "这是系统给出的技术检查信息。",
        "fix": "可以先打开 ros ui 查看项目总览，或运行 ros demo 验证环境本身是否健康。",
        "raw": raw,
        "category": "issue",
        "health_impact": "warn",
    }



def workspace_health(project_dir: str | Path) -> dict[str, Any]:
    errors, warnings = validate_workspace(project_dir)
    translated_errors = [translate_validation_issue(item, "error") for item in errors]
    translated_warnings = [translate_validation_issue(item, "warning") for item in warnings]
    translated = translated_errors + translated_warnings

    visible_warnings = [item for item in translated_warnings if item.get("health_impact") != "neutral"]
    neutral_notices = [item for item in translated_warnings if item.get("health_impact") == "neutral"]

    if errors:
        return {
            "level": "fail",
            "summary": f"需要修复 {len(errors)} 个问题",
            "state": "needs_repair",
            "errors": errors,
            "warnings": warnings,
            "translated": translated,
            "issues": translated_errors + visible_warnings,
            "notices": neutral_notices,
        }

    if visible_warnings:
        return {
            "level": "warn",
            "summary": f"有 {len(visible_warnings)} 条提醒",
            "state": "needs_attention",
            "errors": errors,
            "warnings": warnings,
            "translated": translated,
            "issues": visible_warnings,
            "notices": neutral_notices,
        }

    if any(item.get("category") == "decision" for item in neutral_notices):
        return {
            "level": "pass",
            "summary": "等待你的确认",
            "state": "needs_decision",
            "errors": errors,
            "warnings": warnings,
            "translated": translated,
            "issues": [],
            "notices": neutral_notices,
        }

    if any(item.get("category") == "activity" for item in neutral_notices):
        return {
            "level": "pass",
            "summary": "系统仍在处理现有任务",
            "state": "active",
            "errors": errors,
            "warnings": warnings,
            "translated": translated,
            "issues": [],
            "notices": neutral_notices,
        }

    return {
        "level": "pass",
        "summary": "项目状态健康",
        "state": "healthy",
        "errors": [],
        "warnings": [],
        "translated": [],
        "issues": [],
        "notices": [],
    }



def _strip_markdown_preview(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        while line.startswith("#"):
            line = line[1:].strip()
        line = line.lstrip("-*•0123456789.[]() ").strip()
        if line:
            lines.append(line)
    return " ".join(lines)



def _is_placeholder_note(text: str) -> bool:
    cleaned = _strip_markdown_preview(text).lower().strip()
    if not cleaned:
        return True
    placeholder_tokens = ["replace-me", "todo", "tbd", "coming soon"]
    if any(token in cleaned for token in placeholder_tokens):
        return True
    if cleaned in {"scan notes", "novelty audit", "results synthesis", "title + abstract", "outline"}:
        return True
    return False



def _first_heading(text: str, fallback: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
    return fallback



def _planner_blocker_text(item: str) -> str:
    raw = item.strip()
    if raw.startswith("Pending human gate:"):
        gate_id = raw.split(":", 1)[1].strip()
        return f"等待你确认：{gate_title(gate_id)}"

    replacements = {
        "evidence_registry 至少 3 条": "至少补齐 3 条证据，让系统能判断方向是否站得住。",
        "baseline_registry 至少 3 条": "至少补齐 3 个 baseline，方便判断你的方案是不是有区分度。",
        "novelty_audit 非占位": "把创新点与风险判断写到 novelty_audit 里，避免方向还没想清就继续。",
        "claims 至少 1 条": "至少明确 1 条核心主张，让项目有可验证的目标。",
        "每个活跃 claim 都有 evidence_refs 与 acceptance_checks": "给每条活跃主张补齐证据引用和验收条件。",
        "mvp_name 非占位": "先把 MVP 定下来，后面的执行与写作才不会发散。",
        "至少 1 个 run manifest": "先创建第一条任务记录，让执行阶段真正开始。",
        "results_registry 至少 1 条": "至少注册 1 条结果，系统才知道项目不是空转。",
        "无 queued/leased/running/retryable backlog，且成功 run evaluator 为绿": "先把还没收敛的任务处理完，并确保检查通过。",
        "title_abstract 和 outline 非占位且以结果为依据": "先把摘要和正文骨架写成有结果支撑的版本。",
        "artifact_registry 中无 missing 条目": "把输出文件与复现清单补齐到 ready。",
        "没有 run evaluation failure": "先把失败的结果检查修好，再进入发布前收尾。",
    }
    return replacements.get(raw, raw)



def _stage_journey(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    stage_status = workspace.stage_state.get("stage_status", {})
    for stage in STAGE_SEQUENCE:
        status = stage_status.get(stage, "blocked")
        if stage == workspace.current_stage and status != "done":
            status = "active"
        items.append(
            {
                "stage": stage,
                "title": stage_title(stage),
                "description": stage_description(stage),
                "status": status,
                "status_title": STAGE_STATUS_LABELS.get(status, status),
                "is_current": stage == workspace.current_stage,
                "is_done": status == "done",
            }
        )
    return items



def _progress_summary(workspace: WorkspaceSnapshot, plan: dict[str, Any]) -> dict[str, Any]:
    totals = {stage: 0 for stage in STAGE_SEQUENCE}
    done = {stage: 0 for stage in STAGE_SEQUENCE}
    for task in workspace.task_graph.get("tasks", []):
        stage = task.get("stage")
        if stage not in totals:
            continue
        totals[stage] += 1
        if task.get("status") == "done":
            done[stage] += 1

    completed_stages = sum(1 for stage in STAGE_SEQUENCE if workspace.stage_state.get("stage_status", {}).get(stage) == "done")
    pct = completed_stages * 20
    current = workspace.current_stage
    current_total = totals.get(current, 0)
    current_done = done.get(current, 0)
    if current == "audit" and plan.get("advance_ready"):
        pct = 100
    elif current_total:
        pct += round(20 * (current_done / current_total))
    elif plan.get("advance_ready"):
        pct += 20
    elif plan["metrics"]["session_count"] == 0 and plan["metrics"]["run_count"] == 0:
        pct += 4
    else:
        pct += 8
    pct = max(0, min(100, pct))

    if pct >= 95:
        label = "接近可交付"
    elif pct >= 75:
        label = "已经跑通主链路"
    elif pct >= 45:
        label = "已经进入执行主段"
    elif pct >= 20:
        label = "基础方案已成形"
    else:
        label = "刚开始搭建"

    return {
        "pct": pct,
        "label": label,
        "completed_tasks": sum(done.values()),
        "total_tasks": sum(totals.values()),
        "current_stage_done": current_done,
        "current_stage_total": current_total,
    }



def _stage_readiness(workspace: WorkspaceSnapshot, plan: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    pending = _pending_confirmations(workspace, plan)
    blockers = [_planner_blocker_text(item) for item in plan.get("blocking", []) if item]
    scheduler_summary = plan.get("scheduler", {}).get("summary", {})

    if health["level"] == "fail":
        return {
            "state": "needs_repair",
            "title": "先修项目结构",
            "message": "当前问题不是流程卡住，而是项目本身有缺失或损坏。先修好，再继续推进会更安全。",
            "items": [item.get("title", "未命名问题") for item in health.get("issues", [])[:4]],
        }

    if pending:
        return {
            "state": "needs_decision",
            "title": "机器侧已经准备好，只差你确认",
            "message": "这不是报错。系统已经把当前阶段能自动完成的部分做完了，现在需要你点头后继续。",
            "items": [item["title"] for item in pending[:4]],
        }

    if plan.get("advance_ready"):
        next_stage = plan.get("proposed_stage")
        title = "当前阶段已经达标"
        if next_stage:
            message = f"继续推进时，系统会尝试进入“{stage_title(next_stage)}”。"
        else:
            message = "当前阶段已经完成收尾条件，现在更适合做审计、导出或对外交付。"
        return {"state": "ready", "title": title, "message": message, "items": []}

    if blockers:
        return {
            "state": "blocked",
            "title": "距离下一阶段还差这些",
            "message": "你不需要先理解底层 runtime。先把下面几项补齐，系统就会更自然地继续往前走。",
            "items": blockers[:4],
        }

    if scheduler_summary.get("dispatchable_runs", 0) > 0 or plan["metrics"]["queued_or_running_runs"] > 0:
        return {
            "state": "active",
            "title": "系统里还有任务正在流转",
            "message": "如果你想继续看进展，可以再推进一步；如果你在等本地执行器，也可以稍后回来刷新。",
            "items": [],
        }

    return {
        "state": "in_progress",
        "title": "当前阶段还在推进中",
        "message": "系统会继续根据当前阶段决定下一步；你只要优先处理推荐动作即可。",
        "items": [],
    }



def _experience_state(workspace: WorkspaceSnapshot, plan: dict[str, Any], health: dict[str, Any], readiness: dict[str, Any]) -> dict[str, str]:
    metrics = plan["metrics"]
    if health["level"] == "fail":
        return {"mode": "repair", "label": "先修再继续", "summary": "项目本身需要修复，暂时不建议继续推进。"}
    if readiness["state"] == "needs_decision":
        return {"mode": "decision", "label": "等待你确认", "summary": "自动步骤已完成，接下来是人工确认。"}
    if metrics["session_count"] == 0 and metrics["run_count"] == 0:
        return {"mode": "new", "label": "刚开始", "summary": "这是一个刚创建的项目，最适合先推进第一步。"}
    if readiness["state"] == "ready" and workspace.current_stage == "audit":
        return {"mode": "ready", "label": "可以收尾", "summary": "核心链路已经跑通，剩下的是审计与交付动作。"}
    if health.get("state") == "active" or metrics["queued_or_running_runs"] > 0:
        return {"mode": "active", "label": "系统正在推进", "summary": "项目里还有任务在流转，适合查看最新进展。"}
    if metrics["run_count"] > 0:
        return {"mode": "active", "label": "已有结果积累", "summary": "项目已经不再是空白，可以转向看结果、检查和输出。"}
    return {"mode": "steady", "label": "继续推进", "summary": "主路径已经建立，跟着推荐动作即可。"}



def _note_previews(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    note_files = list(workspace.notes_dir.glob("*.md")) if workspace.notes_dir.exists() else []
    ordered_names = NOTE_PRIORITY + [path.name for path in sorted(note_files) if path.name not in NOTE_PRIORITY]
    seen: set[str] = set()
    for name in ordered_names:
        if name in seen:
            continue
        seen.add(name)
        path = workspace.notes_dir / name
        if not path.exists() or not path.is_file():
            continue
        text = read_text(path, "")
        placeholder = _is_placeholder_note(text)
        label = NOTE_LABELS.get(name, _first_heading(text, name.replace("_", " ").replace(".md", "").title()))
        preview = _strip_markdown_preview(text)
        if placeholder:
            preview = "系统后续会把这一部分写成更可读的内容；现在还处于占位或待补全状态。"
        elif len(preview) > 220:
            preview = preview[:217].rstrip() + "..."
        items.append(
            {
                "name": name,
                "label": label,
                "path": f"notes/{name}",
                "placeholder": placeholder,
                "status": "待补充" if placeholder else "已有内容",
                "preview": preview,
            }
        )
    return items[:8]



def _recent_milestones(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for session in workspace.session_registry.get("sessions", []):
        items.append(
            {
                "kind": "session",
                "id": session.get("session_id"),
                "at": session.get("ended_at") or session.get("started_at"),
                "title": "系统推进了一步",
                "detail": f"{stage_title(session.get('current_stage') or workspace.current_stage)} · {session.get('agent') or 'controller'} / {session.get('profile') or '-'} · {session.get('status') or '-'}",
            }
        )

    for run in workspace.run_registry.get("runs", []):
        items.append(
            {
                "kind": "run",
                "id": run.get("run_id"),
                "at": run.get("ended_at") or run.get("started_at") or run.get("queued_at") or run.get("created_at"),
                "title": f"任务 {run.get('run_id')} {run_status_title(run.get('status'))}",
                "detail": f"结果检查：{eval_status_title(run.get('evaluation_status'))}",
            }
        )

    for evaluation in workspace.evaluation_registry.get("evaluations", []):
        fallback_target = f"{evaluation.get('target_type')}:{evaluation.get('target_id')}"
        items.append(
            {
                "kind": "evaluation",
                "id": evaluation.get("evaluation_id"),
                "target": evaluation.get("target_id"),
                "at": evaluation.get("created_at"),
                "title": f"结果检查：{eval_status_title(evaluation.get('status'))}",
                "detail": f"{evaluation.get('evaluator')} · {evaluation.get('summary') or fallback_target}",
            }
        )

    for artifact in workspace.artifact_registry.get("items", []):
        items.append(
            {
                "kind": "artifact",
                "id": artifact.get("name"),
                "at": artifact.get("updated_at"),
                "title": f"输出文件 {artifact.get('name')}：{artifact.get('status', 'ready')}",
                "detail": artifact.get("notes") or artifact.get("owner") or "",
            }
        )

    for gate in workspace.stage_state.get("gates", []):
        if gate.get("approved_at"):
            items.append(
                {
                    "kind": "gate",
                    "id": gate.get("gate_id"),
                    "at": gate.get("approved_at"),
                    "title": f"人工确认已通过：{gate_title(gate.get('gate_id', ''), gate.get('title'))}",
                    "detail": gate.get("approved_note") or gate.get("approved_by") or "",
                }
            )

    items.sort(key=lambda item: _recent_sort_key(item, "at"), reverse=True)
    return items[:10]



def _project_story(workspace: WorkspaceSnapshot, plan: dict[str, Any]) -> str:
    metrics = plan["metrics"]
    stage = workspace.current_stage
    if metrics["session_count"] == 0 and metrics["run_count"] == 0 and metrics["evidence_items"] == 0:
        return "这是一个刚创建的空项目。你还没有运行过任何自动步骤，最轻松的开始方式是先让系统推进一步。"
    if stage == "scan":
        return "项目还在文献与证据阶段。现在最重要的是补齐 evidence、相关工作和方向风险。"
    if stage == "design":
        return "项目已经有基础材料，正在把主张、验收条件和 MVP 变成结构化研究设计。"
    if stage == "execute":
        return "项目已经进入实验执行阶段。现在要么在等待结果，要么需要处理待批准或待重试的任务。"
    if stage == "write":
        return "项目已经有结果，当前重点是把通过检查的结果写成 research brief、摘要和结构。"
    if stage == "audit":
        return "项目已接近交付，当前重点是补齐输出文件并确认所有关键审计检查通过。"
    return "这是一个 Research OS 专业科研助手工作区，用来逐步推进研究项目。"



def _open_tasks_for_users(plan: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for task in plan.get("open_tasks", [])[:5]:
        items.append(
            {
                "task_id": task.get("task_id", ""),
                "title": task.get("title", "未命名任务"),
                "stage": stage_title(task.get("stage", "")),
                "status": task.get("status", "todo"),
                "acceptance": task.get("acceptance_notes", ""),
            }
        )
    return items



def _pending_confirmations(workspace: WorkspaceSnapshot, plan: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    requested_gate_ids = {item.get("gate_id") for item in plan.get("requested_gates", [])}
    pending_stage_gate_ids = set(plan.get("stage_exit", {}).get("pending_gates", [])) if plan.get("stage_exit", {}).get("gate_needed") else set()
    for gate in workspace.stage_state.get("gates", []):
        gate_id = gate.get("gate_id")
        status = gate.get("status", "pending")
        if gate_id in requested_gate_ids or (status in {"requested", "pending"} and gate_id in pending_stage_gate_ids):
            items.append(
                {
                    "kind": "gate",
                    "id": gate_id,
                    "title": gate_title(gate_id, gate.get("title")),
                    "status": "等待人工确认" if status in {"requested", "pending"} else status,
                    "reason": gate.get("last_reason") or "系统已准备好进入下一步，需要你确认。",
                }
            )
    for run in workspace.run_registry.get("runs", []):
        approval = run.get("approval", {})
        if approval.get("status") in {"pending", "requested", "rejected"}:
            items.append(
                {
                    "kind": "run",
                    "id": run.get("run_id"),
                    "title": f"批准任务 {run.get('run_id')}",
                    "status": "等待任务批准",
                    "reason": approval.get("reason") or "这个任务需要人工确认后才能继续。",
                }
            )
    return items



def _attention_items(workspace: WorkspaceSnapshot, plan: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    pending = _pending_confirmations(workspace, plan)
    items.extend(pending)
    for run in workspace.run_registry.get("runs", []):
        status = run.get("status")
        if status not in {"blocked", "retryable", "failed"}:
            continue
        reason = run.get("blocked_reason") or run.get("last_error") or "需要你处理"
        items.append(
            {
                "kind": "run_state",
                "id": run.get("run_id"),
                "title": f"任务 {run.get('run_id')}：{run_status_title(status)}",
                "status": run_status_title(status),
                "reason": reason,
            }
        )
    return items[:8]



def build_next_steps(workspace: WorkspaceSnapshot, plan: dict[str, Any], health: dict[str, Any]) -> list[dict[str, str]]:
    project_dir = str(workspace.root)
    steps: list[dict[str, str]] = []
    metrics = plan["metrics"]
    current_stage = workspace.current_stage
    pending = _pending_confirmations(workspace, plan)
    scheduler_summary = plan.get("scheduler", {}).get("summary", {})

    if health["level"] == "fail":
        steps.append(
            {
                "title": "先修复项目问题",
                "why": "系统发现这个项目有损坏或缺失文件，继续推进前应先修好。",
                "command": f'ros doctor "{project_dir}"',
                "action": "doctor",
            }
        )

    if pending:
        first = pending[0]
        if first["kind"] == "gate":
            steps.append(
                {
                    "title": f"批准“{first['title']}”",
                    "why": first["reason"],
                    "command": f'ros approve "{project_dir}" --gate {first["id"]}',
                    "action": "approve_gate",
                }
            )
        else:
            steps.append(
                {
                    "title": f"批准任务 {first['id']}",
                    "why": first["reason"],
                    "command": f'ros approve "{project_dir}" --run {first["id"]}',
                    "action": "approve_run",
                }
            )

    if metrics["session_count"] == 0 and metrics["run_count"] == 0:
        steps.append(
            {
                "title": "先让系统推进第一步",
                "why": "这是最短的体验路径：系统会自动补齐最基础的待办和项目内容。",
                "command": f'ros run "{project_dir}"',
                "action": "run",
            }
        )
    elif scheduler_summary.get("dispatchable_runs", 0) > 0 or metrics["queued_or_running_runs"] > 0 or metrics["blocked_runs"] > 0:
        steps.append(
            {
                "title": "继续推进当前任务",
                "why": "项目里已经有待执行或正在等待处理的任务。",
                "command": f'ros run "{project_dir}"',
                "action": "run",
            }
        )
    elif plan.get("advance_ready"):
        next_stage = plan.get("proposed_stage")
        title = f"进入下一阶段：{stage_title(next_stage)}" if next_stage else "完成收尾检查"
        steps.append(
            {
                "title": title,
                "why": f"当前阶段“{stage_title(current_stage)}”已经满足推进条件。",
                "command": f'ros run "{project_dir}"',
                "action": "run",
            }
        )
    else:
        steps.append(
            {
                "title": "继续推进一小步",
                "why": "系统会根据当前阶段自动决定下一位 agent 和动作。",
                "command": f'ros run "{project_dir}"',
                "action": "run",
            }
        )

    if metrics["evaluation_failures"] > 0:
        steps.append(
            {
                "title": "查看失败检查并修复",
                "why": "至少有一个结果检查没有通过，先修这个再写结论会更稳。",
                "command": f'ros ui "{project_dir}"',
                "action": "ui",
            }
        )

    steps.append(
        {
            "title": "打开可视化工作台",
            "why": "浏览器界面更适合看总体状态、待处理事项和最近结果。",
            "command": f'ros ui "{project_dir}"',
            "action": "ui",
        }
    )
    steps.append(
        {
            "title": "做一次健康检查",
            "why": "当你不确定项目为什么卡住时，这个命令最直接。",
            "command": f'ros doctor "{project_dir}"',
            "action": "doctor",
        }
    )

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in steps:
        key = item["command"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:4]



def _recent_runs(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    runs = list(workspace.run_registry.get("runs", []))
    runs.sort(key=lambda item: _recent_sort_key(item, "ended_at", "started_at", "queued_at", "created_at"), reverse=True)
    items: list[dict[str, Any]] = []
    for run in runs[:6]:
        items.append(
            {
                "run_id": run.get("run_id"),
                "status": run_status_title(run.get("status")),
                "status_raw": run.get("status"),
                "evaluation": eval_status_title(run.get("evaluation_status")),
                "priority": run.get("priority", "normal"),
                "ended_at": run.get("ended_at") or run.get("started_at") or run.get("queued_at") or run.get("created_at"),
                "needs_attention": run.get("status") in {"blocked", "retryable", "failed"} or run.get("evaluation_status") == "fail",
            }
        )
    return items



def _recent_evaluations(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    evaluations = list(workspace.evaluation_registry.get("evaluations", []))
    evaluations.sort(key=lambda item: _recent_sort_key(item, "created_at"), reverse=True)
    items: list[dict[str, Any]] = []
    for item in evaluations[:6]:
        items.append(
            {
                "evaluation_id": item.get("evaluation_id"),
                "target": f"{item.get('target_type')}:{item.get('target_id')}",
                "evaluator": item.get("evaluator"),
                "status": eval_status_title(item.get("status")),
                "status_raw": item.get("status"),
                "summary": item.get("summary", ""),
                "created_at": item.get("created_at"),
            }
        )
    return items



def _recent_artifacts(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    items = list(workspace.artifact_registry.get("items", []))
    items.sort(key=lambda item: _recent_sort_key(item, "updated_at"), reverse=True)
    payload: list[dict[str, Any]] = []
    for item in items[:6]:
        payload.append(
            {
                "name": item.get("name"),
                "status": item.get("status", "ready"),
                "owner": item.get("owner"),
                "updated_at": item.get("updated_at"),
                "notes": item.get("notes", ""),
            }
        )
    return payload



def _recent_sessions(workspace: WorkspaceSnapshot) -> list[dict[str, Any]]:
    sessions = list(workspace.session_registry.get("sessions", []))
    sessions.sort(key=lambda item: _recent_sort_key(item, "ended_at", "started_at"), reverse=True)
    payload: list[dict[str, Any]] = []
    for item in sessions[:6]:
        payload.append(
            {
                "session_id": item.get("session_id"),
                "agent": item.get("agent"),
                "profile": item.get("profile"),
                "status": item.get("status"),
                "started_at": item.get("started_at"),
                "ended_at": item.get("ended_at"),
            }
        )
    return payload



def _metric_items(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for key, value in (metrics or {}).items():
        payload.append({"key": key, "value": value})
    return payload



def project_run_details(project_dir: str | Path, run_id: str) -> dict[str, Any] | None:
    workspace = WorkspaceSnapshot.load(project_dir)
    run = workspace.get_run(run_id)
    if run is None:
        return None
    manifest = workspace.load_run_manifest(run_id)
    request = workspace.load_run_request(run_id)
    metrics_blob = workspace.load_run_metrics(run_id)
    output_manifest = workspace.load_run_output_manifest(run_id)
    evaluations = workspace.evaluations_for_target("run", run_id)
    results = [item for item in workspace.results_registry.get("results", []) if item.get("run_id") == run_id]
    related_claims = [item for item in workspace.claims.get("claims", []) if item.get("claim_id") in {result.get("claim_id") for result in results if result.get("claim_id")}]

    return {
        "run": run,
        "manifest": manifest,
        "request": request,
        "metrics": _metric_items(metrics_blob.get("metrics", {})),
        "output_manifest": output_manifest,
        "evaluations": evaluations,
        "results": results,
        "claims": related_claims,
        "summary": {
            "title": manifest.get("question") or manifest.get("run_name") or run_id,
            "status": run_status_title(run.get("status")),
            "evaluation": eval_status_title(run.get("evaluation_status")),
            "needs_attention": run.get("status") in {"blocked", "retryable", "failed"} or run.get("evaluation_status") == "fail",
            "can_approve": run.get("approval", {}).get("status") in {"pending", "requested", "rejected"},
            "can_retry": run.get("status") in {"failed", "blocked", "retryable", "cancelled"},
            "can_cancel": run.get("status") in {"planned", "queued", "leased", "running", "retryable", "blocked"},
        },
    }



def project_task_details(project_dir: str | Path, task_id: str) -> dict[str, Any] | None:
    workspace = WorkspaceSnapshot.load(project_dir)
    tasks = workspace.task_graph.get("tasks", [])
    task = next((item for item in tasks if item.get("task_id") == task_id), None)
    if task is None:
        return None
    dependencies = [item for item in tasks if item.get("task_id") in set(task.get("depends_on", []))]
    downstream = [item for item in tasks if task_id in set(item.get("depends_on", []))]
    related_runs = [item for item in workspace.run_registry.get("runs", []) if item.get("task_id") == task_id]
    return {
        "task": task,
        "dependencies": dependencies,
        "downstream": downstream,
        "related_runs": related_runs,
    }



def project_artifact_details(project_dir: str | Path, name: str) -> dict[str, Any] | None:
    workspace = WorkspaceSnapshot.load(project_dir)
    artifact = next((item for item in workspace.artifact_registry.get("items", []) if item.get("name") == name), None)
    if artifact is None:
        return None
    resolved_path = None
    if artifact.get("path"):
        resolved_path = workspace.root / artifact.get("path")
    related_run = workspace.get_run(artifact.get("run_id")) if artifact.get("run_id") else None
    return {
        "artifact": artifact,
        "resolved_path": str(resolved_path) if resolved_path else None,
        "exists_on_disk": bool(resolved_path and resolved_path.exists()),
        "related_run": related_run,
    }



def project_session_details(project_dir: str | Path, session_id: str) -> dict[str, Any] | None:
    workspace = WorkspaceSnapshot.load(project_dir)
    session = next((item for item in workspace.session_registry.get("sessions", []) if item.get("session_id") == session_id), None)
    if session is None:
        return None
    return {"session": session}



def project_note_details(project_dir: str | Path, name: str) -> dict[str, Any] | None:
    workspace = WorkspaceSnapshot.load(project_dir)
    path = workspace.notes_dir / name
    if not path.exists() or not path.is_file():
        return None
    text = read_text(path, "")
    return {
        "name": name,
        "label": NOTE_LABELS.get(name, _first_heading(text, name.replace("_", " ").replace(".md", "").title())),
        "path": f"notes/{name}",
        "content": text,
        "placeholder": _is_placeholder_note(text),
    }



def project_dashboard(project_dir: str | Path) -> dict[str, Any]:
    workspace = WorkspaceSnapshot.load(project_dir)
    plan = build_plan(workspace, persist=False)
    health = workspace_health(project_dir)
    metrics = plan["metrics"]
    current_stage = workspace.current_stage
    readiness = _stage_readiness(workspace, plan, health)
    experience = _experience_state(workspace, plan, health, readiness)
    progress = _progress_summary(workspace, plan)
    next_steps = build_next_steps(workspace, plan, health)

    return {
        "path": str(Path(project_dir).resolve()),
        "project": {
            "title": workspace.project.get("title"),
            "slug": workspace.project.get("project_slug"),
            "owner": workspace.project.get("owner"),
            "venue": workspace.project.get("target_venue"),
            "goal": workspace.project.get("current_goal"),
            "version": workspace.project.get("version"),
        },
        "story": _project_story(workspace, plan),
        "health": health,
        "experience": experience,
        "progress": progress,
        "stage": {
            "raw": current_stage,
            "title": stage_title(current_stage),
            "description": stage_description(current_stage),
            "goal": stage_goal(current_stage),
            "advance_ready": bool(plan.get("advance_ready")),
            "next_stage": plan.get("proposed_stage"),
        },
        "stage_journey": _stage_journey(workspace),
        "stage_readiness": readiness,
        "stats": {
            "evidence": metrics["evidence_items"],
            "baselines": metrics["baseline_items"],
            "claims": metrics["claim_count"],
            "runs": metrics["run_count"],
            "results": metrics["result_count"],
            "artifacts": metrics["artifact_items"],
            "sessions": metrics["session_count"],
            "pending_approvals": metrics["pending_run_approvals"],
            "checks_failed": metrics["evaluation_failures"],
        },
        "tasks": _open_tasks_for_users(plan),
        "attention": _attention_items(workspace, plan),
        "next_steps": next_steps,
        "recent_runs": _recent_runs(workspace),
        "recent_evaluations": _recent_evaluations(workspace),
        "recent_artifacts": _recent_artifacts(workspace),
        "recent_sessions": _recent_sessions(workspace),
        "recent_milestones": _recent_milestones(workspace),
        "notes": _note_previews(workspace),
        "recommendations": plan.get("recommendations", []),
        "terms": TERM_MAP,
        "raw_plan": plan,
    }



def _format_status_line(level: str, text: str) -> str:
    symbol = {"pass": "[通过]", "warn": "[提醒]", "fail": "[失败]"}.get(level, "[信息]")
    return f"{symbol} {text}"



def render_home_text(root: str | Path = "projects") -> str:
    projects = list_projects(root)
    lines = [
        f"{APP_NAME} {APP_VERSION}",
        "",
        "这是一个面向专业研究工作的 AI 科研助手。",
        "它会帮你整理 evidence、推进 claim / MVP / run，并把结果导出成面向协作的研究成果物。",
        "",
        "第一次最短路径：",
        "  1. ros quickstart            # 一键准备一个可玩的演示项目",
        "  2. ros ui                   # 打开浏览器工作台",
        "  3. ros run <项目路径>        # 让系统继续推进一步",
        "  4. ros approve <项目路径>    # 如果系统在等你确认，就用它继续",
        "  5. ros doctor <项目路径>     # 看为什么卡住、怎么修",
        "",
        "打开 UI 之后，优先看这 4 块：",
        "  - 总览：系统现在如何理解这个项目",
        "  - 你现在最适合做什么：下一步推荐动作",
        "  - 距离下一阶段还差什么：别再自己猜流程",
        "  - 最近进展：最近一次推进、任务、检查和输出",
        "",
        "常用命令：",
        "  ros init                    # 创建一个新的空项目",
        "  ros demo                    # 复制一个内置演示项目",
        "  ros approve <项目路径>      # 批准待确认事项",
        "  ros audit <项目路径>        # 生成审计报告",
        "  ros showcase <项目路径>     # 导出 research brief / evidence matrix / deliverable index",
        "",
    ]
    if projects:
        lines.append("已发现的项目：")
        for item in projects:
            health = item["health"]["summary"]
            next_step = item.get("next_step")
            next_text = next_step["title"] if next_step else "打开查看"
            progress = item.get("progress", {}).get("pct", 0)
            experience = item.get("experience", {}).get("label", item["stage_title"])
            lines.append(f"  - {item['title']}  [{item['stage_title']} / {experience} / {progress}%]  {health}  → {next_text}")
    else:
        lines.append("当前还没有检测到项目。你可以先运行 ros quickstart 或 ros init。")
    lines.append("")
    lines.append("高级命令仍然保留，比如 plan / scheduler / orchestrate / create-run，但它们不再是新手主入口。")
    return "\n".join(lines)



def render_project_text(dashboard: dict[str, Any]) -> str:
    project = dashboard["project"]
    stage = dashboard["stage"]
    health = dashboard["health"]
    readiness = dashboard["stage_readiness"]
    progress = dashboard["progress"]
    experience = dashboard["experience"]
    lines = [
        f"项目：{project['title']}",
        f"位置：{dashboard['path']}",
        f"当前阶段：{stage['title']}",
        f"这一阶段的目标：{stage['goal']}",
        f"当前状态：{experience['label']} · {health['summary']}",
        f"整体进度：{progress['pct']}% ({progress['label']})",
        "",
        "现在系统怎么看这个项目：",
        f"  {dashboard['story']}",
        "",
        f"距离下一阶段：{readiness['title']}",
        f"  {readiness['message']}",
    ]
    if readiness["items"]:
        lines.append("  你只需要先处理这几项：")
        for item in readiness["items"][:4]:
            lines.append(f"    - {item}")
    lines.extend(
        [
            "",
        "你现在能做什么：",
        ]
    )
    for item in dashboard["next_steps"]:
        lines.append(f"  - {item['title']} -> {item['command']}")
        lines.append(f"    原因：{item['why']}")
    if dashboard["attention"]:
        lines.extend(["", "当前需要你处理的事项："])
        for item in dashboard["attention"][:5]:
            lines.append(f"  - {item['title']}：{item['reason']}")
    if dashboard["tasks"]:
        lines.extend(["", "当前阶段的待办："])
        for task in dashboard["tasks"][:5]:
            suffix = f"（完成标准：{task['acceptance']}）" if task.get("acceptance") else ""
            lines.append(f"  - {task['title']}{suffix}")
    if dashboard["notes"]:
        lines.extend(["", "最近可读内容："])
        for item in dashboard["notes"][:3]:
            lines.append(f"  - {item['label']}：{item['preview']}")
    if dashboard["recent_milestones"]:
        lines.extend(["", "最近进展："])
        for item in dashboard["recent_milestones"][:4]:
            lines.append(f"  - {item['title']}：{item['detail']}")
    return "\n".join(lines)



def doctor_report(project_dir: str | Path | None = None, root: str | Path = "projects") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    root_path = Path(root).resolve()

    def add(level: str, title: str, detail: str, fix: str = "") -> None:
        checks.append({"level": level, "title": title, "detail": detail, "fix": fix})

    add("pass", "Python 环境可用", f"当前 Python 版本：{platform.python_version()}。")

    package_root = Path(__file__).resolve().parents[1]
    if (package_root / "templates" / "project").exists():
        add("pass", "已找到项目模板", "可以直接创建新项目。")
    else:
        add("fail", "缺少项目模板", "templates/project 不存在。", "请确认你拿到的是完整项目包，而不是只复制了部分文件。")

    if (package_root / "projects" / "sample_joint_tri_runtime_v4_2").exists():
        add("pass", "已找到内置演示项目", "可以直接运行 ros demo 复制一份进行体验。")
    else:
        add("warn", "没有检测到内置演示项目", "你仍然可以创建空项目，但首次体验路径会稍长。", "确认 projects/sample_joint_tri_runtime_v4_2 是否存在。")

    if os.environ.get("OPENAI_API_KEY"):
        add("pass", "已检测到 OPENAI_API_KEY", "如需使用 openai provider，可以直接配置并运行。")
    else:
        add("pass", "当前未设置 OPENAI_API_KEY（可选）", "这不影响使用 mock provider，也不影响 UI、demo 和本地体验。", "只有在你想接入 OpenAI provider 时，才需要设置它。")

    if not root_path.exists():
        add("warn", "项目目录根路径还不存在", f"当前 root={root_path}。", "第一次运行前系统会自动创建它，这不是阻塞问题。")
    else:
        known_projects = list_projects(root_path)
        if known_projects:
            add("pass", "已发现现有项目", f"共发现 {len(known_projects)} 个项目。")
        else:
            add("warn", "还没有检测到项目", "你可以先运行 ros quickstart 或 ros init。", "推荐先运行 ros quickstart，5 分钟内就能完成第一次成功体验。")

    dashboard = None
    if project_dir is not None:
        project_path = Path(project_dir).resolve()
        if not project_path.exists():
            add("fail", "项目路径不存在", f"未找到：{project_path}", "请确认路径正确，或先运行 ros demo / ros init 创建项目。")
        elif not project_exists(project_path):
            add("fail", "这不是一个完整的项目目录", f"目录存在，但缺少 state/project.json：{project_path}", "请传入项目根目录，而不是其中的 notes/、state/ 或 runs/ 子目录。")
        else:
            health = workspace_health(project_path)
            if health["level"] == "pass":
                add("pass", "项目结构健康", "没有发现结构损坏或关键文件缺失。")
            elif health["level"] == "warn":
                add("warn", "项目可以继续使用，但有提醒", health["summary"], "建议先打开 ros ui 查看提醒，再继续推进。")
            else:
                add("fail", "项目需要修复", health["summary"], "请先根据 doctor 提示修复，再继续推进。")
            for item in health.get("translated", []):
                checks.append(item)
            try:
                dashboard = project_dashboard(project_path)
            except Exception as exc:
                add("fail", "项目状态无法读取", str(exc), "先用 ros demo 验证安装正常，再检查这个项目。")

    overall = "pass"
    if any(item["level"] == "fail" for item in checks):
        overall = "fail"
    elif any(item["level"] == "warn" and item.get("health_impact") != "neutral" for item in checks):
        overall = "warn"

    return {"overall": overall, "checks": checks, "dashboard": dashboard, "root": str(root_path), "project_dir": str(project_dir) if project_dir else None}



def render_doctor_text(report: dict[str, Any]) -> str:
    lines = [
        f"健康检查结果：{ {'pass': '通过', 'warn': '有提醒', 'fail': '需要修复'}.get(report['overall'], report['overall']) }",
        "",
    ]
    for item in report["checks"]:
        lines.append(_format_status_line(item["level"], item["title"]))
        if item.get("detail"):
            lines.append(f"  说明：{item['detail']}")
        if item.get("fix"):
            lines.append(f"  建议：{item['fix']}")
    dashboard = report.get("dashboard")
    if dashboard:
        lines.extend(["", "推荐下一步："])
        for step in dashboard["next_steps"][:3]:
            lines.append(f"  - {step['title']} -> {step['command']}")
    return "\n".join(lines)



def summarize_run_result(result: dict[str, Any]) -> dict[str, Any]:
    if "history" in result:
        final_plan = result.get("final_plan", {})
        return {
            "mode": "workloop",
            "steps": len(result.get("history", [])),
            "final_plan": final_plan,
            "session_id": result.get("history", [{}])[-1].get("session_id") if result.get("history") else None,
            "executor_runs": sum(len(item.get("executor_results", [])) for item in result.get("history", [])),
        }
    return {
        "mode": "single",
        "steps": 1,
        "session_id": result.get("session_id"),
        "agent": result.get("agent"),
        "profile": result.get("profile"),
        "changes": len((result.get("apply_result") or {}).get("changes", [])),
        "executor_runs": len(result.get("executor_results", [])),
        "final_plan": result.get("final_plan", {}),
    }



def render_run_text(project_dir: str | Path, result: dict[str, Any]) -> str:
    summary = summarize_run_result(result)
    dashboard = project_dashboard(project_dir)
    final_plan = summary.get("final_plan", {})
    readiness = dashboard["stage_readiness"]
    lines = [
        "已完成本次推进。",
        f"- 模式：{'连续推进' if summary['mode'] == 'workloop' else '单步推进'}",
        f"- 会话：{summary.get('session_id') or '未记录'}",
    ]
    if summary.get("agent"):
        lines.append(f"- 本次执行角色：{summary['agent']} / {summary.get('profile')}")
    if summary.get("changes") is not None:
        lines.append(f"- 产生的状态变更：{summary.get('changes', 0)} 项")
    lines.append(f"- 本次执行了 {summary.get('executor_runs', 0)} 个任务")
    if final_plan:
        lines.append(f"- 当前阶段：{stage_title(final_plan.get('current_stage', ''))}")
    lines.append(f"- 当前项目状态：{dashboard['experience']['label']} · {dashboard['health']['summary']}")
    lines.append(f"- 整体进度：{dashboard['progress']['pct']}% ({dashboard['progress']['label']})")
    lines.append("")
    lines.append(f"为什么现在停在这里：{readiness['title']}")
    lines.append(f"- {readiness['message']}")
    for item in readiness["items"][:3]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("下一步建议：")
    for item in dashboard["next_steps"][:3]:
        lines.append(f"- {item['title']} -> {item['command']}")
    return "\n".join(lines)



def humanize_exception(exc: Exception, command: str | None = None) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lines = ["无法完成这一步。", ""]

    if isinstance(exc, FileExistsError):
        lines.extend(
            [
                "原因：目标目录已经存在。",
                f"详情：{message}",
                "修复：换一个 --name，或者删除同名目录后重试。",
            ]
        )
        return "\n".join(lines)

    if isinstance(exc, FileNotFoundError):
        lines.extend(
            [
                "原因：找不到你指定的文件或目录。",
                f"详情：{message}",
                "修复：确认路径正确；如果你还没有项目，可以先运行 ros quickstart 或 ros init。",
            ]
        )
        return "\n".join(lines)

    if isinstance(exc, PermissionError):
        lines.extend(
            [
                "原因：系统的保护规则拦下了这次操作。",
                f"详情：{message}",
                "修复：先根据报错说明补齐前置条件，再重试；通常是审批、结果检查或受保护状态未满足。",
            ]
        )
        return "\n".join(lines)

    if isinstance(exc, RuntimeError) and "OPENAI_API_KEY" in message:
        lines.extend(
            [
                "原因：你选择了 openai provider，但当前环境没有设置 OPENAI_API_KEY。",
                "修复：先设置环境变量，或者改用默认的 mock provider 继续体验。",
            ]
        )
        return "\n".join(lines)

    if isinstance(exc, ValueError) and "Unknown run_id" in message:
        lines.extend(
            [
                "原因：你指定的任务编号不存在。",
                f"详情：{message}",
                "修复：先运行 ros status <项目路径> 或打开 ros ui 查看当前有哪些任务。",
            ]
        )
        return "\n".join(lines)

    if isinstance(exc, ValueError) and "Unknown" in message and "gate" in message.lower():
        lines.extend(
            [
                "原因：你指定的人工确认项不存在。",
                f"详情：{message}",
                "修复：先运行 ros status <项目路径> 查看当前待确认项。",
            ]
        )
        return "\n".join(lines)

    if command:
        lines.append(f"命令：{command}")
    lines.extend([f"详情：{message}", "修复：先运行 ros doctor 看整体状态，或者打开 ros ui 查看更直观的提示。"])
    return "\n".join(lines)



def pick_pending_approval(workspace: WorkspaceSnapshot) -> dict[str, str] | None:
    plan = build_plan(workspace, persist=False)
    pending = _pending_confirmations(workspace, plan)
    if not pending:
        return None
    first = pending[0]
    return {"kind": first["kind"], "id": first["id"], "title": first["title"]}



def stage_options() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for stage in load_stage_machine().get("stages", []):
        code = stage.get("stage")
        items.append({"stage": code, "title": stage_title(code), "description": stage_description(code)})
    return items
