from __future__ import annotations

import difflib
import mimetypes
import os
import shutil
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .common import ensure_dir, load_json, now_iso, resolve_within_root, save_json, slugify, write_text


MODULE_SPECS: dict[str, dict[str, Any]] = {
    "paper": {
        "code": "A",
        "title": "A线 · 论文",
        "description": "idea → 初稿 → 调研整改 → 严谨稿 → 预投稿级论文。",
        "workspace_root": "paper",
        "library_bucket": "paper",
        "steps": [
            ("idea", "1. 产出 idea", "围绕课题提出多个候选 idea，并筛出最值得推进的一条。"),
            ("draft", "2. 用 idea 产出初稿", "把已选 idea 写成第一版结构化论文初稿。"),
            ("revision", "3. 对初稿继续优化调研分析整改", "继续补调研、审稿人视角检查并整改论文。"),
            ("rigorous", "4. 产出更合理严谨的稿子", "把调研与整改结果回写成更严谨稳定的稿件。"),
            ("presub", "5. 产出带图片占位和实验占位的预投稿级论文", "形成逻辑完整、图位明确、待实验/图片回写的预投稿级主稿。"),
        ],
    },
    "experiments": {
        "code": "B",
        "title": "B线 · 实验",
        "description": "论文 → 代码 → 预跑 → 优化 → 真实实验 → 结果回写。",
        "workspace_root": "experiments",
        "library_bucket": "experiments",
        "steps": [
            ("codegen", "1. 根据论文生成完整代码", "根据论文主稿生成实验代码与目录结构。"),
            ("preflight", "2. 预跑和修补", "让 AI 先做轻量预跑、发现明显问题并修补。"),
            ("optimize", "3. 优化实验", "继续优化代码、配置与实验设计。"),
            ("gap_check", "4. 检测实验和论文是否还有优化空间", "检查实验与论文之间是否还有结构性优化空间。"),
            ("stabilize", "5. 跑通", "把实验持续修到稳定跑通。"),
            ("server_run", "6. 本地服务器真实实验", "在本地服务器执行真实实验并记录日志。"),
            ("writeback", "7. 结果回写论文", "将实验结果汇总并回写论文主稿。"),
        ],
    },
    "figures": {
        "code": "C",
        "title": "C线 · 图片",
        "description": "论文 → 图片提示词 → 原图 → 审图重绘 → PDF。",
        "workspace_root": "figures",
        "library_bucket": "figures",
        "steps": [
            ("prompting", "1. 从论文生成图片提示词", "根据论文需要生成图片制作提示词。"),
            ("raw", "2. 调外部模型产原图", "将提示词与论文交给外部模型生成原图。"),
            ("review", "3. 审图与矢量重绘", "检查原图并重绘为论文可用的矢量图。"),
            ("bundle", "4. 汇总导出 PDF", "整理全部最终图并导出 PDF 汇总包。"),
        ],
    },
    "control": {
        "code": "D",
        "title": "D线 · 总控 / 设置",
        "description": "项目总进度、共享文件库、provider 地址、模板、版本和投稿状态。",
        "workspace_root": "control",
        "library_bucket": "shared",
        "steps": [],
    },
}

LINE_SPECS = MODULE_SPECS
MODULE_ORDER = ["paper", "experiments", "figures", "control"]
LIBRARY_BUCKETS = ["paper", "experiments", "figures", "shared", "handoff_packages"]

STEP_STATUS_META = {
    "todo": ("待开始", "neutral"),
    "active": ("当前步骤", "info"),
    "review": ("等待你审阅", "warn"),
    "blocked": ("被阻塞", "bad"),
    "done": ("已完成", "ok"),
}

TEXT_EXTS = {".md", ".txt", ".tex", ".py", ".json", ".yaml", ".yml", ".csv", ".tsv", ".html", ".xml", ".log", ".sh", ".rst"}

DEFAULT_PROVIDER_PROFILES = [
    {
        "profile_id": "mock-local",
        "name": "本地 Mock",
        "provider": "mock",
        "base_url": "",
        "default_model": "mock",
        "api_key_env": "",
        "notes": "调试 UI 和步骤流程时使用。",
        "is_builtin": True,
    },
    {
        "profile_id": "openai-default",
        "name": "OpenAI 兼容 API",
        "provider": "openai",
        "base_url": "",
        "default_model": "gpt-4.1-mini",
        "api_key_env": "OPENAI_API_KEY",
        "notes": "base_url 留空时使用 OPENAI_API_BASE 或官方默认地址。",
        "is_builtin": True,
    },
    {
        "profile_id": "chatgpt-web",
        "name": "ChatGPT 网页",
        "provider": "manual_web",
        "base_url": "https://chatgpt.com",
        "default_model": "ChatGPT Web",
        "api_key_env": "",
        "notes": "适合手工协同：复制 Prompt、上传文件、回填结果。",
        "is_builtin": True,
    },
    {
        "profile_id": "gemini-web",
        "name": "Gemini 网页",
        "provider": "manual_web",
        "base_url": "https://gemini.google.com",
        "default_model": "Gemini Web",
        "api_key_env": "",
        "notes": "适合手工协同：复制 Prompt、上传文件、回填结果。",
        "is_builtin": True,
    },
    {
        "profile_id": "manual-web",
        "name": "网页手工交接",
        "provider": "manual_web",
        "base_url": "",
        "default_model": "网页 AI",
        "api_key_env": "",
        "notes": "用于生成交接包，发给 GPT Pro / Gemini 网页等。",
        "is_builtin": True,
    },
]

DEFAULT_CONTROL = {
    "program_goal": "围绕一篇论文完成论文、实验、图片与投稿总控四条线。",
    "next_milestone": "锁定论文主线的当前步骤",
    "submission_status": "未开始",
    "open_source_status": "未开始",
    "github_repo": "",
    "manager_notes": "",
    "risk_notes": "",
    "blocking_notes": "",
    "paper_master_status": "未锁定",
    "experiment_master_status": "未锁定",
    "figure_master_status": "未锁定",
    "writeback_status": "未开始",
    "last_control_update_at": None,
}


def _global_prompt_templates_path() -> Path:
    return Path.home() / ".research_os" / "prompt_templates.json"


def _load_global_prompt_templates() -> dict[str, Any]:
    return load_json(_global_prompt_templates_path(), {"templates": []})


def _save_global_prompt_templates(payload: dict[str, Any]) -> None:
    save_json(_global_prompt_templates_path(), payload)


BUILTIN_TEMPLATE_SPECS: list[dict[str, Any]] = [
    {
        "template_id": "builtin:system:structured",
        "name": "系统默认：结构化推进",
        "scope": "system_default",
        "module_id": None,
        "step_id": None,
        "prompt": "你正在协助一个论文生产项目里的单一步骤。\n项目总目标：{{project_brief}}\n当前模块：{{module_title}}\n当前步骤：{{step_title}}\n当前目标：{{step_goal}}\n输入文件：\n{{input_assets}}\n期望输出：{{output_expectation}}\n\n请先明确关键风险，再直接产出最能往前推进的结果。输出要结构化，便于继续重跑、交接和写回。",
    },
    {
        "template_id": "builtin:paper:default",
        "name": "论文线默认模板",
        "scope": "module_default",
        "module_id": "paper",
        "step_id": None,
        "prompt": "你在 A线·论文中工作。\n项目主线：{{project_brief}}\n当前步骤：{{step_title}}\n目标：{{step_goal}}\n输入文件：\n{{input_assets}}\n\n请直接给出可继续写论文的内容。优先输出：候选方案、主张、结构化正文、潜在 reviewer 风险、下一步建议。",
    },
    {
        "template_id": "builtin:experiments:default",
        "name": "实验线默认模板",
        "scope": "module_default",
        "module_id": "experiments",
        "step_id": None,
        "prompt": "你在 B线·实验中工作。\n项目主线：{{project_brief}}\n当前步骤：{{step_title}}\n目标：{{step_goal}}\n输入文件：\n{{input_assets}}\n\n请给出可执行的代码/脚本/排错建议/配置建议。优先输出：最短跑通路径、风险检查、结果记录模板、回写论文要点。",
    },
    {
        "template_id": "builtin:figures:default",
        "name": "图片线默认模板",
        "scope": "module_default",
        "module_id": "figures",
        "step_id": None,
        "prompt": "你在 C线·图片中工作。\n项目主线：{{project_brief}}\n当前步骤：{{step_title}}\n目标：{{step_goal}}\n输入文件：\n{{input_assets}}\n\n请产出高质量的图片提示词、版式建议、重绘说明或导出清单。优先保证论文表达清晰、风格统一、可矢量化。",
    },
]

PROMPT_TEMPLATE_VARIABLES: dict[str, str] = {
    "project_brief": "项目总目标 / 总简介",
    "module_id": "当前模块 ID，例如 paper",
    "module_title": "当前模块标题，例如 A线 · 论文",
    "step_id": "当前步骤 ID",
    "step_title": "当前步骤标题",
    "step_goal": "当前步骤目标",
    "output_expectation": "当前步骤期望输出",
    "provider_name": "当前 provider 覆盖名",
    "model_hint": "当前模型说明",
    "input_assets": "当前步骤的输入/引用文件清单",
    "input_asset_names": "当前输入文件名列表",
    "control_next_milestone": "D 线里当前填写的下一里程碑",
    "control_submission_status": "当前投稿状态",
    "control_open_source_status": "当前开源状态",
    "current_time": "套用模板时的本地时间",
}


# ---------------------------------------------------------------------------
# Defaults / normalization
# ---------------------------------------------------------------------------


def _module_meta(module_id: str) -> dict[str, Any]:
    spec = MODULE_SPECS[module_id]
    return {
        "module_id": module_id,
        "line_id": module_id,
        "code": spec["code"],
        "title": spec["title"],
        "description": spec["description"],
        "workspace_root": spec["workspace_root"],
        "root": spec["workspace_root"],
        "library_bucket": spec["library_bucket"],
    }


def _default_web_target(module_id: str) -> str:
    if module_id == "figures":
        return "gemini"
    return "chatgpt"


def _apply_step_entry_mode(step: dict[str, Any], mode: str) -> None:
    if mode == "chatgpt":
        step["provider_mode"] = "manual_web"
        step["provider_name"] = "manual_web"
        step["provider_profile_id"] = "chatgpt-web"
        step["web_target"] = "chatgpt"
        step["model_hint"] = "ChatGPT Web"
    elif mode == "gemini":
        step["provider_mode"] = "manual_web"
        step["provider_name"] = "manual_web"
        step["provider_profile_id"] = "gemini-web"
        step["web_target"] = "gemini"
        step["model_hint"] = "Gemini Web"
    elif mode == "api":
        step["provider_mode"] = "openai_api"
        step["provider_name"] = "openai"
        step["provider_profile_id"] = "openai-default"
        step["model_hint"] = "gpt-4.1-mini"
    else:
        step["provider_mode"] = "mock"
        step["provider_name"] = "mock"
        step["provider_profile_id"] = "mock-local"
        if not step.get("model_hint") or step.get("model_hint") in {"ChatGPT Web", "Gemini Web", "gpt-4.1-mini"}:
            step["model_hint"] = "mock"
    step["updated_at"] = now_iso()


def apply_starter_ai_profile(studio: dict[str, Any], starter_ai: str | None) -> str:
    choice = str(starter_ai or "recommended").strip().lower() or "recommended"
    if choice not in {"recommended", "chatgpt", "gemini", "api", "mock"}:
        choice = "recommended"
    for step in studio.get("steps", []):
        module_id = step.get("module_id") or step.get("line_id") or "paper"
        if module_id == "control":
            continue
        target_mode = choice
        if choice == "recommended":
            target_mode = "gemini" if module_id == "figures" else "chatgpt"
        _apply_step_entry_mode(step, target_mode)
    preferences = studio.setdefault("preferences", {})
    if isinstance(preferences, dict):
        preferences["starter_ai"] = choice
    return choice


def _default_step(module_id: str, step_key: str, title: str, goal: str, order_index: int) -> dict[str, Any]:
    step_id = f"{module_id}_{step_key}"
    provider_name = "mock" if module_id != "control" else "manual_web"
    model_hint = {
        "paper": "GPT Think / GPT Pro",
        "experiments": "GPT Pro / Code model",
        "figures": "GPT Pro / Gemini / Nano Banana",
        "control": "GPT Think / 人工总控",
    }[module_id]
    return {
        "step_id": step_id,
        "module_id": module_id,
        "line_id": module_id,
        "parent_step_id": None,
        "title": title,
        "goal": goal,
        "prompt": goal,
        "output_expectation": "给出可继续推进的结果，并明确下一步。",
        "status": "todo",
        "order_index": order_index,
        "level": 0,
        "folder_hint": f"library/{MODULE_SPECS[module_id]['library_bucket']}",
        "provider_mode": "mock" if module_id != "control" else "manual_web",
        "provider_name": provider_name,
        "provider_profile_id": "mock-local" if module_id != "control" else "manual-web",
        "web_target": _default_web_target(module_id),
        "model_hint": model_hint,
        "operator_notes": "",
        "review_notes": "",
        "attempt_ids": [],
        "selected_attempt_id": None,
        "compare_attempt_id": None,
        "asset_ids": [],
        "references": [],
        "manual_review_required": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def _default_studio(project: dict[str, Any] | None = None) -> dict[str, Any]:
    brief = (project or {}).get("workflow_brief") or (project or {}).get("current_goal") or DEFAULT_CONTROL["program_goal"]
    modules = [_module_meta(module_id) for module_id in MODULE_ORDER]
    steps: list[dict[str, Any]] = []
    for module_id in MODULE_ORDER:
        for index, (step_key, title, goal) in enumerate(MODULE_SPECS[module_id]["steps"], start=1):
            steps.append(_default_step(module_id, step_key, title, goal, index))
    active_by_module = {
        module_id: next((step["step_id"] for step in steps if step["module_id"] == module_id), None)
        for module_id in MODULE_ORDER
    }
    return {
        "schema_version": 2,
        "brief": brief,
        "modules": deepcopy(modules),
        "lines": deepcopy(modules),
        "active_module_id": "paper",
        "active_step_id": active_by_module.get("paper"),
        "active_step_by_module": active_by_module,
        "steps": steps,
        "assets": [],
        "attempts": [],
        "packages": [],
        "handoffs": [],
        "prompt_templates": [],
        "recent_template_keys": [],
        "provider_profiles": deepcopy(DEFAULT_PROVIDER_PROFILES),
        "counters": {"step": 0, "asset": 0, "attempt": 0, "package": 0, "handoff": 0, "template": 0, "provider": 0},
        "control": deepcopy(DEFAULT_CONTROL),
    }


def status_label(status: str) -> str:
    return STEP_STATUS_META.get(status, STEP_STATUS_META["todo"])[0]


def status_tone(status: str) -> str:
    return STEP_STATUS_META.get(status, STEP_STATUS_META["todo"])[1]


def _infer_counter(studio: dict[str, Any], kind: str) -> int:
    prefix_map = {"step": "ST", "asset": "AS", "attempt": "AT", "package": "PKG", "handoff": "HF", "template": "TPL", "provider": "PP"}
    collection_map = {
        "step": studio.get("steps", []),
        "asset": studio.get("assets", []),
        "attempt": studio.get("attempts", []),
        "package": studio.get("packages", []),
        "handoff": studio.get("handoffs", []),
        "template": studio.get("prompt_templates", []),
        "provider": studio.get("provider_profiles", []),
    }
    key_map = {"step": "step_id", "asset": "asset_id", "attempt": "attempt_id", "package": "package_id", "handoff": "handoff_id", "template": "template_id", "provider": "profile_id"}
    prefix = prefix_map[kind]
    max_idx = 0
    for item in collection_map[kind]:
        value = str(item.get(key_map[kind], ""))
        if value.startswith(prefix):
            suffix = value[len(prefix):]
            if suffix.isdigit():
                max_idx = max(max_idx, int(suffix))
    return max_idx


def _next_id(studio: dict[str, Any], kind: str, prefix: str) -> str:
    studio.setdefault("counters", {}).setdefault(kind, 0)
    studio["counters"][kind] += 1
    return f"{prefix}{studio['counters'][kind]:04d}"


def _ordered_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(step: dict[str, Any]) -> tuple[int, int, str]:
        module_id = step.get("module_id") or step.get("line_id") or "paper"
        module_rank = MODULE_ORDER.index(module_id) if module_id in MODULE_ORDER else 999
        return (module_rank, int(step.get("order_index", 0) or 0), f"{step.get('created_at') or ''}{step.get('step_id') or ''}")

    return sorted(steps, key=sort_key)


def _ensure_references_shape(step: dict[str, Any]) -> bool:
    changed = False
    if not isinstance(step.get("references"), list):
        step["references"] = []
        changed = True
    normalized: list[dict[str, Any]] = []
    for item in step.get("references", []):
        if isinstance(item, str):
            normalized.append({"asset_id": item, "role": "reference", "created_at": now_iso()})
            changed = True
            continue
        if not isinstance(item, dict):
            changed = True
            continue
        if not item.get("asset_id"):
            changed = True
            continue
        item.setdefault("role", "reference")
        item.setdefault("created_at", now_iso())
        normalized.append(item)
    if normalized != step.get("references", []):
        step["references"] = normalized
        changed = True
    return changed


def normalize_studio(studio: dict[str, Any], project: dict[str, Any] | None = None) -> bool:
    changed = False
    default = _default_studio(project)
    if not studio:
        studio.update(default)
        return True

    if not studio.get("steps"):
        preserved = {k: deepcopy(v) for k, v in studio.items() if k not in default}
        studio.clear()
        studio.update(default)
        studio.update(preserved)
        changed = True

    if "schema_version" not in studio or int(studio.get("schema_version") or 0) < 2:
        studio["schema_version"] = 2
        changed = True

    for key in ["brief", "assets", "attempts", "packages", "handoffs", "prompt_templates", "recent_template_keys", "provider_profiles", "counters"]:
        if key not in studio:
            studio[key] = deepcopy(default[key])
            changed = True

    if "modules" not in studio:
        studio["modules"] = deepcopy(default["modules"])
        changed = True
    if "lines" not in studio:
        studio["lines"] = deepcopy(studio["modules"])
        changed = True

    known_modules = {item.get("module_id") or item.get("line_id") for item in studio.get("modules", [])}
    for module in default["modules"]:
        if module["module_id"] not in known_modules:
            studio["modules"].append(deepcopy(module))
            changed = True
    studio["lines"] = deepcopy(studio["modules"])

    control = studio.setdefault("control", {})
    for key, value in DEFAULT_CONTROL.items():
        if key not in control:
            control[key] = deepcopy(value)
            changed = True

    if not isinstance(studio.get("provider_profiles"), list):
        studio["provider_profiles"] = []
        changed = True
    profiles_by_id = {item.get("profile_id"): item for item in studio.get("provider_profiles", []) if item.get("profile_id")}
    for base in DEFAULT_PROVIDER_PROFILES:
        existing = profiles_by_id.get(base["profile_id"])
        if existing is None:
            studio["provider_profiles"].append(deepcopy(base))
            changed = True
            continue
        for key, value in base.items():
            if key not in existing:
                existing[key] = deepcopy(value)
                changed = True

    if not studio.get("brief"):
        studio["brief"] = default["brief"]
        changed = True

    # steps
    steps = studio.setdefault("steps", [])
    module_seen: dict[str, list[dict[str, Any]]] = {module_id: [] for module_id in MODULE_ORDER}
    for step in steps:
        if not isinstance(step, dict) or not step.get("step_id"):
            continue
        module_id = step.get("module_id") or step.get("line_id")
        if not module_id:
            module_id = "paper"
        if step.get("module_id") != module_id:
            step["module_id"] = module_id
            changed = True
        if step.get("line_id") != module_id:
            step["line_id"] = module_id
            changed = True
        module_seen.setdefault(module_id, []).append(step)
        if step.get("status") not in STEP_STATUS_META:
            step["status"] = "todo"
            changed = True
        if "order_index" not in step:
            step["order_index"] = len(module_seen[module_id])
            changed = True
        if "title" not in step:
            step["title"] = step["step_id"]
            changed = True
        if "goal" not in step:
            step["goal"] = ""
            changed = True
        if "prompt" not in step:
            step["prompt"] = step.get("goal") or ""
            changed = True
        if "output_expectation" not in step:
            step["output_expectation"] = "给出可继续推进的结果，并明确下一步。"
            changed = True
        if "level" not in step:
            step["level"] = 0
            changed = True
        if "parent_step_id" not in step:
            step["parent_step_id"] = None
            changed = True
        if "asset_ids" not in step or not isinstance(step.get("asset_ids"), list):
            step["asset_ids"] = []
            changed = True
        if "attempt_ids" not in step or not isinstance(step.get("attempt_ids"), list):
            step["attempt_ids"] = []
            changed = True
        if "selected_attempt_id" not in step:
            step["selected_attempt_id"] = None
            changed = True
        if "compare_attempt_id" not in step:
            step["compare_attempt_id"] = None
            changed = True
        if "provider_mode" not in step:
            step["provider_mode"] = "mock"
            changed = True
        if "provider_name" not in step:
            step["provider_name"] = "mock"
            changed = True
        if "provider_profile_id" not in step:
            step["provider_profile_id"] = "mock-local" if module_id != "control" else "manual-web"
            changed = True
        if "web_target" not in step:
            step["web_target"] = _default_web_target(module_id)
            changed = True
        if "model_hint" not in step:
            step["model_hint"] = ""
            changed = True
        if "operator_notes" not in step:
            step["operator_notes"] = ""
            changed = True
        if "review_notes" not in step:
            step["review_notes"] = ""
            changed = True
        if "manual_review_required" not in step:
            step["manual_review_required"] = True
            changed = True
        if "created_at" not in step:
            step["created_at"] = now_iso()
            changed = True
        if "updated_at" not in step:
            step["updated_at"] = step["created_at"]
            changed = True
        if "folder_hint" not in step:
            step["folder_hint"] = f"library/{MODULE_SPECS.get(module_id, MODULE_SPECS['paper'])['library_bucket']}"
            changed = True
        if _ensure_references_shape(step):
            changed = True

    # Only seed defaults for modules that have zero steps at all.
    if not steps:
        studio["steps"] = deepcopy(default["steps"])
        steps = studio["steps"]
        changed = True
    else:
        for module_id in MODULE_ORDER:
            if module_id == "control":
                continue
            existing_for_module = [step for step in steps if (step.get("module_id") or step.get("line_id")) == module_id]
            if not existing_for_module:
                for index, (_, title, goal) in enumerate(MODULE_SPECS[module_id]["steps"], start=1):
                    studio["steps"].append(_default_step(module_id, f"seed{index}", title, goal, index))
                changed = True

    for module_id in MODULE_ORDER:
        _reindex_module_steps(studio, module_id)

    studio["steps"] = _ordered_steps(studio["steps"])

    # attempts
    for attempt in studio.get("attempts", []):
        step_id = attempt.get("step_id")
        if not step_id:
            continue
        try:
            step = find_step(studio, step_id)
        except KeyError:
            continue
        module_id = step.get("module_id") or step.get("line_id") or "paper"
        if attempt.get("module_id") != module_id:
            attempt["module_id"] = module_id
            changed = True
        if attempt.get("line_id") != module_id:
            attempt["line_id"] = module_id
            changed = True
        if "provider" not in attempt:
            attempt["provider"] = attempt.get("provider_name") or step.get("provider_name") or step.get("provider_mode") or "mock"
            changed = True
        if "model" not in attempt:
            attempt["model"] = attempt.get("model_hint") or step.get("provider_name") or ""
            changed = True
        if "prompt_snapshot" not in attempt:
            attempt["prompt_snapshot"] = attempt.get("prompt") or step.get("prompt") or ""
            changed = True
        if "human_review" not in attempt:
            attempt["human_review"] = ""
            changed = True
        if "review_decision" not in attempt:
            attempt["review_decision"] = "candidate"
            changed = True
        if "review_score" not in attempt:
            attempt["review_score"] = None
            changed = True
        if "review_tags" not in attempt or not isinstance(attempt.get("review_tags"), list):
            attempt["review_tags"] = []
            changed = True
        if "created_at" not in attempt:
            attempt["created_at"] = now_iso()
            changed = True
        if "updated_at" not in attempt:
            attempt["updated_at"] = attempt["created_at"]
            changed = True
        if "status" not in attempt:
            attempt["status"] = "draft"
            changed = True
        for key in ["input_asset_ids", "output_asset_ids"]:
            if key not in attempt or not isinstance(attempt.get(key), list):
                attempt[key] = []
                changed = True
        for key in ["summary", "goal", "output_expectation", "operator_notes"]:
            if key not in attempt:
                attempt[key] = ""
                changed = True

    # templates
    if not isinstance(studio.get("prompt_templates"), list):
        studio["prompt_templates"] = []
        changed = True
    if not isinstance(studio.get("preferences"), dict):
        studio["preferences"] = {}
        changed = True
    for template in studio.get("prompt_templates", []):
        if not template.get("template_id"):
            template["template_id"] = _next_id(studio, "template", "TPL")
            changed = True
        template.setdefault("scope", "project")
        template.setdefault("module_id", None)
        template.setdefault("step_id", None)
        template.setdefault("usage_count", 0)
        template.setdefault("last_used_at", None)
        template.setdefault("created_at", now_iso())
        template.setdefault("updated_at", template["created_at"])

    # assets
    for asset in studio.get("assets", []):
        module_id = asset.get("module_id") or asset.get("line_id")
        if not module_id:
            step_id = asset.get("step_id")
            if step_id:
                try:
                    step = find_step(studio, step_id)
                    module_id = step.get("module_id") or step.get("line_id") or "paper"
                except KeyError:
                    module_id = "paper"
            else:
                module_id = "paper"
            asset["module_id"] = module_id
            changed = True
        if asset.get("line_id") != module_id:
            asset["line_id"] = module_id
            changed = True
        if "filename" not in asset:
            asset["filename"] = asset.get("name") or Path(asset.get("local_path") or "asset.bin").name
            changed = True
        if "name" not in asset:
            asset["name"] = asset["filename"]
            changed = True
        if "mime_type" not in asset:
            asset["mime_type"] = mimetypes.guess_type(asset.get("filename") or "")[0] or "application/octet-stream"
            changed = True
        if "role" not in asset:
            asset["role"] = "output"
            changed = True
        if "is_primary" not in asset:
            asset["is_primary"] = False
            changed = True
        if "referenced_by" not in asset or not isinstance(asset.get("referenced_by"), list):
            asset["referenced_by"] = []
            changed = True
        else:
            normalized_refs: list[dict[str, Any]] = []
            for ref in asset["referenced_by"]:
                if isinstance(ref, str):
                    normalized_refs.append({"step_id": ref, "role": "reference", "created_at": now_iso()})
                    changed = True
                elif isinstance(ref, dict) and ref.get("step_id"):
                    ref.setdefault("role", "reference")
                    ref.setdefault("created_at", now_iso())
                    normalized_refs.append(ref)
                else:
                    changed = True
            asset["referenced_by"] = normalized_refs
        if "library_bucket" not in asset:
            asset["library_bucket"] = module_library_bucket(asset.get("module_id") or "paper")
            changed = True
        if "source_step_id" not in asset:
            asset["source_step_id"] = asset.get("step_id")
            changed = True
        if "created_at" not in asset:
            asset["created_at"] = now_iso()
            changed = True
        if "description" not in asset:
            asset["description"] = ""
            changed = True
        if "provider_refs" not in asset:
            asset["provider_refs"] = {}
            changed = True

    # packages / handoffs
    for package in studio.get("packages", []):
        step_id = package.get("source_step_id") or package.get("step_id")
        if step_id and package.get("source_step_id") != step_id:
            package["source_step_id"] = step_id
            changed = True
        if step_id and package.get("step_id") != step_id:
            package["step_id"] = step_id
            changed = True
        if "manifest_path" not in package and package.get("folder_path"):
            package["manifest_path"] = str(Path(package["folder_path"]) / "manifest.json")
            changed = True
        if "asset_ids" not in package or not isinstance(package.get("asset_ids"), list):
            package["asset_ids"] = []
            changed = True
        if "status" not in package:
            package["status"] = "prepared"
            changed = True
        if "created_at" not in package:
            package["created_at"] = now_iso()
            changed = True
    for handoff in studio.get("handoffs", []):
        if "from_attempt_id" not in handoff:
            handoff["from_attempt_id"] = None
            changed = True
        if "to_provider" not in handoff:
            handoff["to_provider"] = handoff.get("to_label") or handoff.get("mode") or "manual_web"
            changed = True
        if "to_step_id" not in handoff:
            handoff["to_step_id"] = None
            changed = True
        if "result_asset_ids" not in handoff or not isinstance(handoff.get("result_asset_ids"), list):
            handoff["result_asset_ids"] = []
            changed = True
        if "status" not in handoff:
            handoff["status"] = "prepared"
            changed = True
        if "created_at" not in handoff:
            handoff["created_at"] = now_iso()
            changed = True

    # rebuild referenced_by from step refs and owned assets
    assets_by_id = {asset.get("asset_id"): asset for asset in studio.get("assets", []) if asset.get("asset_id")}
    for asset in assets_by_id.values():
        refs_map: dict[tuple[str, str], dict[str, Any]] = {}
        if asset.get("step_id"):
            refs_map[(asset["step_id"], asset.get("role") or "output")] = {
                "step_id": asset["step_id"],
                "role": asset.get("role") or "output",
                "created_at": asset.get("created_at") or now_iso(),
            }
        for ref in asset.get("referenced_by", []):
            if ref.get("step_id"):
                refs_map[(ref["step_id"], ref.get("role") or "reference")] = {
                    "step_id": ref["step_id"],
                    "role": ref.get("role") or "reference",
                    "created_at": ref.get("created_at") or now_iso(),
                }
        asset["referenced_by"] = list(refs_map.values())
    for step in studio.get("steps", []):
        for ref in step.get("references", []):
            asset = assets_by_id.get(ref.get("asset_id"))
            if asset is None:
                continue
            key = (step["step_id"], ref.get("role") or "reference")
            existing = {(item.get("step_id"), item.get("role")): item for item in asset.get("referenced_by", [])}
            if key not in existing:
                asset.setdefault("referenced_by", []).append({
                    "step_id": step["step_id"],
                    "role": ref.get("role") or "reference",
                    "created_at": ref.get("created_at") or now_iso(),
                })
                changed = True

    # active module / step
    if "active_step_by_module" not in studio or not isinstance(studio.get("active_step_by_module"), dict):
        studio["active_step_by_module"] = {}
        changed = True
    for module_id in MODULE_ORDER:
        module_steps = steps_for_line(studio, module_id)
        fallback = module_steps[0]["step_id"] if module_steps else None
        if module_id not in studio["active_step_by_module"] or studio["active_step_by_module"].get(module_id) not in {step["step_id"] for step in module_steps}:
            studio["active_step_by_module"][module_id] = fallback
            changed = True
    if studio.get("active_module_id") not in MODULE_ORDER:
        studio["active_module_id"] = "paper"
        changed = True
    active_module = studio.get("active_module_id") or "paper"
    valid_active_ids = {step["step_id"] for step in studio.get("steps", [])}
    preferred_active = studio["active_step_by_module"].get(active_module)
    if studio.get("active_step_id") not in valid_active_ids:
        studio["active_step_id"] = preferred_active or next(iter(valid_active_ids), None)
        changed = True
    if studio.get("active_step_id"):
        try:
            active = find_step(studio, studio["active_step_id"])
            if studio.get("active_module_id") != active.get("module_id"):
                studio["active_module_id"] = active.get("module_id")
                changed = True
            if studio["active_step_by_module"].get(active.get("module_id")) != active["step_id"]:
                studio["active_step_by_module"][active.get("module_id")] = active["step_id"]
                changed = True
        except KeyError:
            pass

    for key in ["step", "asset", "attempt", "package", "handoff", "template", "provider"]:
        studio["counters"][key] = max(int(studio["counters"].get(key, 0) or 0), _infer_counter(studio, key))

    return changed


# ---------------------------------------------------------------------------
# Module / step helpers
# ---------------------------------------------------------------------------


def module_library_bucket(module_id: str) -> str:
    return MODULE_SPECS.get(module_id, MODULE_SPECS["paper"])["library_bucket"]


def steps_for_line(studio: dict[str, Any], line_id: str) -> list[dict[str, Any]]:
    return [step for step in _ordered_steps(studio.get("steps", [])) if (step.get("module_id") or step.get("line_id")) == line_id]


def steps_for_module(studio: dict[str, Any], module_id: str) -> list[dict[str, Any]]:
    return steps_for_line(studio, module_id)


def find_step(studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in studio.get("steps", []):
        if step.get("step_id") == step_id:
            return step
    raise KeyError(step_id)


def active_step(studio: dict[str, Any], module_id: str | None = None) -> dict[str, Any] | None:
    if module_id:
        step_id = studio.get("active_step_by_module", {}).get(module_id)
        if step_id:
            try:
                return find_step(studio, step_id)
            except KeyError:
                pass
        module_steps = steps_for_module(studio, module_id)
        return module_steps[0] if module_steps else None
    step_id = studio.get("active_step_id")
    if step_id:
        try:
            return find_step(studio, step_id)
        except KeyError:
            pass
    return studio.get("steps", [None])[0]


def set_active_module(studio: dict[str, Any], module_id: str) -> dict[str, Any] | None:
    studio["active_module_id"] = module_id
    step = active_step(studio, module_id)
    if step is not None:
        set_active_step(studio, step["step_id"])
    return step


def set_active_step(studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    studio["active_step_id"] = step_id
    studio["active_module_id"] = module_id
    studio.setdefault("active_step_by_module", {})[module_id] = step_id
    if step.get("status") == "todo":
        step["status"] = "active"
    step["updated_at"] = now_iso()
    return step


def _reindex_module_steps(studio: dict[str, Any], module_id: str) -> None:
    module_steps = [step for step in studio.get("steps", []) if (step.get("module_id") or step.get("line_id")) == module_id]
    module_steps = sorted(module_steps, key=lambda item: (int(item.get("order_index", 0) or 0), item.get("created_at") or "", item.get("step_id") or ""))
    for idx, step in enumerate(module_steps, start=1):
        step["order_index"] = idx


def _step_index_in_module(studio: dict[str, Any], step_id: str) -> int:
    step = find_step(studio, step_id)
    module_steps = steps_for_module(studio, step.get("module_id") or step.get("line_id") or "paper")
    for idx, item in enumerate(module_steps):
        if item["step_id"] == step_id:
            return idx
    raise KeyError(step_id)


def _descendant_step_ids(studio: dict[str, Any], step_id: str) -> list[str]:
    descendants: list[str] = []
    step_ids = {item.get("step_id") for item in studio.get("steps", [])}
    changed = True
    queue = [step_id]
    while changed:
        changed = False
        for step in studio.get("steps", []):
            parent = step.get("parent_step_id")
            if parent in queue and step.get("step_id") not in queue:
                queue.append(step["step_id"])
                changed = True
    descendants.extend([item for item in queue if item in step_ids])
    return descendants


def _subtree_block(studio: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    step = find_step(studio, step_id)
    module_steps = steps_for_module(studio, step.get("module_id") or step.get("line_id") or "paper")
    block_ids = set(_descendant_step_ids(studio, step_id))
    ordered: list[dict[str, Any]] = []
    in_block = False
    for item in module_steps:
        if item["step_id"] == step_id:
            in_block = True
        if in_block and item["step_id"] in block_ids:
            ordered.append(item)
            continue
        if in_block and item["step_id"] not in block_ids:
            break
    if ordered:
        return ordered
    return [step]


def add_step(
    studio: dict[str, Any],
    module_id: str,
    title: str,
    goal: str = "",
    prompt: str = "",
    *,
    parent_step_id: str | None = None,
    after_step_id: str | None = None,
) -> dict[str, Any]:
    studio["counters"]["step"] = max(int(studio.get("counters", {}).get("step", 0) or 0), _infer_counter(studio, "step"))
    step_id = _next_id(studio, "step", "ST")
    module_steps = steps_for_module(studio, module_id)
    insert_after = after_step_id
    if insert_after is None and parent_step_id:
        parent_block = _subtree_block(studio, parent_step_id)
        insert_after = parent_block[-1]["step_id"]
    if insert_after:
        try:
            insert_pos = _step_index_in_module(studio, insert_after) + 1
        except KeyError:
            insert_pos = len(module_steps)
    else:
        insert_pos = len(module_steps)
    for item in module_steps[insert_pos:]:
        item["order_index"] = int(item.get("order_index", 0) or 0) + 1
    level = 0
    if parent_step_id:
        try:
            parent = find_step(studio, parent_step_id)
            level = int(parent.get("level", 0) or 0) + 1
        except KeyError:
            parent_step_id = None
            level = 0
    new_step = {
        "step_id": step_id,
        "module_id": module_id,
        "line_id": module_id,
        "parent_step_id": parent_step_id,
        "title": title or "新的步骤",
        "goal": goal or "",
        "prompt": prompt or goal or "",
        "output_expectation": "给出可继续推进的结果，并明确下一步。",
        "status": "todo",
        "order_index": insert_pos + 1,
        "level": level,
        "folder_hint": f"library/{module_library_bucket(module_id)}",
        "provider_mode": "mock" if module_id != "control" else "manual_web",
        "provider_name": "mock" if module_id != "control" else "manual_web",
        "provider_profile_id": "mock-local" if module_id != "control" else "manual-web",
        "model_hint": "",
        "operator_notes": "",
        "review_notes": "",
        "attempt_ids": [],
        "selected_attempt_id": None,
        "compare_attempt_id": None,
        "asset_ids": [],
        "references": [],
        "manual_review_required": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    studio.setdefault("steps", []).append(new_step)
    _reindex_module_steps(studio, module_id)
    set_active_step(studio, step_id)
    return new_step


def add_substep(studio: dict[str, Any], parent_step_id: str, title: str, goal: str = "", prompt: str = "") -> dict[str, Any]:
    parent = find_step(studio, parent_step_id)
    block = _subtree_block(studio, parent_step_id)
    after_id = block[-1]["step_id"] if block else parent_step_id
    return add_step(
        studio,
        parent.get("module_id") or parent.get("line_id") or "paper",
        title=title or f"{parent['title']} · 子步骤",
        goal=goal or parent.get("goal") or "",
        prompt=prompt or parent.get("prompt") or "",
        parent_step_id=parent_step_id,
        after_step_id=after_id,
    )


def move_step(studio: dict[str, Any], step_id: str, direction: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    module_steps = steps_for_module(studio, module_id)
    block = _subtree_block(studio, step_id)
    if not block:
        return step
    block_start = module_steps.index(block[0])
    block_end = block_start + len(block)
    if direction == "up":
        if block_start == 0:
            return step
        prev_start = block_start - 1
        prev_candidate = module_steps[prev_start]
        while prev_start > 0 and prev_candidate.get("parent_step_id") and prev_candidate.get("parent_step_id") in {item["step_id"] for item in module_steps[:prev_start]}:
            # climb to start of previous subtree
            prev_start -= 1
            prev_candidate = module_steps[prev_start]
            if prev_candidate.get("parent_step_id") is None:
                break
        prev_block = _subtree_block(studio, module_steps[prev_start]["step_id"])
        new_order = module_steps[:prev_start] + block + prev_block + module_steps[block_end:]
    elif direction == "down":
        if block_end >= len(module_steps):
            return step
        next_block = _subtree_block(studio, module_steps[block_end]["step_id"])
        next_end = block_end + len(next_block)
        new_order = module_steps[:block_start] + next_block + block + module_steps[next_end:]
    else:
        return step
    for idx, item in enumerate(new_order, start=1):
        item["order_index"] = idx
        item["updated_at"] = now_iso()
    studio["steps"] = [item for item in studio.get("steps", []) if (item.get("module_id") or item.get("line_id")) != module_id] + new_order
    studio["steps"] = _ordered_steps(studio["steps"])
    set_active_step(studio, step_id)
    return step


def delete_step(studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    removed_ids = set(_descendant_step_ids(studio, step_id))
    studio["steps"] = [item for item in studio.get("steps", []) if item.get("step_id") not in removed_ids]

    # remove step references from assets
    for asset in studio.get("assets", []):
        refs = []
        for ref in asset.get("referenced_by", []):
            if ref.get("step_id") not in removed_ids:
                refs.append(ref)
        asset["referenced_by"] = refs
        if asset.get("step_id") in removed_ids:
            asset["orphaned_from_step_id"] = asset.get("step_id")
            asset["step_id"] = None

    # remove references on remaining steps
    for item in studio.get("steps", []):
        item["references"] = [ref for ref in item.get("references", []) if ref.get("asset_id")]

    # remove attempts owned by removed steps
    studio["attempts"] = [attempt for attempt in studio.get("attempts", []) if attempt.get("step_id") not in removed_ids]

    active_for_module = studio.get("active_step_by_module", {}).get(module_id)
    if active_for_module in removed_ids:
        fallback = steps_for_module(studio, module_id)
        studio.setdefault("active_step_by_module", {})[module_id] = fallback[0]["step_id"] if fallback else None
    if studio.get("active_step_id") in removed_ids:
        fallback = active_step(studio, module_id)
        studio["active_step_id"] = fallback["step_id"] if fallback else None
    _reindex_module_steps(studio, module_id)
    studio["steps"] = _ordered_steps(studio.get("steps", []))
    return step


def reopen_step(studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = set_active_step(studio, step_id)
    step["status"] = "active"
    step["updated_at"] = now_iso()
    return step


def update_step_from_form(studio: dict[str, Any], step_id: str, data: dict[str, Any]) -> dict[str, Any]:
    step = set_active_step(studio, step_id)
    for field in [
        "title",
        "goal",
        "prompt",
        "output_expectation",
        "provider_mode",
        "provider_name",
        "provider_profile_id",
        "web_target",
        "model_hint",
        "operator_notes",
        "review_notes",
    ]:
        if field in data:
            step[field] = str(data.get(field) or "").strip()
    step["updated_at"] = now_iso()
    return step


def update_control_from_form(studio: dict[str, Any], data: dict[str, Any]) -> None:
    control = studio.setdefault("control", deepcopy(DEFAULT_CONTROL))
    for field in DEFAULT_CONTROL:
        if field in data:
            control[field] = str(data.get(field) or "").strip()
    control["last_control_update_at"] = now_iso()
    if control.get("program_goal"):
        studio["brief"] = control["program_goal"]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------


def _builtin_prompt_templates(module_id: str, step: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    out = [deepcopy(item) for item in BUILTIN_TEMPLATE_SPECS if item.get("module_id") in {None, module_id}]
    if step is not None:
        out.append(
            {
                "template_id": f"builtin:step-seed:{step['step_id']}",
                "name": f"当前步骤默认：{step['title']}",
                "scope": "step_default",
                "module_id": module_id,
                "step_id": step["step_id"],
                "prompt": step.get("goal") or step.get("prompt") or "",
            }
        )
    return out


def _template_usage_key(origin: str, template_id: str) -> str:
    return f"{origin}:{template_id}"


def prompt_template_context(studio: dict[str, Any], step_id: str) -> dict[str, str]:
    step = find_step(studio, step_id)
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    module = next((item for item in studio.get("modules", []) if (item.get("module_id") or item.get("line_id")) == module_id), _module_meta(module_id))
    inputs = [asset for asset in assets_for_step(studio, step_id) if (asset.get("context_role") or asset.get("role")) in {"input", "reference"}]
    if inputs:
        input_assets = "\n".join(f"- {asset.get('asset_id')} | {asset.get('filename') or asset.get('name') or '-'} | {(asset.get('context_role') or asset.get('role') or '-')} | {asset.get('local_path') or '-'}" for asset in inputs)
        input_names = ", ".join(str(asset.get("filename") or asset.get("name") or asset.get("asset_id") or "") for asset in inputs)
    else:
        input_assets = "- 当前没有输入文件"
        input_names = ""
    control = studio.get("control", {})
    return {
        "project_brief": str(studio.get("brief") or ""),
        "module_id": str(module_id),
        "module_title": str(module.get("title") or module_id),
        "step_id": str(step.get("step_id") or ""),
        "step_title": str(step.get("title") or ""),
        "step_goal": str(step.get("goal") or ""),
        "output_expectation": str(step.get("output_expectation") or ""),
        "provider_name": str(step.get("provider_name") or step.get("provider_mode") or ""),
        "model_hint": str(step.get("model_hint") or ""),
        "input_assets": input_assets,
        "input_asset_names": input_names,
        "control_next_milestone": str(control.get("next_milestone") or ""),
        "control_submission_status": str(control.get("submission_status") or ""),
        "control_open_source_status": str(control.get("open_source_status") or ""),
        "current_time": now_iso(),
    }


def render_prompt_template(studio: dict[str, Any], step_id: str, prompt: str) -> str:
    rendered = str(prompt or "")
    for key, value in prompt_template_context(studio, step_id).items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def list_available_prompt_templates(studio: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    step = find_step(studio, step_id)
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    project_templates = deepcopy(studio.get("prompt_templates", []))
    global_templates = deepcopy(_load_global_prompt_templates().get("templates", []))
    recent_keys = studio.get("recent_template_keys", []) or []
    recent_rank = {key: idx for idx, key in enumerate(recent_keys)}

    combined: list[dict[str, Any]] = []
    for item in _builtin_prompt_templates(module_id, step):
        item["origin"] = "builtin"
        item["usage_key"] = _template_usage_key("builtin", item["template_id"])
        combined.append(item)
    for item in project_templates:
        if item.get("scope") == "current_step" and item.get("step_id") not in {None, step_id}:
            continue
        if item.get("scope") == "module" and item.get("module_id") not in {None, module_id}:
            continue
        item["origin"] = "project"
        item["usage_key"] = _template_usage_key("project", item["template_id"])
        combined.append(item)
    for item in global_templates:
        if item.get("scope") == "current_step" and item.get("step_id") not in {None, step_id}:
            continue
        if item.get("scope") == "module" and item.get("module_id") not in {None, module_id}:
            continue
        item["origin"] = "global"
        item["usage_key"] = _template_usage_key("global", item["template_id"])
        combined.append(item)

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
        recent_bonus = recent_rank.get(item.get("usage_key"), 999)
        scope = item.get("scope") or "project"
        scope_rank = {"system_default": 0, "module_default": 1, "step_default": 2, "current_step": 3, "module": 4, "project": 5, "global_personal": 6}.get(scope, 7)
        name = item.get("name") or item.get("template_id") or ""
        return (recent_bonus, scope_rank, str(item.get("origin")), name)

    return sorted(combined, key=sort_key)


def _touch_recent_template(studio: dict[str, Any], usage_key: str) -> None:
    recent = [key for key in studio.get("recent_template_keys", []) if key != usage_key]
    recent.insert(0, usage_key)
    studio["recent_template_keys"] = recent[:12]


def save_prompt_template(studio: dict[str, Any], step_id: str, name: str, scope: str, prompt: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    scope = {
        "step": "current_step",
        "step_template": "current_step",
        "current_step_template": "current_step",
        "module_default": "module",
        "module_template": "module",
        "current_module": "module",
        "current_module_template": "module",
        "project_template": "project",
        "global": "global_personal",
        "global_template": "global_personal",
        "personal_global": "global_personal",
    }.get(scope, scope)
    payload = {
        "name": name.strip() or f"{step['title']} prompt",
        "prompt": prompt,
        "scope": scope,
        "module_id": module_id if scope in {"module", "global_personal"} else None,
        "step_id": step_id if scope in {"current_step"} else None,
        "usage_count": 0,
        "last_used_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if scope == "global_personal":
        data = _load_global_prompt_templates()
        templates = data.setdefault("templates", [])
        template_id = f"G{len(templates) + 1:04d}"
        payload["template_id"] = template_id
        templates.append(payload)
        _save_global_prompt_templates(data)
        payload["origin"] = "global"
        payload["usage_key"] = _template_usage_key("global", template_id)
        return payload
    template_id = _next_id(studio, "template", "TPL")
    payload["template_id"] = template_id
    studio.setdefault("prompt_templates", []).append(payload)
    payload["origin"] = "project"
    payload["usage_key"] = _template_usage_key("project", template_id)
    return payload


def apply_prompt_template(studio: dict[str, Any], step_id: str, usage_key: str) -> dict[str, Any]:
    step = set_active_step(studio, step_id)
    templates = list_available_prompt_templates(studio, step_id)
    match = next((item for item in templates if item.get("usage_key") == usage_key), None)
    if match is None:
        raise KeyError(usage_key)
    step["prompt"] = render_prompt_template(studio, step_id, str(match.get("prompt") or ""))
    step["updated_at"] = now_iso()
    _touch_recent_template(studio, usage_key)
    if match.get("origin") == "project":
        for item in studio.get("prompt_templates", []):
            if item.get("template_id") == match.get("template_id"):
                item["usage_count"] = int(item.get("usage_count", 0) or 0) + 1
                item["last_used_at"] = now_iso()
                item["updated_at"] = now_iso()
                break
    elif match.get("origin") == "global":
        data = _load_global_prompt_templates()
        touched = False
        for item in data.get("templates", []):
            if item.get("template_id") == match.get("template_id"):
                item["usage_count"] = int(item.get("usage_count", 0) or 0) + 1
                item["last_used_at"] = now_iso()
                item["updated_at"] = now_iso()
                touched = True
                break
        if touched:
            _save_global_prompt_templates(data)
    step["template_usage_key"] = usage_key
    return match


# ---------------------------------------------------------------------------
# Provider profiles
# ---------------------------------------------------------------------------


def provider_profiles(studio: dict[str, Any]) -> list[dict[str, Any]]:
    return list(studio.get("provider_profiles", []))


def find_provider_profile(studio: dict[str, Any], profile_id: str | None) -> dict[str, Any] | None:
    if not profile_id:
        return None
    for item in studio.get("provider_profiles", []):
        if item.get("profile_id") == profile_id:
            return item
    return None


def upsert_provider_profile(
    studio: dict[str, Any],
    *,
    profile_id: str | None,
    name: str,
    provider: str,
    base_url: str,
    default_model: str,
    api_key_env: str,
    notes: str,
) -> dict[str, Any]:
    if profile_id:
        existing = find_provider_profile(studio, profile_id)
    else:
        existing = None
    if existing is None:
        profile_id = _next_id(studio, "provider", "PP")
        existing = {"profile_id": profile_id, "created_at": now_iso(), "is_builtin": False}
        studio.setdefault("provider_profiles", []).append(existing)
    existing.update(
        {
            "name": name.strip() or "未命名 provider",
            "provider": provider.strip() or "openai",
            "base_url": base_url.strip(),
            "default_model": default_model.strip(),
            "api_key_env": api_key_env.strip(),
            "notes": notes.strip(),
            "updated_at": now_iso(),
        }
    )
    return existing


def delete_provider_profile(studio: dict[str, Any], profile_id: str) -> dict[str, Any]:
    profile = find_provider_profile(studio, profile_id)
    if profile is None:
        raise KeyError(profile_id)
    if profile.get("is_builtin"):
        raise RuntimeError("内置 provider profile 不能删除，但可以在步骤里不使用它。")
    studio["provider_profiles"] = [item for item in studio.get("provider_profiles", []) if item.get("profile_id") != profile_id]
    for step in studio.get("steps", []):
        if step.get("provider_profile_id") == profile_id:
            step["provider_profile_id"] = "mock-local"
    return profile


# ---------------------------------------------------------------------------
# File library / assets
# ---------------------------------------------------------------------------


def ensure_studio_layout(root: str | Path) -> None:
    root_path = Path(root)
    # Keep legacy workspace dirs for compatibility.
    for module_id in MODULE_ORDER:
        workspace_root = root_path / MODULE_SPECS[module_id]["workspace_root"]
        ensure_dir(workspace_root)
        readme = workspace_root / "README.md"
        if not readme.exists():
            body = [f"# {MODULE_SPECS[module_id]['title']}", "", MODULE_SPECS[module_id]["description"], ""]
            write_text(readme, "\n".join(body))
    library_root = ensure_dir(root_path / "library")
    for bucket in LIBRARY_BUCKETS:
        bucket_path = ensure_dir(library_root / bucket)
        readme = bucket_path / "README.md"
        if not readme.exists() and bucket != "handoff_packages":
            write_text(readme, f"# library/{bucket}\n\n共享项目文件库分区：{bucket}\n")
    control_active = ensure_dir(root_path / "control" / "active_context")
    active = control_active / "CURRENT_STEP.md"
    if not active.exists():
        write_text(active, "# Current Step Context\n\n这里记录当前步骤上下文。\n")


def _asset_save_dir(root: str | Path, step: dict[str, Any], role: str) -> Path:
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    bucket = module_library_bucket(module_id)
    # Keep non-shared admin assets in shared bucket by default.
    if module_id == "control" and role in {"output", "final"}:
        bucket = "shared"
    return ensure_dir(Path(root) / "library" / bucket)


def assets_for_step(studio: dict[str, Any], step_id: str, role: str | None = None) -> list[dict[str, Any]]:
    step = find_step(studio, step_id)
    assets_by_id = {asset.get("asset_id"): asset for asset in studio.get("assets", []) if asset.get("asset_id")}
    items: list[dict[str, Any]] = []
    for asset in studio.get("assets", []):
        if asset.get("step_id") == step_id:
            context_role = asset.get("role") or "output"
            if role and context_role != role:
                continue
            owned = deepcopy(asset)
            owned["context_role"] = context_role
            owned["owned_by_step"] = True
            owned["source_role"] = asset.get("role")
            items.append(owned)
    for ref in step.get("references", []):
        asset = assets_by_id.get(ref.get("asset_id"))
        if asset is None:
            continue
        context_role = ref.get("role") or "reference"
        if role and context_role != role:
            continue
        linked = deepcopy(asset)
        linked["context_role"] = context_role
        linked["role"] = context_role
        linked["owned_by_step"] = False
        linked["source_role"] = asset.get("role")
        linked["linked_from_step_id"] = asset.get("step_id") or asset.get("source_step_id")
        linked["linked_at"] = ref.get("created_at")
        items.append(linked)
    return sorted(items, key=lambda item: (item.get("linked_at") or item.get("created_at") or "", item.get("asset_id") or ""))


def all_assets(studio: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(studio.get("assets", []), key=lambda item: (item.get("created_at") or "", item.get("asset_id") or ""), reverse=True)


def attempts_for_step(studio: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    return [item for item in sorted(studio.get("attempts", []), key=lambda item: (item.get("created_at") or "", item.get("attempt_id") or ""), reverse=True) if item.get("step_id") == step_id]


def register_asset(
    root: str | Path,
    studio: dict[str, Any],
    step_id: str,
    role: str,
    filename: str,
    content: bytes,
    *,
    source: str = "user_upload",
    description: str = "",
    attempt_id: str | None = None,
    package_id: str | None = None,
    handoff_id: str | None = None,
) -> dict[str, Any]:
    step = find_step(studio, step_id)
    asset_id = _next_id(studio, "asset", "AS")
    safe_name = Path(filename or f"{asset_id}.bin").name
    stem = slugify(Path(safe_name).stem) or asset_id.lower()
    ext = Path(safe_name).suffix or ".bin"
    rel_dir = _asset_save_dir(root, step, role)
    saved_name = f"{asset_id}_{stem}{ext}"
    path = rel_dir / saved_name
    path.write_bytes(content)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    module_id = step.get("module_id") or step.get("line_id") or "paper"
    asset = {
        "asset_id": asset_id,
        "filename": safe_name,
        "name": safe_name,
        "local_path": str(path.relative_to(Path(root))),
        "mime_type": mime,
        "module_id": module_id,
        "line_id": module_id,
        "step_id": step_id,
        "source_step_id": step_id,
        "attempt_id": attempt_id,
        "package_id": package_id,
        "handoff_id": handoff_id,
        "role": role,
        "source": source,
        "is_primary": False,
        "description": description,
        "created_at": now_iso(),
        "provider_refs": {},
        "library_bucket": module_library_bucket(module_id),
        "referenced_by": [{"step_id": step_id, "role": role, "created_at": now_iso()}],
    }
    studio.setdefault("assets", []).append(asset)
    step.setdefault("asset_ids", []).append(asset_id)
    step["updated_at"] = now_iso()
    return asset


def link_existing_asset(studio: dict[str, Any], step_id: str, asset_id: str, role: str = "reference") -> dict[str, Any]:
    step = find_step(studio, step_id)
    asset = next((item for item in studio.get("assets", []) if item.get("asset_id") == asset_id), None)
    if asset is None:
        raise KeyError(asset_id)
    references = step.setdefault("references", [])
    existing = next((item for item in references if item.get("asset_id") == asset_id and item.get("role") == role), None)
    if existing is None:
        references.append({"asset_id": asset_id, "role": role, "created_at": now_iso()})
    ref_key = (step_id, role)
    existing_refs = {(item.get("step_id"), item.get("role")): item for item in asset.setdefault("referenced_by", [])}
    if ref_key not in existing_refs:
        asset["referenced_by"].append({"step_id": step_id, "role": role, "created_at": now_iso()})
    step["updated_at"] = now_iso()
    return asset


def unlink_step_asset(studio: dict[str, Any], step_id: str, asset_id: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    before = len(step.get("references", []))
    step["references"] = [item for item in step.get("references", []) if item.get("asset_id") != asset_id]
    asset = next((item for item in studio.get("assets", []) if item.get("asset_id") == asset_id), None)
    if asset:
        asset["referenced_by"] = [item for item in asset.get("referenced_by", []) if item.get("step_id") != step_id or (item.get("role") or "reference") in {asset.get("role"), "output", "input", "final"} and asset.get("step_id") == step_id]
    if len(step.get("references", [])) == before:
        raise KeyError(asset_id)
    step["updated_at"] = now_iso()
    return asset or {"asset_id": asset_id}


def mark_asset_primary(studio: dict[str, Any], asset_id: str) -> dict[str, Any]:
    target = next((asset for asset in studio.get("assets", []) if asset.get("asset_id") == asset_id), None)
    if target is None:
        raise KeyError(asset_id)
    source_step_id = target.get("step_id")
    source_role = target.get("role")
    for asset in studio.get("assets", []):
        if asset.get("step_id") == source_step_id and asset.get("role") == source_role:
            asset["is_primary"] = asset.get("asset_id") == asset_id
    return target


def rename_asset(root: str | Path, studio: dict[str, Any], asset_id: str, new_name: str) -> dict[str, Any]:
    asset = next((item for item in studio.get("assets", []) if item.get("asset_id") == asset_id), None)
    if asset is None:
        raise KeyError(asset_id)
    clean_name = Path(new_name.strip()).name
    if not clean_name:
        raise ValueError("新的文件名不能为空。")
    old_path = resolve_within_root(root, asset["local_path"])
    suffix = Path(clean_name).suffix or old_path.suffix
    stem = slugify(Path(clean_name).stem) or asset_id.lower()
    new_filename = f"{asset_id}_{stem}{suffix}"
    new_path = old_path.with_name(new_filename)
    if old_path.exists() and old_path != new_path:
        old_path.rename(new_path)
    asset["filename"] = clean_name
    asset["name"] = clean_name
    asset["local_path"] = str(new_path.relative_to(Path(root).resolve()))
    asset["mime_type"] = mimetypes.guess_type(clean_name)[0] or asset.get("mime_type") or "application/octet-stream"
    return asset


def move_asset(root: str | Path, studio: dict[str, Any], asset_id: str, bucket: str) -> dict[str, Any]:
    if bucket not in LIBRARY_BUCKETS:
        raise ValueError(f"不支持的文件库分区：{bucket}")
    asset = next((item for item in studio.get("assets", []) if item.get("asset_id") == asset_id), None)
    if asset is None:
        raise KeyError(asset_id)
    old_path = resolve_within_root(root, asset["local_path"])
    new_dir = ensure_dir(Path(root).resolve() / "library" / bucket)
    new_path = new_dir / old_path.name
    if old_path.exists() and old_path != new_path:
        shutil.move(str(old_path), str(new_path))
    asset["local_path"] = str(new_path.relative_to(Path(root).resolve()))
    asset["library_bucket"] = bucket
    return asset


def delete_asset(root: str | Path, studio: dict[str, Any], asset_id: str) -> dict[str, Any]:
    asset = next((item for item in studio.get("assets", []) if item.get("asset_id") == asset_id), None)
    if asset is None:
        raise KeyError(asset_id)
    path = resolve_within_root(root, asset["local_path"])
    if path.exists() and path.is_file():
        path.unlink()
    studio["assets"] = [item for item in studio.get("assets", []) if item.get("asset_id") != asset_id]
    for step in studio.get("steps", []):
        step["asset_ids"] = [item for item in step.get("asset_ids", []) if item != asset_id]
        step["references"] = [item for item in step.get("references", []) if item.get("asset_id") != asset_id]
    for attempt in studio.get("attempts", []):
        attempt["input_asset_ids"] = [item for item in attempt.get("input_asset_ids", []) if item != asset_id]
        attempt["output_asset_ids"] = [item for item in attempt.get("output_asset_ids", []) if item != asset_id]
    for package in studio.get("packages", []):
        package["asset_ids"] = [item for item in package.get("asset_ids", []) if item != asset_id]
    for handoff in studio.get("handoffs", []):
        handoff["result_asset_ids"] = [item for item in handoff.get("result_asset_ids", []) if item != asset_id]
    return asset


def asset_reference_summary(studio: dict[str, Any], asset_id: str) -> list[dict[str, Any]]:
    asset = next((item for item in studio.get("assets", []) if item.get("asset_id") == asset_id), None)
    if asset is None:
        return []
    refs = []
    for ref in asset.get("referenced_by", []):
        refs.append({
            "step_id": ref.get("step_id"),
            "role": ref.get("role") or "reference",
            "created_at": ref.get("created_at"),
        })
    return refs


# ---------------------------------------------------------------------------
# Attempts / outputs
# ---------------------------------------------------------------------------


def create_attempt(studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    attempt_id = _next_id(studio, "attempt", "AT")
    input_assets = [asset["asset_id"] for asset in assets_for_step(studio, step_id) if asset.get("context_role") in {"input", "reference"} or asset.get("role") in {"input", "reference"}]
    attempt = {
        "attempt_id": attempt_id,
        "step_id": step_id,
        "module_id": step.get("module_id") or step.get("line_id") or "paper",
        "line_id": step.get("module_id") or step.get("line_id") or "paper",
        "provider_mode": step.get("provider_mode") or "mock",
        "provider_name": step.get("provider_name") or "mock",
        "provider": step.get("provider_name") or step.get("provider_mode") or "mock",
        "model_hint": step.get("model_hint") or "",
        "model": step.get("provider_name") or step.get("model_hint") or "",
        "prompt": step.get("prompt") or "",
        "prompt_snapshot": step.get("prompt") or "",
        "goal": step.get("goal") or "",
        "output_expectation": step.get("output_expectation") or "",
        "operator_notes": step.get("operator_notes") or "",
        "input_asset_ids": input_assets,
        "output_asset_ids": [],
        "status": "draft",
        "summary": "",
        "human_review": "",
        "review_decision": "candidate",
        "review_score": None,
        "review_tags": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    studio.setdefault("attempts", []).append(attempt)
    step.setdefault("attempt_ids", []).append(attempt_id)
    step["selected_attempt_id"] = attempt_id
    step["status"] = "active"
    step["updated_at"] = now_iso()
    studio["active_step_id"] = step_id
    studio.setdefault("active_step_by_module", {})[step.get("module_id") or step.get("line_id") or "paper"] = step_id
    return attempt


def complete_attempt_text_output(root: str | Path, studio: dict[str, Any], attempt_id: str, text: str, *, filename_hint: str = "output.md", source: str = "ai_generated") -> dict[str, Any]:
    attempt = next(item for item in studio.get("attempts", []) if item.get("attempt_id") == attempt_id)
    attempt["status"] = "review"
    attempt["summary"] = text[:400]
    attempt["updated_at"] = now_iso()
    asset = register_asset(root, studio, attempt["step_id"], "output", filename_hint, text.encode("utf-8"), source=source, attempt_id=attempt_id)
    attempt.setdefault("output_asset_ids", []).append(asset["asset_id"])
    step = find_step(studio, attempt["step_id"])
    step["selected_attempt_id"] = attempt_id
    return asset


def select_attempt(studio: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    attempt = next(item for item in studio.get("attempts", []) if item.get("attempt_id") == attempt_id)
    step = find_step(studio, attempt["step_id"])
    step["selected_attempt_id"] = attempt_id
    step["updated_at"] = now_iso()
    return attempt


def set_compare_attempt(studio: dict[str, Any], step_id: str, compare_attempt_id: str | None) -> dict[str, Any]:
    step = set_active_step(studio, step_id)
    if compare_attempt_id:
        compare = next((item for item in studio.get("attempts", []) if item.get("attempt_id") == compare_attempt_id and item.get("step_id") == step_id), None)
        if compare is None:
            raise KeyError(compare_attempt_id)
        step["compare_attempt_id"] = compare_attempt_id
    else:
        step["compare_attempt_id"] = None
    step["updated_at"] = now_iso()
    return step


def _attempt_output_assets(studio: dict[str, Any], attempt: dict[str, Any]) -> list[dict[str, Any]]:
    assets_by_id = {asset.get("asset_id"): asset for asset in studio.get("assets", []) if asset.get("asset_id")}
    return [assets_by_id[item] for item in attempt.get("output_asset_ids", []) if item in assets_by_id]


def mark_attempt_outputs_primary(studio: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    attempt = next(item for item in studio.get("attempts", []) if item.get("attempt_id") == attempt_id)
    outputs = _attempt_output_assets(studio, attempt)
    if not outputs:
        raise RuntimeError("这个尝试还没有输出文件，无法固定为主版本。")
    for asset in outputs:
        mark_asset_primary(studio, asset["asset_id"])
    select_attempt(studio, attempt_id)
    attempt["review_decision"] = "preferred"
    attempt["updated_at"] = now_iso()
    return attempt


def review_attempt(studio: dict[str, Any], attempt_id: str, *, decision: str, human_review: str, score: str | int | None = None, tags: str = "") -> dict[str, Any]:
    attempt = next(item for item in studio.get("attempts", []) if item.get("attempt_id") == attempt_id)
    attempt["review_decision"] = decision or attempt.get("review_decision") or "candidate"
    attempt["human_review"] = human_review.strip()
    cleaned_score: int | None
    try:
        cleaned_score = int(str(score).strip()) if score not in {None, ""} else None
    except Exception:
        cleaned_score = None
    if cleaned_score is not None:
        cleaned_score = max(0, min(100, cleaned_score))
    attempt["review_score"] = cleaned_score
    attempt["review_tags"] = [item.strip() for item in str(tags or "").split(",") if item.strip()]
    attempt["updated_at"] = now_iso()
    if attempt["review_decision"] == "preferred":
        select_attempt(studio, attempt_id)
    return attempt


def branch_step_from_attempt(studio: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    attempt = next(item for item in studio.get("attempts", []) if item.get("attempt_id") == attempt_id)
    step = set_active_step(studio, attempt["step_id"])
    step["prompt"] = attempt.get("prompt_snapshot") or attempt.get("prompt") or step.get("prompt") or ""
    step["operator_notes"] = "\n".join(part for part in [step.get("operator_notes") or "", f"已基于 {attempt_id} 回填 prompt，准备继续分叉调试。"] if part).strip()
    step["updated_at"] = now_iso()
    return step


def next_step_after(studio: dict[str, Any], step_id: str) -> dict[str, Any] | None:
    step = find_step(studio, step_id)
    module_steps = steps_for_module(studio, step.get("module_id") or step.get("line_id") or "paper")
    for index, item in enumerate(module_steps):
        if item.get("step_id") == step_id and index + 1 < len(module_steps):
            return module_steps[index + 1]
    return None


def complete_step_and_advance(studio: dict[str, Any], step_id: str) -> dict[str, Any] | None:
    step = find_step(studio, step_id)
    step["status"] = "done"
    step["updated_at"] = now_iso()
    nxt = next_step_after(studio, step_id)
    if nxt is not None:
        selected_attempt_id = step.get("selected_attempt_id")
        primary_output_ids: list[str] = []
        for asset in studio.get("assets", []):
            if asset.get("step_id") == step_id and asset.get("role") in {"output", "final"} and asset.get("is_primary"):
                primary_output_ids.append(str(asset.get("asset_id")))
        if not primary_output_ids and selected_attempt_id:
            attempt = next((item for item in studio.get("attempts", []) if item.get("attempt_id") == selected_attempt_id), None)
            if attempt is not None:
                primary_output_ids.extend([str(item) for item in attempt.get("output_asset_ids", []) if item])
        if not primary_output_ids:
            latest_outputs = [
                asset for asset in studio.get("assets", [])
                if asset.get("step_id") == step_id and asset.get("role") in {"output", "final"}
            ]
            if latest_outputs:
                primary_output_ids.append(str(latest_outputs[-1].get("asset_id")))
        existing_refs = {(item.get("asset_id"), item.get("role") or "reference") for item in nxt.get("references", [])}
        for asset_id in primary_output_ids[:3]:
            if (asset_id, "reference") not in existing_refs:
                link_existing_asset(studio, nxt["step_id"], asset_id, role="reference")
        if not str(nxt.get("prompt") or "").strip():
            nxt["prompt"] = (
                f"基于上一步“{step.get('title') or step_id}”的结果，继续完成当前步骤“{nxt.get('title') or nxt.get('step_id')}”。\n"
                "请先吸收已有结论，再输出当前步骤需要的内容。"
            )
        if not str(nxt.get("operator_notes") or "").strip():
            nxt["operator_notes"] = f"系统已把上一步“{step.get('title') or step_id}”的主输出挂到这里，可直接继续。"
        set_active_step(studio, nxt["step_id"])
        if nxt.get("status") in {"todo", "blocked"}:
            nxt["status"] = "active"
        nxt["updated_at"] = now_iso()
    return nxt


def attempt_output_text(root: str | Path, studio: dict[str, Any], attempt: dict[str, Any], limit: int = 12000) -> str:
    assets = _attempt_output_assets(studio, attempt)
    if not assets:
        return ""
    return asset_text_preview(root, assets[0], limit=limit)


def attempt_comparison(studio: dict[str, Any], root: str | Path, step_id: str) -> dict[str, Any] | None:
    step = find_step(studio, step_id)
    selected_id = step.get("selected_attempt_id")
    compare_id = step.get("compare_attempt_id")
    if not selected_id or not compare_id or selected_id == compare_id:
        return None
    attempts = {item.get("attempt_id"): item for item in studio.get("attempts", []) if item.get("step_id") == step_id}
    base = attempts.get(selected_id)
    compare = attempts.get(compare_id)
    if base is None or compare is None:
        return None

    def _diff_block(left: str, right: str, *, context: int = 2, limit: int = 220) -> str:
        diff_lines = list(difflib.unified_diff(
            (left or "").splitlines(),
            (right or "").splitlines(),
            fromfile=base.get("attempt_id") or "selected",
            tofile=compare.get("attempt_id") or "compare",
            lineterm="",
            n=context,
        ))
        if len(diff_lines) > limit:
            diff_lines = diff_lines[:limit] + ["... diff truncated ..."]
        return "\n".join(diff_lines) if diff_lines else "（没有差异）"

    base_prompt = base.get("prompt_snapshot") or base.get("prompt") or ""
    compare_prompt = compare.get("prompt_snapshot") or compare.get("prompt") or ""
    base_output = attempt_output_text(root, studio, base)
    compare_output = attempt_output_text(root, studio, compare)
    return {
        "base": base,
        "compare": compare,
        "prompt_diff": _diff_block(base_prompt, compare_prompt),
        "output_diff": _diff_block(base_output, compare_output),
        "base_output": base_output,
        "compare_output": compare_output,
    }


# ---------------------------------------------------------------------------
# Packages / handoff
# ---------------------------------------------------------------------------


def package_default_asset_ids(studio: dict[str, Any], step_id: str, include: str) -> list[str]:
    step_assets = assets_for_step(studio, step_id)
    if include == "primary_outputs":
        chosen = [asset["asset_id"] for asset in step_assets if asset.get("owned_by_step") and asset.get("role") in {"output", "final"} and asset.get("is_primary")]
        if chosen:
            return chosen
        fallback = [asset["asset_id"] for asset in step_assets if asset.get("owned_by_step") and asset.get("role") in {"output", "final"}]
        return fallback[-2:]
    if include == "inputs_and_primary":
        chosen = [asset["asset_id"] for asset in step_assets if asset.get("role") in {"input", "reference"}]
        chosen += [asset["asset_id"] for asset in step_assets if asset.get("owned_by_step") and asset.get("role") in {"output", "final"} and asset.get("is_primary")]
        return list(dict.fromkeys(chosen))
    return [asset["asset_id"] for asset in step_assets]


def create_handoff_package(
    root: str | Path,
    studio: dict[str, Any],
    project: dict[str, Any],
    step_id: str,
    *,
    include: str,
    target_label: str,
    target_step_label: str,
    mode: str,
    prompt_override: str = "",
    notes: str = "",
) -> dict[str, Any]:
    step = find_step(studio, step_id)
    package_id = _next_id(studio, "package", "PKG")
    handoff_id = _next_id(studio, "handoff", "HF")
    asset_ids = package_default_asset_ids(studio, step_id, include)
    package_root = Path(root).resolve() / "library" / "handoff_packages" / package_id
    files_dir = ensure_dir(package_root / "files")
    selected_assets = [asset for asset in studio.get("assets", []) if asset.get("asset_id") in asset_ids]
    copied: list[dict[str, Any]] = []
    for asset in selected_assets:
        src = resolve_within_root(root, asset["local_path"])
        if src.exists():
            dst = files_dir / Path(asset["local_path"]).name
            shutil.copy2(src, dst)
            copied.append(
                {
                    "asset_id": asset["asset_id"],
                    "name": asset.get("filename") or asset.get("name"),
                    "relative_path": f"files/{dst.name}",
                    "role": asset.get("role"),
                }
            )
    prompt_text = prompt_override.strip() or step.get("prompt") or step.get("goal") or ""
    manifest = {
        "package_id": package_id,
        "handoff_id": handoff_id,
        "source_step_id": step_id,
        "source_module_id": step.get("module_id") or step.get("line_id") or "paper",
        "target_label": target_label,
        "target_step_label": target_step_label,
        "mode": mode,
        "brief": studio.get("brief") or project.get("current_goal") or "",
        "goal": step.get("goal") or "",
        "prompt": prompt_text,
        "output_expectation": step.get("output_expectation") or "",
        "notes": notes,
        "assets": copied,
        "created_at": now_iso(),
    }
    save_json(package_root / "manifest.json", manifest)
    write_text(package_root / "prompt.md", "# Prompt to next AI\n\n" + prompt_text + "\n")
    readme = [
        f"# {package_id}",
        "",
        f"来源步骤：{step['title']}",
        f"目标 AI / 会话：{target_label}",
        f"目标步骤：{target_step_label}",
        f"模式：{mode}",
        "",
        "## 使用方式",
        "",
        "1. 打开 `prompt.md` 复制提示词",
        "2. 将 `files/` 里的文件上传到目标 AI / 会话",
        "3. 让对方按提示词生成结果",
        "4. 回到平台，把结果重新上传到对应步骤的输出箱",
    ]
    write_text(package_root / "README.md", "\n".join(readme) + "\n")
    zip_path = Path(root) / "library" / "handoff_packages" / f"{package_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in package_root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(package_root.parent))
    package = {
        "package_id": package_id,
        "handoff_id": handoff_id,
        "step_id": step_id,
        "source_step_id": step_id,
        "module_id": step.get("module_id") or step.get("line_id") or "paper",
        "line_id": step.get("module_id") or step.get("line_id") or "paper",
        "mode": mode,
        "target_label": target_label,
        "target_step_label": target_step_label,
        "asset_ids": asset_ids,
        "prompt": prompt_text,
        "notes": notes,
        "folder_path": str(package_root.relative_to(Path(root))),
        "manifest_path": str((package_root / "manifest.json").relative_to(Path(root))),
        "zip_path": str(zip_path.relative_to(Path(root))),
        "status": "prepared",
        "created_at": now_iso(),
    }
    handoff = {
        "handoff_id": handoff_id,
        "package_id": package_id,
        "from_step_id": step_id,
        "from_attempt_id": step.get("selected_attempt_id"),
        "to_provider": target_label,
        "to_label": target_label,
        "to_step_id": None,
        "to_step_label": target_step_label,
        "mode": mode,
        "status": "prepared",
        "created_at": now_iso(),
        "result_asset_ids": [],
        "notes": notes,
    }
    studio.setdefault("packages", []).append(package)
    studio.setdefault("handoffs", []).append(handoff)
    return package


def link_uploaded_result_to_latest_handoff(studio: dict[str, Any], step_id: str, asset_id: str) -> None:
    for handoff in reversed(studio.get("handoffs", [])):
        if handoff.get("from_step_id") == step_id and handoff.get("status") == "prepared":
            handoff.setdefault("result_asset_ids", []).append(asset_id)
            handoff["status"] = "returned"
            return


# ---------------------------------------------------------------------------
# Summaries / previews
# ---------------------------------------------------------------------------


def step_context_text(studio: dict[str, Any], project: dict[str, Any], step_id: str, root: str | Path | None = None) -> str:
    step = find_step(studio, step_id)
    module = next(item for item in studio.get("modules", []) if (item.get("module_id") or item.get("line_id")) == (step.get("module_id") or step.get("line_id")))
    parts = [
        f"当前工作线：{module['title']}",
        f"当前步骤：{step['title']}",
        f"项目总目标：{studio.get('brief') or project.get('current_goal') or ''}",
        f"这一步要做什么：{step.get('goal') or ''}",
        f"当前提示词：{step.get('prompt') or ''}",
        f"期望输出：{step.get('output_expectation') or ''}",
        f"执行模式：{step.get('provider_mode') or 'mock'} / {step.get('provider_name') or 'mock'} / {step.get('model_hint') or '-'}",
        f"建议输出目录：{step.get('folder_hint') or '-'}",
    ]
    if step.get("operator_notes"):
        parts.append(f"人工备注：{step['operator_notes']}")
    if root is not None:
        assets = assets_for_step(studio, step_id)
        if assets:
            parts.append("本步文件：")
            for asset in assets:
                role = asset.get("context_role") or asset.get("role")
                parts.append(f"- {asset['asset_id']} | {role} | {asset['local_path']}")
    return "\n".join(parts)


def write_active_context(root: str | Path, studio: dict[str, Any], project: dict[str, Any], step_id: str) -> str:
    text = "# Current Step Context\n\n" + step_context_text(studio, project, step_id, root) + "\n"
    rel = Path("control") / "active_context" / "CURRENT_STEP.md"
    write_text(Path(root) / rel, text)
    return str(rel)


def summarize_tree(studio: dict[str, Any]) -> dict[str, Any]:
    modules_out = []
    counted_total = 0
    counted_done = 0
    for module in studio.get("modules", []):
        module_id = module.get("module_id") or module.get("line_id")
        module_steps = steps_for_module(studio, module_id)
        module_done = sum(1 for step in module_steps if step.get("status") == "done")
        if module_id != "control":
            counted_total += len(module_steps)
            counted_done += module_done
        active = active_step(studio, module_id)
        modules_out.append(
            {
                **module,
                "steps": module_steps,
                "done_count": module_done,
                "total_steps": len(module_steps),
                "progress_pct": int((module_done / len(module_steps)) * 100) if module_steps else 0,
                "active_step": active,
                "review_count": sum(1 for step in module_steps if step.get("status") == "review"),
                "blocked_count": sum(1 for step in module_steps if step.get("status") == "blocked"),
            }
        )
    all_blocked = [step for step in studio.get("steps", []) if step.get("status") == "blocked"]
    all_review = [step for step in studio.get("steps", []) if step.get("status") == "review"]
    primary_assets = [asset for asset in studio.get("assets", []) if asset.get("is_primary")]
    bucket_counts = {bucket: 0 for bucket in LIBRARY_BUCKETS}
    for asset in studio.get("assets", []):
        bucket = asset.get("library_bucket") or module_library_bucket(asset.get("module_id") or "paper")
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    master_assets_by_module: dict[str, list[dict[str, Any]]] = {module_id: [] for module_id in MODULE_ORDER}
    for asset in primary_assets:
        module_id = asset.get("module_id") or asset.get("line_id") or "paper"
        master_assets_by_module.setdefault(module_id, []).append(asset)
    unreferenced_assets = [asset for asset in studio.get("assets", []) if len(asset.get("referenced_by", [])) <= 1 and not asset.get("is_primary")]
    return {
        "brief": studio.get("brief") or "",
        "lines": modules_out,
        "modules": modules_out,
        "overall_progress_pct": int((counted_done / counted_total) * 100) if counted_total else 0,
        "active_step": active_step(studio),
        "active_module_id": studio.get("active_module_id") or "paper",
        "control": studio.get("control", {}),
        "package_count": len(studio.get("packages", [])),
        "handoff_count": len(studio.get("handoffs", [])),
        "asset_count": len(studio.get("assets", [])),
        "template_count": len(studio.get("prompt_templates", [])) + len(_load_global_prompt_templates().get("templates", [])),
        "provider_count": len(studio.get("provider_profiles", [])),
        "blocked_steps": all_blocked,
        "review_steps": all_review,
        "primary_assets": primary_assets,
        "bucket_counts": bucket_counts,
        "master_assets_by_module": master_assets_by_module,
        "unreferenced_assets": unreferenced_assets,
    }


def asset_text_preview(root: str | Path, asset: dict[str, Any], limit: int = 12000) -> str:
    path = resolve_within_root(root, asset["local_path"])
    if not path.exists():
        return "[Missing local file]"
    if path.suffix.lower() in TEXT_EXTS:
        data = path.read_text(encoding="utf-8", errors="ignore")
        return data[:limit]
    return f"[Binary file: {path.name} | {asset.get('mime_type')}]"


def make_download_filename(name: str) -> str:
    return Path(name).name.replace("\n", "_").replace("\r", "_")
