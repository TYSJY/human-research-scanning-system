from __future__ import annotations

import base64
import html
import json
import re
from typing import Any
from urllib.parse import urlencode

from .common import resolve_within_root
from .studio import (
    MODULE_SPECS,
    PROMPT_TEMPLATE_VARIABLES,
    all_assets,
    attempt_comparison,
    asset_reference_summary,
    asset_text_preview,
    assets_for_step,
    attempts_for_step,
    find_provider_profile,
    find_step,
    list_available_prompt_templates,
    next_step_after,
    normalize_studio,
    provider_profiles,
    status_label,
    status_tone,
    steps_for_module,
    summarize_tree,
)
from .workspace import WorkspaceSnapshot

STATE_KEYS = ["project", "tab", "mode", "run", "task", "artifact", "session", "note"]
MODULE_TABS = [
    ("paper", "写论文"),
    ("experiments", "做实验"),
    ("figures", "做图表"),
    ("control", "看总览"),
]
MODULE_LONG_LABELS = {
    "paper": "写论文 · A线",
    "experiments": "做实验 · B线",
    "figures": "做图表 · C线",
    "control": "看总览 · D线",
}
WEB_TARGETS = {
    "chatgpt": {"label": "ChatGPT", "full_label": "ChatGPT 网页", "url": "https://chatgpt.com", "profile_id": "chatgpt-web", "model_hint": "ChatGPT Web"},
    "gemini": {"label": "Gemini", "full_label": "Gemini 网页", "url": "https://gemini.google.com", "profile_id": "gemini-web", "model_hint": "Gemini Web"},
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _module_label(module_id: str, *, long: bool = False) -> str:
    for key, label in MODULE_TABS:
        if key == module_id:
            return MODULE_LONG_LABELS.get(module_id, label) if long else label
    return module_id


def _web_target_meta(web_target: str | None) -> dict[str, str]:
    key = str(web_target or "chatgpt").strip().lower()
    return WEB_TARGETS.get(key, WEB_TARGETS["chatgpt"])


def _hidden_copy_source(source_id: str, text: str) -> str:
    return f'<textarea id="{_escape(source_id)}" class="hidden-copy-source" readonly>{_escape(text)}</textarea>'


def _state_fields(state: dict[str, str | None], project_dir: str, extra: dict[str, str | None] | None = None) -> str:
    fields = []
    for key in STATE_KEYS:
        value = state.get(key)
        if key == "project":
            value = project_dir
        if value:
            field_name = "project" if key == "project" else key
            fields.append(f'<input type="hidden" name="{_escape(field_name)}" value="{_escape(value)}">')
    fields.append(f'<input type="hidden" name="project_dir" value="{_escape(project_dir)}">')
    for key, value in (extra or {}).items():
        if value is None:
            continue
        fields.append(f'<input type="hidden" name="{_escape(key)}" value="{_escape(value)}">')
    return "".join(fields)


def _button(
    label: str,
    action: str,
    state: dict[str, str | None],
    project_dir: str,
    extra: dict[str, str | None] | None = None,
    *,
    button_class: str = "",
    confirm_text: str | None = None,
) -> str:
    fields = [f'<input type="hidden" name="action" value="{_escape(action)}">', _state_fields(state, project_dir, extra)]
    cls = f' class="{button_class}"' if button_class else ""
    onclick = f' onclick="return confirm({_escape(repr(confirm_text))})"' if confirm_text else ""
    return f'<form method="post" action="/action" class="inline-form">{"".join(fields)}<button{cls}{onclick}>{_escape(label)}</button></form>'


def _build_url(state: dict[str, str | None], **updates: str | None) -> str:
    params: dict[str, str] = {}
    for key in STATE_KEYS:
        value = updates[key] if key in updates else state.get(key)
        if value:
            params[key] = str(value)
    encoded = urlencode(params)
    return f"/?{encoded}" if encoded else "/"


def _badge(label: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{_escape(label)}</span>'


def _file_chip(label: str, tone: str = "neutral") -> str:
    return f'<span class="file-chip {tone}">{_escape(label)}</span>'


def _textarea(name: str, value: str, placeholder: str = "", rows: int = 4) -> str:
    return f'<textarea name="{_escape(name)}" rows="{rows}" placeholder="{_escape(placeholder)}">{_escape(value)}</textarea>'


def _time_label(value: str | None) -> str:
    text = str(value or '').strip()
    if not text:
        return '未记录'
    return text.replace('T', ' ')[:16]


def _quick_stats(items: list[tuple[str, str]]) -> str:
    return '<div class="quick-stats">' + ''.join(
        f'<div class="stat-pill"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
        for label, value in items
    ) + '</div>'


def _details_card(title: str, body: str, *, subtitle: str = '', badge_html: str = '', open: bool = False) -> str:
    subtitle_html = f'<div class="card-subtitle">{_escape(subtitle)}</div>' if subtitle else ''
    open_attr = ' open' if open else ''
    return f"""
    <details class="card details-card"{open_attr}>
      <summary>
        <div class="line-card-head">
          <div>
            <h2>{_escape(title)}</h2>
            {subtitle_html}
          </div>
          <div class="summary-meta">{badge_html}</div>
        </div>
      </summary>
      <div class="details-card-body">{body}</div>
    </details>
    """




def _activity_row(item: dict[str, Any]) -> str:
    tone = str(item.get("tone") or "neutral")
    kind = str(item.get("kind") or "动作")
    detail = str(item.get("detail") or "")
    return f'''
    <div class="activity-item">
      <div class="activity-dot {tone}"></div>
      <div class="activity-copy">
        <div class="activity-top"><strong>{_escape(item.get("title") or kind)}</strong>{_badge(kind, tone)}</div>
        <div class="row-sub">{_escape(detail or "项目状态已更新。")}</div>
        <div class="activity-time">{_escape(_time_label(item.get("at")))}</div>
      </div>
    </div>
    '''


def _collect_activity_items(
    studio: dict[str, Any],
    *,
    module_id: str | None = None,
    step_id: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    step_map = {item.get("step_id"): item for item in studio.get("steps", []) if item.get("step_id")}
    items: list[dict[str, Any]] = []

    def include_module(value: str | None) -> bool:
        if not module_id:
            return True
        return (value or "paper") == module_id

    def append_item(key: str, title: str, detail: str, at: str | None, *, kind: str, tone: str = "neutral") -> None:
        items.append({
            "key": key,
            "title": title,
            "detail": detail,
            "at": str(at or ""),
            "kind": kind,
            "tone": tone,
        })

    for step in studio.get("steps", []):
        module_key = step.get("module_id") or step.get("line_id") or "paper"
        if not include_module(module_key):
            continue
        if step_id and step.get("step_id") != step_id:
            continue
        append_item(
            f"step:{step.get('step_id')}",
            _clean_step_title(step.get("title")),
            f"步骤状态：{status_label(step.get('status') or 'todo')}",
            step.get("updated_at") or step.get("created_at"),
            kind="步骤",
            tone=status_tone(step.get("status") or "todo"),
        )

    for attempt in studio.get("attempts", []):
        step = step_map.get(attempt.get("step_id"))
        module_key = (step or {}).get("module_id") or (step or {}).get("line_id") or attempt.get("module_id") or attempt.get("line_id") or "paper"
        if not include_module(module_key):
            continue
        if step_id and attempt.get("step_id") != step_id:
            continue
        decision = attempt.get("review_decision") or "candidate"
        append_item(
            f"attempt:{attempt.get('attempt_id')}",
            f"新版本 {attempt.get('attempt_id') or '-'}",
            f"{_clean_step_title((step or {}).get('title'))} · {_provider_mode_label(attempt.get('provider_mode'))}",
            attempt.get("updated_at") or attempt.get("created_at"),
            kind="版本",
            tone="ok" if decision == "preferred" else "neutral",
        )

    for asset in studio.get("assets", []):
        module_key = asset.get("module_id") or asset.get("line_id") or "paper"
        if not include_module(module_key):
            continue
        if step_id and asset.get("step_id") != step_id and not any(ref.get("step_id") == step_id for ref in asset.get("referenced_by", [])):
            continue
        role = asset.get("context_role") or asset.get("role") or "output"
        append_item(
            f"asset:{asset.get('asset_id')}",
            asset.get("filename") or asset.get("name") or asset.get("asset_id") or "文件",
            f"{role} · {asset.get('library_bucket') or module_key}",
            asset.get("created_at"),
            kind="文件",
            tone="ok" if asset.get("is_primary") else "info",
        )

    for package in studio.get("packages", []):
        package_step_id = package.get("source_step_id") or package.get("step_id")
        step = step_map.get(package_step_id)
        module_key = (step or {}).get("module_id") or (step or {}).get("line_id") or "paper"
        if not include_module(module_key):
            continue
        if step_id and package_step_id != step_id:
            continue
        append_item(
            f"package:{package.get('package_id')}",
            "已生成交接包",
            f"{package.get('target_label') or package.get('mode') or '网页协同'} · {_clean_step_title((step or {}).get('title'))}",
            package.get("created_at"),
            kind="交接",
            tone="info",
        )

    for handoff in studio.get("handoffs", []):
        handoff_step_id = handoff.get("from_step_id") or handoff.get("to_step_id")
        step = step_map.get(handoff_step_id)
        module_key = (step or {}).get("module_id") or (step or {}).get("line_id") or "paper"
        if not include_module(module_key):
            continue
        if step_id and handoff_step_id != step_id:
            continue
        append_item(
            f"handoff:{handoff.get('handoff_id')}",
            "网页结果回填",
            f"{handoff.get('to_provider') or handoff.get('to_label') or 'manual_web'} · {handoff.get('status') or 'prepared'}",
            handoff.get("created_at"),
            kind="回填",
            tone="info",
        )

    control = studio.get("control", {}) or {}
    if (not module_id or module_id == "control") and control.get("last_control_update_at"):
        append_item(
            "control:update",
            "项目总控已更新",
            control.get("next_milestone") or control.get("program_goal") or "概览已更新",
            control.get("last_control_update_at"),
            kind="总控",
            tone="info",
        )

    items.sort(key=lambda item: (item.get("at") or "", item.get("key") or ""), reverse=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("key") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break

    if step_id and len(result) < min(limit, 4):
        fallback = _collect_activity_items(studio, module_id=module_id, step_id=None, limit=limit)
        existing = {str(item.get("key") or "") for item in result}
        for item in fallback:
            key = str(item.get("key") or "")
            if key in existing:
                continue
            existing.add(key)
            result.append(item)
            if len(result) >= limit:
                break
    return result[:limit]


def _render_activity_feed(title: str, items: list[dict[str, Any]], *, card_id: str = '', subtitle: str = '') -> str:
    rows = ''.join(_activity_row(item) for item in items) or '<div class="empty">最近还没有动作。</div>'
    subtitle_html = f'<div class="helper-text compact-copy">{_escape(subtitle)}</div>' if subtitle else ''
    badge_html = _badge(f'{len(items)} 条', 'info' if items else 'neutral')
    card_attr = f' id="{_escape(card_id)}"' if card_id else ''
    return f'''
    <section class="card compact-card"{card_attr}>
      <div class="line-card-head"><h2>{_escape(title)}</h2><div class="chip-row">{badge_html}</div></div>
      {subtitle_html}
      <div class="activity-feed">{rows}</div>
    </section>
    '''


def _priority_tile(title: str, detail: str, action_html: str, *, tone: str = 'neutral', badge_label: str = '现在做') -> str:
    return f'''
    <div class="priority-card {tone}">
      <div class="priority-head">
        <div>
          <div class="priority-eyebrow">{_escape(badge_label)}</div>
          <h3>{_escape(title)}</h3>
        </div>
        <div>{_badge(badge_label, tone)}</div>
      </div>
      <div class="row-sub">{_escape(detail)}</div>
      <div class="action-row wrap">{action_html}</div>
    </div>
    '''


def _render_priority_actions(
    project_dir: str,
    state: dict[str, str | None],
    module_id: str,
    step: dict[str, Any],
    output_assets: list[dict[str, Any]],
    selected_attempt: dict[str, Any] | None,
    advance_button: str,
) -> str:
    input_ready = all(str(step.get(field) or '').strip() for field in ['goal', 'prompt', 'output_expectation'])
    if input_ready:
        input_tile = _priority_tile(
            '任务已经写清楚',
            '目标、Prompt、输出要求都已经填好。',
            '<a class="button ghost" href="#current-task">查看当前任务</a>',
            tone='ok',
            badge_label='第 1 步',
        )
    else:
        missing = [label for field, label in [('goal', '目标'), ('prompt', 'Prompt'), ('output_expectation', '输出要求')] if not str(step.get(field) or '').strip()]
        input_tile = _priority_tile(
            '先把这一步说清楚',
            f"还缺：{' / '.join(missing) if missing else '任务说明'}。",
            '<a class="button secondary" href="#current-task">去补任务</a>',
            tone='warn',
            badge_label='第 1 步',
        )

    mode = step.get('provider_mode')
    if selected_attempt or output_assets:
        run_tile = _priority_tile(
            '结果已经出来了',
            '现在可以直接看主输出，或者回头比较历史结果。',
            '<a class="button ghost" href="#main-output">看主输出</a><a class="button ghost" href="#version-history">看历史结果</a>',
            tone='ok',
            badge_label='第 2 步',
        )
    elif mode == 'manual_web':
        web_meta = _web_target_meta(step.get('web_target'))
        copy_id = f"prompt-pack-{step['step_id']}"
        run_tile = _priority_tile(
            f"去 {web_meta['label']} 生成结果",
            '复制 Prompt，上传右侧文件，然后把结果导回这里。',
            f'<button type="button" class="button secondary copy-trigger" data-copy-target="{_escape(copy_id)}" data-copied-label="已复制 Prompt">复制 Prompt</button><a class="button primary" target="_blank" rel="noreferrer" href="{_escape(web_meta["url"])}">打开 {_escape(web_meta["label"])} </a>',
            tone='info',
            badge_label='第 2 步',
        )
    elif mode == 'openai_api':
        run_tile = _priority_tile(
            '开始生成',
            '平台内直接留版本，适合已经配好 API 的人。',
            _button('开始生成', 'run_openai_step', state, project_dir, {'tab': module_id, 'task': step['step_id']}, button_class='primary'),
            tone='info',
            badge_label='第 2 步',
        )
    else:
        run_tile = _priority_tile(
            '先演练一下',
            '只检查 Prompt 和步骤流，不是正式结果。',
            _button('演练一下', 'run_mock_step', state, project_dir, {'tab': module_id, 'task': step['step_id']}, button_class='primary'),
            tone='info',
            badge_label='第 2 步',
        )

    primary_ready = any(asset.get('is_primary') for asset in output_assets)
    pin_action = ''
    if selected_attempt and selected_attempt.get('output_asset_ids'):
        pin_action = _button(
            '把当前结果定为主输出',
            'mark_attempt_outputs_primary',
            state,
            project_dir,
            {'tab': module_id, 'task': step['step_id'], 'attempt_id': selected_attempt['attempt_id']},
            button_class='secondary',
        )
    if primary_ready:
        finish_detail = '主输出已经锁定，可以继续推进下一步。'
        finish_tone = 'ok'
    elif selected_attempt and selected_attempt.get('output_asset_ids'):
        finish_detail = '先把当前结果固定为主输出，再继续下一步。'
        finish_tone = 'warn'
    else:
        finish_detail = '先拿到结果，再把最好的一版定为主输出。'
        finish_tone = 'neutral'
    finish_actions = pin_action + advance_button if (pin_action or advance_button) else '<a class="button ghost" href="#main-output">去看结果</a>'
    finish_tile = _priority_tile(
        '确认结果并继续',
        finish_detail,
        finish_actions,
        tone=finish_tone,
        badge_label='第 3 步',
    )

    return f'''
    <section class="card compact-card" id="priority-actions">
      <div class="line-card-head"><h2>现在只做这三件事</h2><div class="chip-row">{_badge(_clean_step_title(step.get('title')), 'info')}</div></div>
      <div class="priority-grid">{input_tile}{run_tile}{finish_tile}</div>
    </section>
    '''

def _asset_download_link(project_dir: str, asset: dict[str, Any], label: str | None = None) -> str:
    filename = Path(str(asset.get("filename") or asset.get("name") or asset["asset_id"])).name
    qs = urlencode({"project": project_dir, "asset": asset["asset_id"], "filename": filename})
    return f'<a class="inline-link" href="/download?{qs}">{_escape(label or asset.get("filename") or asset.get("name") or asset["asset_id"])}</a>'


def _package_download_link(project_dir: str, package: dict[str, Any]) -> str:
    filename = Path(str(package.get("zip_path") or package["package_id"])).name
    qs = urlencode({"project": project_dir, "package": package["package_id"], "filename": filename})
    return f'<a class="inline-link" href="/download?{qs}">{_escape(package["package_id"])}</a>'


def _module_links(project_dir: str, state: dict[str, str | None], active_tab: str) -> str:
    items = []
    for tab, label in MODULE_TABS:
        url = _build_url(state, project=project_dir, tab=tab, run=None, artifact=None, session=None, note=None)
        active = " active-tab" if active_tab == tab else ""
        items.append(f'<a class="tab{active}" href="{_escape(url)}">{_escape(label)}</a>')
    return '<nav class="tabs module-tabs">' + "".join(items) + '</nav>'


def _template_options(studio: dict[str, Any], step_id: str) -> str:
    groups: dict[str, list[str]] = {
        "最近使用": [],
        "系统默认": [],
        "当前模块模板": [],
        "当前项目模板": [],
        "全局个人模板": [],
    }
    for item in list_available_prompt_templates(studio, step_id):
        label = item.get("name") or item.get("template_id") or "未命名模板"
        scope = item.get("scope") or "project"
        desc_parts = []
        if item.get("module_id"):
            desc_parts.append(item["module_id"])
        if item.get("step_id"):
            desc_parts.append(item["step_id"])
        text = label + (f" · {' / '.join(desc_parts)}" if desc_parts else "")
        option = f'<option value="{_escape(item["usage_key"])}">{_escape(text)}</option>'
        if item.get("usage_key") in (studio.get("recent_template_keys") or []):
            groups["最近使用"].append(option)
        elif scope in {"system_default", "step_default"}:
            groups["系统默认"].append(option)
        elif scope == "module_default":
            groups["当前模块模板"].append(option)
        elif item.get("origin") == "global" or scope == "global_personal":
            groups["全局个人模板"].append(option)
        else:
            groups["当前项目模板"].append(option)
    html_groups = []
    for title, options in groups.items():
        if options:
            html_groups.append(f'<optgroup label="{_escape(title)}">{"".join(options)}</optgroup>')
    return "".join(html_groups) or '<option value="">当前还没有可用模板</option>'


def _provider_options(studio: dict[str, Any], selected: str | None) -> str:
    options = ['<option value="">不使用 profile（手填 provider/model）</option>']
    for profile in provider_profiles(studio):
        label = profile.get("name") or profile.get("profile_id") or "未命名 provider"
        provider = profile.get("provider") or "openai"
        model = profile.get("default_model") or "-"
        option = f'<option value="{_escape(profile["profile_id"])}"{" selected" if profile.get("profile_id") == selected else ""}>{_escape(label)} · {provider} · {model}</option>'
        options.append(option)
    return "".join(options)


def _template_variable_help() -> str:
    chips = [f'<span class="badge neutral">{{{{{_escape(key)}}}}} · {_escape(desc)}</span>' for key, desc in PROMPT_TEMPLATE_VARIABLES.items()]
    return '<div class="chip-row">' + ''.join(chips) + '</div>'


def _attempt_decision_badge(attempt: dict[str, Any]) -> str:
    decision = attempt.get("review_decision") or "candidate"
    mapping = {
        "candidate": ("候选", "neutral"),
        "preferred": ("优选", "ok"),
        "discarded": ("废弃", "bad"),
    }
    label, tone = mapping.get(decision, (decision, "neutral"))
    return _badge(label, tone)


def _provider_mode_label(mode: str | None) -> str:
    mapping = {
        "mock": "演练",
        "openai_api": "API",
        "manual_web": "网页协同",
    }
    key = str(mode or "mock")
    return mapping.get(key, key)



def _step_entry_label(step: dict[str, Any]) -> str:
    mode = step.get('provider_mode')
    if mode == 'manual_web':
        return 'Gemini' if (step.get('web_target') or 'chatgpt') == 'gemini' else 'ChatGPT'
    if mode == 'openai_api':
        return 'API'
    return '演练'


def _clean_step_title(title: str | None) -> str:
    raw = str(title or '').strip()
    if not raw:
        return '未命名步骤'
    return re.sub(r'^\s*\d+\s*[.、)）-]?\s*', '', raw).strip() or raw


def _compact_step_title(title: str | None) -> str:
    text = _clean_step_title(title)
    lowered = text.lower()
    keyword_rules = [
        ('预投稿', '预投稿'),
        ('严谨', '严谨稿'),
        ('整改', '整改'),
        ('调研', '调研整改'),
        ('初稿', '初稿'),
        ('idea', 'idea'),
        ('提示词', '提示词'),
        ('图片', '图片'),
        ('代码', '代码'),
        ('实验', '实验'),
        ('结果', '结果'),
        ('论文', '论文'),
    ]
    for needle, label in keyword_rules:
        if needle in text or needle in lowered:
            return label
    for marker in ['生成', '产出', '整理', '完成']:
        if marker in text:
            tail = text.split(marker)[-1].strip()
            if tail:
                return tail[:8] + ('…' if len(tail) > 8 else '')
    return text[:8] + ('…' if len(text) > 8 else '')


def _render_step_flow(
    project_dir: str,
    state: dict[str, str | None],
    module: dict[str, Any],
    step: dict[str, Any],
    next_step: dict[str, Any] | None,
    input_assets: list[dict[str, Any]],
    output_assets: list[dict[str, Any]],
    attempt_count: int,
) -> str:
    steps = module.get('steps', [])
    current_index = next((idx for idx, item in enumerate(steps) if item.get('step_id') == step.get('step_id')), 0)
    prev_step = steps[current_index - 1] if current_index > 0 else None
    rail_nodes: list[str] = []
    for index, item in enumerate(steps, start=1):
        if item.get('step_id') == step.get('step_id'):
            tone = 'current'
        elif (item.get('status') or '') == 'done' or index - 1 < current_index:
            tone = 'done'
        else:
            tone = 'upcoming'
        url = _build_url(state, project=project_dir, tab=module.get('module_id'), task=item.get('step_id'), run=None, artifact=None, session=None, note=None)
        rail_nodes.append(
            f'<a class="rail-step {tone}" href="{_escape(url)}" title="{_escape(_clean_step_title(item.get("title")))}"><span class="rail-index">{index}</span></a>'
        )
    summary_badges = ''.join([
        _badge(f'已完成 {module.get("done_count", 0)}/{module.get("total_steps", 0)}', 'info'),
        _badge(f'尝试 {attempt_count}', 'neutral'),
        _badge(f'输入 {len(input_assets)}', 'neutral'),
        _badge(f'输出 {len(output_assets)}', 'neutral'),
    ])
    prev_label = _clean_step_title(prev_step.get('title')) if prev_step else '无'
    current_label = _clean_step_title(step.get('title'))
    next_label = _clean_step_title(next_step.get('title')) if next_step else '本线收尾'
    return f'''
    <section class="card compact-card workflow-card">
      <div class="line-card-head">
        <h2>步骤推进</h2>
        <div class="chip-row">{summary_badges}</div>
      </div>
      <div class="step-rail">{''.join(rail_nodes)}</div>
      <div class="focus-lane">
        <div class="focus-node">
          <span>上一步</span>
          <strong>{_escape(_compact_step_title(prev_label))}</strong>
        </div>
        <div class="focus-node current">
          <span>现在</span>
          <strong>{_escape(_compact_step_title(current_label))}</strong>
        </div>
        <div class="focus-node">
          <span>下一步</span>
          <strong>{_escape(_compact_step_title(next_label))}</strong>
        </div>
      </div>
    </section>
    '''


def _render_beginner_guide(step: dict[str, Any], next_step: dict[str, Any] | None) -> str:
    next_label = _clean_step_title(next_step.get('title')) if next_step else '继续把这一线收尾'
    return f'''
    <section class="card compact-card novice-only">
      <div class="line-card-head"><h2>第一次用就按这个顺序来</h2><div class="chip-row">{_badge('给普通用户', 'info')}</div></div>
      <div class="home-start-grid">
        <div class="start-card"><div class="start-index">1</div><div class="start-title">先写清楚当前任务</div><p>只填目标、输出要求和 Prompt 就够了。</p></div>
        <div class="start-card"><div class="start-index">2</div><div class="start-title">再选一种开始方式</div><p>推荐直接用 ChatGPT；也可以换 Gemini。</p></div>
        <div class="start-card"><div class="start-index">3</div><div class="start-title">看结果并继续</div><p>把最好的一版定为主输出，然后进入：{_escape(next_label)}。</p></div>
      </div>
    </section>
    '''


def _asset_preview_fragment(project_dir: str, asset: dict[str, Any]) -> str:
    try:
        path = resolve_within_root(project_dir, str(asset.get("local_path") or ""))
    except Exception:
        return '<div class="helper-text">文件路径无效。</div>'
    if not path.exists():
        return '<div class="helper-text">本地文件不存在。</div>'
    mime = str(asset.get("mime_type") or "")
    if mime.startswith("image/") and path.stat().st_size <= 900_000:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'<img class="asset-preview-image" src="data:{_escape(mime)};base64,{encoded}" alt="{_escape(asset.get("filename") or asset.get("name") or asset.get("asset_id") or "preview")}">'
    preview = asset_text_preview(project_dir, asset, limit=1800)
    return f'<div class="markdown-preview compact-preview">{_escape(preview)}</div>'



def _render_step_tree(project_dir: str, summary: dict[str, Any], state: dict[str, str | None], module_id: str) -> str:
    module = next((item for item in summary["modules"] if item["module_id"] == module_id), None)
    if module is None:
        return '<section class="card tree-card"><h2>步骤</h2><div class="empty">当前模块不存在。</div></section>'
    step_items: list[str] = []
    active_id = state.get('task') or (module.get('active_step') or {}).get('step_id') or (summary.get('active_step') or {}).get('step_id')
    current_step = next((item for item in module['steps'] if item.get('step_id') == active_id), None)
    for step in module['steps']:
        is_active = step.get('step_id') == active_id
        indent_cls = ' is-child' if int(step.get('level', 0) or 0) > 0 else ''
        active_cls = ' active-step-row' if is_active else ''
        url = _build_url(state, project=project_dir, tab=module_id, task=step.get('step_id'), run=None, artifact=None, session=None, note=None)
        badge_html = _badge('当前', 'info') if is_active else _badge(status_label(step.get('status') or 'todo'), status_tone(step.get('status') or 'todo'))
        step_items.append(
            f"""
            <a class="step-tree-row-link" href="{_escape(url)}">
              <div class="step-tree-row{active_cls}{indent_cls}">
                <div class="step-tree-index">{_escape(step.get('order_index') or '?')}</div>
                <div class="step-tree-main">
                  <div class="step-tree-title">{_escape(_compact_step_title(step.get('title')))}</div>
                </div>
                <div class="step-tree-side">{badge_html}</div>
              </div>
            </a>
            """
        )
    current_ops = ''
    if current_step is not None:
        current_ops_body = f"""
        <div class="action-row wrap">
          {_button('上移', 'move_step_up', state, project_dir, {'tab': module_id, 'task': current_step['step_id']}, button_class='ghost')}
          {_button('下移', 'move_step_down', state, project_dir, {'tab': module_id, 'task': current_step['step_id']}, button_class='ghost')}
          {_button('重开', 'reopen_step', state, project_dir, {'tab': module_id, 'task': current_step['step_id']}, button_class='ghost')}
          {_button('删除', 'delete_step', state, project_dir, {'tab': module_id, 'task': current_step['step_id']}, button_class='ghost', confirm_text='确认删除这个步骤及其子步骤？相关文件会保留在共享文件库。')}
        </div>
        """
        current_ops = _details_card(
            '流程调整',
            current_ops_body,
            badge_html=_badge(status_label(current_step.get('status') or 'todo'), status_tone(current_step.get('status') or 'todo')),
            open=False,
        )
    add_form = f"""
      <form method="post" action="/action" class="form-stack compact-card inset-form">
        {_state_fields(state, project_dir, {'tab': module_id, 'task': module.get('active_step', {}).get('step_id') or ''})}
        <input type="hidden" name="action" value="add_step">
        <input type="hidden" name="module_id" value="{_escape(module_id)}">
        <label>标题<input type="text" name="title" placeholder="加一步"></label>
        <label>目标{_textarea('goal', '', '这一步解决什么', 2)}</label>
        <button class="secondary">新增步骤</button>
      </form>
    """
    return f"""
    <section class="card tree-card">
      <div class="line-card-head">
        <h2>步骤</h2>
        {_badge(f'{module["done_count"]}/{module["total_steps"]}', 'info')}
      </div>
      <div class="step-tree">{"".join(step_items) or '<div class="empty">这个模块还没有步骤。</div>'}</div>
      <div class="pro-only">{current_ops}{_details_card('加一步', add_form.replace('<form ', '<form id="step-add" ', 1))}</div>
    </section>
    """

def _render_attempts(project_dir: str, studio: dict[str, Any], step: dict[str, Any], state: dict[str, str | None], module_id: str) -> str:
    attempts = attempts_for_step(studio, step["step_id"])
    if not attempts:
        return '<div class="empty">还没有版本记录。</div>'
    assets = {asset["asset_id"]: asset for asset in all_assets(studio)}
    cards: list[str] = []
    for attempt in attempts:
        selected = attempt["attempt_id"] == step.get("selected_attempt_id")
        output_assets = [assets[a] for a in attempt.get("output_asset_ids", []) if a in assets]
        preview = asset_text_preview(project_dir, output_assets[0], limit=1800) if output_assets else '暂无文本预览。'
        output_links = ''.join(f'<li>{_asset_download_link(project_dir, asset)}</li>' for asset in output_assets) or '<li>当前没有输出文件。</li>'
        score_badge = _badge(f"评分 {attempt.get('review_score')}", 'info') if attempt.get('review_score') is not None else ''
        tags_text = ', '.join(attempt.get('review_tags') or [])
        compare_action = '' if selected else _button('对比', 'compare_attempt', state, project_dir, {'tab': module_id, 'attempt_id': attempt['attempt_id'], 'task': step['step_id']}, button_class='ghost')
        summary_text = _escape(attempt.get('summary') or '')
        created_at = _escape(attempt.get('created_at') or '-')
        provider_line = f"{_escape(attempt.get('provider') or attempt.get('provider_name') or '-')} / {_escape(attempt.get('model') or attempt.get('model_hint') or '-')}"
        cards.append(
            f'''
            <details class="attempt-card"{' open' if selected else ''}>
              <summary>
                <div class="line-card-head">
                  <strong>{_escape(attempt['attempt_id'])}</strong>
                  <div>
                    {_badge('主输出', 'ok') if selected else ''}
                    {_attempt_decision_badge(attempt)}
                    {score_badge}
                    {_badge(_provider_mode_label(attempt.get('provider_mode')), 'info')}
                  </div>
                </div>
                <div class="project-meta">{provider_line} · {created_at}</div>
              </summary>
              <div class="attempt-body">
                {f'<div class="helper-text compact-copy">{summary_text}</div>' if summary_text else ''}
                <div class="markdown-preview compact-preview">{_escape(preview)}</div>
                <div class="action-row wrap">
                  {_button('选中这个结果', 'select_attempt', state, project_dir, {'tab': module_id, 'attempt_id': attempt['attempt_id'], 'task': step['step_id']}, button_class='secondary')}
                  {compare_action}
                  {_button('定为主输出', 'promote_attempt_outputs', state, project_dir, {'tab': module_id, 'attempt_id': attempt['attempt_id'], 'task': step['step_id']}, button_class='ghost')}
                  {_button('基于它再改', 'branch_from_attempt', state, project_dir, {'tab': module_id, 'attempt_id': attempt['attempt_id'], 'task': step['step_id']}, button_class='ghost')}
                </div>
                <details class="stack-item compact-inner">
                  <summary>人工判断</summary>
                  <form method="post" action="/action" class="form-stack compact-card inset-form">
                    {_state_fields(state, project_dir, {'tab': module_id, 'task': step['step_id'], 'attempt_id': attempt['attempt_id']})}
                    <input type="hidden" name="action" value="review_attempt">
                    <div class="two-col">
                      <label>判断
                        <select name="decision">
                          <option value="candidate" {'selected' if (attempt.get('review_decision') or 'candidate') == 'candidate' else ''}>候选</option>
                          <option value="preferred" {'selected' if attempt.get('review_decision') == 'preferred' else ''}>优选</option>
                          <option value="discarded" {'selected' if attempt.get('review_decision') == 'discarded' else ''}>废弃</option>
                        </select>
                      </label>
                      <label>评分<input type="text" name="review_score" value="{_escape(attempt.get('review_score') if attempt.get('review_score') is not None else '')}" placeholder="0-100"></label>
                    </div>
                    <label>标签<input type="text" name="review_tags" value="{_escape(tags_text)}" placeholder="逗号分隔"></label>
                    <label>备注{_textarea('human_review', attempt.get('human_review') or '', '为什么更好 / 更差', 3)}</label>
                    <button class="secondary">保存审阅</button>
                  </form>
                </details>
                <details class="stack-item compact-inner">
                  <summary>输出文件 · {len(output_assets)}</summary>
                  <ul class="guide-list compact">{output_links}</ul>
                </details>
                <details class="stack-item compact-inner">
                  <summary>当时用的 Prompt</summary>
                  <div class="markdown-preview">{_escape(attempt.get('prompt_snapshot') or attempt.get('prompt') or '')}</div>
                </details>
              </div>
            </details>
            '''
        )
    return ''.join(cards)

def _render_attempt_comparison(project_dir: str, studio: dict[str, Any], step: dict[str, Any], state: dict[str, str | None], module_id: str) -> str:
    payload = attempt_comparison(studio, project_dir, step['step_id'])
    if not payload:
        return ''
    base = payload['base']
    compare = payload['compare']
    return f'''
    <section class="card emphasis-card">
      <div class="line-card-head">
        <div>
          <h2>版本对比</h2>
          <div class="project-meta compact-copy">{_escape(base.get('attempt_id') or '-')} ↔ {_escape(compare.get('attempt_id') or '-')}</div>
        </div>
        <div class="action-row wrap">
          {_button('清空', 'clear_compare_attempt', state, project_dir, {'tab': module_id, 'task': step['step_id']}, button_class='ghost')}
        </div>
      </div>
      <div class="comparison-grid">
        <div>
          <div class="section-title">Prompt</div>
          <pre class="diff-block">{_escape(payload.get('prompt_diff') or '（没有差异）')}</pre>
        </div>
        <div>
          <div class="section-title">输出</div>
          <pre class="diff-block">{_escape(payload.get('output_diff') or '（没有差异）')}</pre>
        </div>
      </div>
      <div class="two-col">
        <details class="stack-item compact-inner"><summary>主输出</summary><div class="markdown-preview">{_escape(payload.get('base_output') or '暂无输出')}</div></details>
        <details class="stack-item compact-inner"><summary>对比输出</summary><div class="markdown-preview">{_escape(payload.get('compare_output') or '暂无输出')}</div></details>
      </div>
    </section>
    '''

def _render_asset_rows(project_dir: str, assets: list[dict[str, Any]], state: dict[str, str | None], module_id: str, step_id: str, *, allow_primary: bool = False) -> str:
    if not assets:
        return '<div class="empty">暂无文件。</div>'
    rows: list[str] = []
    role_labels = {
        'input': '输入',
        'reference': '参考',
        'output': '输出',
        'final': '最终',
    }
    for asset in assets:
        role = asset.get("context_role") or asset.get("role") or "-"
        primary = _badge('主输出', 'ok') if asset.get('is_primary') else ''
        meta_parts = [role_labels.get(str(role), str(role))]
        if asset.get('owned_by_step') is False:
            source_step = asset.get("source_step_id") or asset.get("linked_from_step_id") or "-"
            meta_parts.append(f'来自 {source_step}')
            action = _button('取消引用', 'unlink_step_asset', state, project_dir, {'tab': module_id, 'task': step_id, 'asset_id': asset['asset_id']}, button_class='ghost')
        else:
            action = _button('设主输出', 'mark_asset_primary', state, project_dir, {'tab': module_id, 'asset_id': asset['asset_id'], 'task': step_id}, button_class='ghost') if allow_primary else ''
        if asset.get('library_bucket'):
            meta_parts.append(f'库 {asset.get("library_bucket")}')
        if asset.get('description'):
            meta_parts.append(str(asset['description']))
        rows.append(
            f'''
            <div class="asset-row">
              <div>
                <div class="asset-title">{_asset_download_link(project_dir, asset)} {primary}</div>
                <div class="asset-meta">{_escape(' · '.join(meta_parts))}</div>
              </div>
              <div class="asset-actions">{action}</div>
            </div>
            '''
        )
    return ''.join(rows)

def _render_package_rows(project_dir: str, packages: list[dict[str, Any]]) -> str:
    if not packages:
        return '<div class="empty">这个步骤还没有交接包。</div>'
    rows = []
    for package in packages:
        rows.append(
            f'''
            <div class="stack-item">
              <strong>{_package_download_link(project_dir, package)}</strong>
              <p>目标：{_escape(package.get('target_label') or '-')} / {_escape(package.get('target_step_label') or '-')} · {_escape(package.get('mode') or '-')}</p>
            </div>
            '''
        )
    return ''.join(rows)



def _web_prompt_pack(project: dict[str, Any], step: dict[str, Any], input_assets: list[dict[str, Any]]) -> str:
    lines = [
        f"项目：{project.get('title') or project.get('project_slug') or '当前项目'}",
        f"当前任务：{_clean_step_title(step.get('title'))}",
        "",
        "目标：",
        step.get('goal') or '未填写',
        "",
        "Prompt：",
        step.get('prompt') or '未填写',
        "",
        "输出要求：",
        step.get('output_expectation') or '给出可继续推进的结果，并明确下一步。',
    ]
    if input_assets:
        lines.extend(["", "会一起上传的文件："])
        for asset in input_assets[:12]:
            role = asset.get('context_role') or asset.get('role') or 'input'
            name = asset.get('filename') or asset.get('name') or asset.get('asset_id') or '-'
            lines.append(f"- {name} ({role})")
    if step.get('operator_notes'):
        lines.extend(["", "补充备注：", step['operator_notes']])
    lines.extend(["", "请直接给出可继续推进的结果；必要时把输出分成结论、正文 / 代码 / 图表建议、下一步。"])
    return "\n".join(lines).strip()



def _render_ai_mode_card(
    project_dir: str,
    project: dict[str, Any],
    state: dict[str, str | None],
    module_id: str,
    step: dict[str, Any],
    input_assets: list[dict[str, Any]],
    output_assets: list[dict[str, Any]],
    attempt_count: int,
    related_packages: list[dict[str, Any]],
) -> str:
    """Legacy card kept for backward compatibility with older tests/screenshots."""
    web_meta = _web_target_meta(step.get('web_target'))
    copy_id = f"prompt-pack-{step['step_id']}"
    prompt_pack = _web_prompt_pack(project, step, input_assets)
    current_mode_label = 'ChatGPT' if step.get('provider_mode') == 'manual_web' and (step.get('web_target') or 'chatgpt') == 'chatgpt' else 'Gemini' if step.get('provider_mode') == 'manual_web' else '页内 AI'
    action_html = f'<button type="button" class="button ghost copy-trigger" data-copy-target="{_escape(copy_id)}" data-copied-label="已复制 Prompt">复制 Prompt</button><a class="button ghost" target="_blank" rel="noreferrer" href="{_escape(web_meta["url"])}">打开 {_escape(web_meta["label"])} </a>'
    return f"""
    <section class="card compact-card launch-card" id="legacy-start-mode">
      <div class="line-card-head"><h2>运行方式</h2><div class="chip-row">{_badge(current_mode_label, 'info')}</div></div>
      {_hidden_copy_source(copy_id, prompt_pack)}
      <div class="helper-text compact-copy">当前版本已把这块合并进中间的 AI 工作区；这里保留给旧链接。</div>
      <div class="action-row wrap">{action_html}</div>
    </section>
    """


def _surface_choice_from_step(step: dict[str, Any]) -> str:
    if step.get('provider_mode') == 'manual_web':
        return 'gemini' if (step.get('web_target') or 'chatgpt') == 'gemini' else 'chatgpt'
    return 'inline'


def _module_pills(project_dir: str, state: dict[str, str | None], active_tab: str) -> str:
    items: list[str] = []
    for tab, label in MODULE_TABS:
        url = _build_url(state, project=project_dir, tab=tab, run=None, artifact=None, session=None, note=None)
        active = ' active' if active_tab == tab else ''
        items.append(f'<a class="module-pill{active}" href="{_escape(url)}">{_escape(label)}</a>')
    return '<nav class="module-pills">' + ''.join(items) + '</nav>'


def _workspace_module_pills(project_dir: str, state: dict[str, str | None], active_tab: str) -> str:
    items: list[str] = [
        f'<a class="module-pill home-link" href="{_escape(_build_url(state, project=project_dir, tab="project", run=None, task=None, artifact=None, session=None, note=None))}">项目首页</a>'
    ]
    for tab, label in MODULE_TABS:
        if tab == 'control':
            continue
        url = _build_url(state, project=project_dir, tab=tab, run=None, artifact=None, session=None, note=None)
        active = ' active' if active_tab == tab else ''
        items.append(f'<a class="module-pill{active}" href="{_escape(url)}">{_escape(label)}</a>')
    items.append(f'<a class="module-pill ghost-link" href="{_escape(_build_url(state, project=project_dir, tab="control", run=None, task=None, artifact=None, session=None, note=None))}">项目设置</a>')
    return '<nav class="module-pills work-shell-nav">' + ''.join(items) + '</nav>'


def _project_home_module_card(project_dir: str, state: dict[str, str | None], module: dict[str, Any], *, current_module_id: str | None = None) -> str:
    active_step = module.get('active_step') or (module.get('steps') or [None])[0] or {}
    module_id = module.get('module_id') or 'paper'
    card_url = _build_url(state, project=project_dir, tab=module_id, task=active_step.get('step_id'), run=None, artifact=None, session=None, note=None)
    current = current_module_id == module_id
    title = _clean_step_title(active_step.get('title') or '打开这条线')
    goal = (active_step.get('goal') or active_step.get('output_expectation') or module.get('description') or '打开后直接进入当前工作步骤。').strip()
    if len(goal) > 120:
        goal = goal[:117].rstrip() + '…'
    order_index = active_step.get('order_index') or 1
    status_bits = [
        f"{module.get('progress_pct', 0)}%",
        f"第 {order_index} / {module.get('total_steps', 0)} 步",
    ]
    if module.get('review_count'):
        status_bits.append(f"待审 {module['review_count']}")
    if module.get('blocked_count'):
        status_bits.append(f"阻塞 {module['blocked_count']}")
    action_label = '继续当前工作' if current else '进入备用路线'
    return f"""
    <article class="module-home-card route-row{' current' if current else ''}">
      <div class="route-row-main">
        <div class="module-home-kicker">{_escape(module.get('label') or _module_label(module_id))}</div>
        <h3>{_escape(title)}</h3>
        <p>{_escape(goal)}</p>
      </div>
      <div class="route-row-meta">
        <strong>{_escape(' · '.join(status_bits[:2]))}</strong>
        <span>{_escape(' · '.join(status_bits[2:]) or '当前入口')}</span>
      </div>
      <div class="route-row-actions"><a class="button {'primary' if current else 'secondary'}" href="{_escape(card_url)}">{action_label}</a></div>
    </article>
    """


def render_project_home(project_dir: str, state: dict[str, str | None]) -> str:
    workspace = WorkspaceSnapshot.load(project_dir)
    normalize_studio(workspace.studio, workspace.project)
    summary = summarize_tree(workspace.studio)
    control = summary.get('control', {})
    modules = [item for item in summary.get('modules', []) if item.get('module_id') in {'paper', 'experiments', 'figures'}]
    current_module_id = summary.get('active_module_id') or 'paper'
    current_module = next((item for item in modules if item.get('module_id') == current_module_id), modules[0] if modules else None)
    current_step = (current_module or {}).get('active_step') or (((current_module or {}).get('steps') or [None])[0] or {})
    project_title = workspace.project.get('title') or summary.get('brief') or '我的研究项目'
    project_goal = control.get('program_goal') or summary.get('brief') or '把项目拆成清楚的步骤，并持续推进。'
    if len(project_goal) > 180:
        project_goal = project_goal[:177].rstrip() + '…'
    current_step_label = _clean_step_title(current_step.get('title') or '打开当前步骤')
    current_step_goal = (current_step.get('goal') or current_step.get('output_expectation') or '进入工作页后，先在主输入区写清楚这一步要做什么。').strip()
    if len(current_step_goal) > 180:
        current_step_goal = current_step_goal[:177].rstrip() + '…'
    current_output_goal = (current_step.get('output_expectation') or '先拿到一版可判断、可采纳、可继续推进的结果。').strip()
    if len(current_output_goal) > 120:
        current_output_goal = current_output_goal[:117].rstrip() + '…'
    next_milestone = control.get('next_milestone') or '先把当前主线推进到下一步。'
    current_url = _build_url(state, project=project_dir, tab=(current_module or {}).get('module_id') or 'paper', task=current_step.get('step_id'), run=None, artifact=None, session=None, note=None)
    settings_url = _build_url(state, project=project_dir, tab='control', run=None, task=None, artifact=None, session=None, note=None)
    advanced_url = _build_url(state, project=project_dir, tab='advanced', run=None, task=None, artifact=None, session=None, note=None)
    blocked_count = len(summary.get('blocked_steps', [])) + len(summary.get('review_steps', []))
    module_cards = ''.join(_project_home_module_card(project_dir, state, module, current_module_id=current_module_id) for module in modules) or '<div class="empty">当前还没有工作线。</div>'
    primary_assets = summary.get('primary_assets', [])[:4]
    latest_primary = primary_assets[0] if primary_assets else None
    latest_primary_label = latest_primary.get('filename') or latest_primary.get('name') or latest_primary.get('asset_id') if latest_primary else '还没有已采纳结果'
    latest_primary_meta = f"{_module_label(latest_primary.get('module_id') or 'paper')} · {latest_primary.get('step_id') or latest_primary.get('source_step_id') or '-'}" if latest_primary else '先进入工作页完成第一版。'
    primary_rows = ''.join(
        f'<li><strong>{_asset_download_link(project_dir, asset)}</strong><span>{_escape(_module_label(asset.get("module_id") or "paper"))} · {_escape(asset.get("step_id") or asset.get("source_step_id") or "-")}</span></li>'
        for asset in primary_assets
    ) or '<li>还没有主输出。先进入工作页生成第一版结果。</li>'
    activity_items = _collect_activity_items(workspace.studio, limit=8)
    activity_rows = ''.join(
        f'<li><strong>{_escape(item.get("title") or item.get("label") or "最近更新")}</strong><span>{_escape(item.get("detail") or item.get("subtitle") or item.get("time") or "")}</span></li>'
        for item in activity_items
    ) or '<li>项目刚建立，还没有最近更新。</li>'
    current_lane_label = _module_label((current_module or {}).get('module_id') or 'paper')
    current_lane_progress = f"{(current_module or {}).get('done_count', 0)}/{(current_module or {}).get('total_steps', 0)} 步"
    current_step_index = current_step.get('order_index') or 1
    focus_summary = '文献与证据 → 研究设计 → 实验执行 → 学术写作'
    return f"""
    <section class="card compact-card project-home-shell mission-home-shell quiet-launch-shell minimal-home-shell">
      <div class="minimal-home-head mission-home-hero quiet-launch-hero">
        <div class="mission-home-copy quiet-launch-copy">
          <div class="eyebrow">科研助手首页</div>
          <h1>{_escape(project_title)}</h1>
          <div class="subtitle project-home-subtitle">{_escape(project_goal)}</div>
        </div>
        <div class="mission-home-actions quiet-launch-actions minimal-home-actions">
          <a class="button primary wide" href="{_escape(current_url)}">继续当前工作</a>
          <div class="chip-row">{_badge('自动保存', 'info')}{_badge('自动带入下一步', 'neutral')}</div>
          <div class="action-row wrap"><a class="button secondary" href="{_escape(settings_url)}">项目设置</a></div>
        </div>
      </div>
      <div class="mission-home-rail quiet-launch-rail minimal-home-strip">
        <div class="goal-mini"><span>当前里程碑</span><strong>{_escape(current_step_label)}</strong><small>{_escape(current_lane_label)} · 第 {current_step_index} / {(current_module or {}).get('total_steps', 0)} 步</small></div>
        <div class="goal-mini"><span>项目完成</span><strong>{_escape(summary.get('overall_progress_pct', 0))}%</strong><small>{_escape(current_lane_progress)} · 待处理 {blocked_count}</small></div>
        <div class="goal-mini"><span>最近采纳</span><strong>{_escape(latest_primary_label)}</strong><small>{_escape(latest_primary_meta)}</small></div>
      </div>
      <section class="mission-spotlight quiet-launch-spotlight minimal-home-focus mission-home-board quiet-launch-board">
        <div class="minimal-home-focus-top">
          <div>
            <span class="goal-spotlight-label">当前最该推进</span>
            <h2>{_escape(current_step_label)}</h2>
            <p>{_escape(current_step_goal)}</p>
          </div>
          <div class="action-row wrap"><a class="button primary" href="{_escape(current_url)}">继续当前工作</a></div>
        </div>
        <div class="mission-loop quiet-launch-loop minimal-home-summary-row">
          <div class="mission-loop-card"><span>当前目标</span><strong>{_escape(current_step_goal)}</strong></div>
          <div class="mission-loop-card"><span>你会先得到</span><strong>{_escape(current_output_goal)}</strong></div>
          <div class="mission-loop-card"><span>自动衔接</span><strong>采纳后系统会自动把当前成品带到“{_escape(next_milestone)}”。</strong></div>
        </div>
        <div class="focus-summary-note">
          <strong>进入后会先得到什么</strong>
          <span>{_escape(focus_summary)}</span>
        </div>
      </section>
    </section>

    <section class="project-home-grid mission-launchpad-grid quiet-launch-grid simplified-home-grid">
      <div class="project-home-main quiet-launch-main">
        <details class="card section-toggle compact-card launch-route-fold" id="project-routes" open>
          <summary>项目路线 · 备用入口</summary>
          <div class="line-card-head">
            <div>
              <h2>项目路线</h2>
              <div class="helper-text compact-copy">首页只保留当前主入口；其它路线、最近采纳和最近更新退到下方折叠区，不抢主视线。你看到的是一个以 evidence 和 deliverable 为核心的科研助手主界面。</div>
            </div>
            <div class="chip-row">{_badge('当前目标优先', 'info')}</div>
          </div>
          <div class="route-list-grid">{module_cards}</div>
        </details>
        <details class="card section-toggle compact-card launch-route-fold">
          <summary>最近已采纳结果 · {len(primary_assets)}</summary>
          <ul class="project-home-list">{primary_rows}</ul>
        </details>
        <details class="card section-toggle compact-card launch-route-fold">
          <summary>最近更新 · {len(activity_items)}</summary>
          <ul class="project-home-list">{activity_rows}</ul>
        </details>
      </div>
    </section>
    """


def render_workspace(project_dir: str, state: dict[str, str | None], module_id: str, dashboard: dict | None = None) -> str:
    workspace = WorkspaceSnapshot.load(project_dir)
    normalize_studio(workspace.studio, workspace.project)
    summary = summarize_tree(workspace.studio)
    module = next((item for item in summary['modules'] if item['module_id'] == module_id), None)
    if module is None:
        return '<section class="card"><h2>模块不存在</h2></section>'

    module_steps = module['steps']
    selected_step_id = state.get('task') or (module.get('active_step') or {}).get('step_id')
    if selected_step_id and module_steps:
        try:
            step = find_step(workspace.studio, selected_step_id)
            if step.get('module_id') != module_id:
                step = module_steps[0]
        except Exception:
            step = module_steps[0]
    else:
        step = module_steps[0] if module_steps else None

    if step is not None:
        from .studio import set_active_step

        set_active_step(workspace.studio, step['step_id'])
        workspace.save_state('studio')
        input_assets = [asset for asset in assets_for_step(workspace.studio, step['step_id']) if (asset.get('context_role') or asset.get('role')) in {'input', 'reference'}]
        output_assets = [asset for asset in assets_for_step(workspace.studio, step['step_id']) if (asset.get('context_role') or asset.get('role')) in {'output', 'final'}]
        attempt_count = len(attempts_for_step(workspace.studio, step['step_id']))
        selected_attempt = next((item for item in workspace.studio.get('attempts', []) if item.get('attempt_id') == step.get('selected_attempt_id')), None)
        preview_text = ''
        if selected_attempt and selected_attempt.get('output_asset_ids'):
            assets_by_id = {asset['asset_id']: asset for asset in all_assets(workspace.studio)}
            first_output = assets_by_id.get(selected_attempt['output_asset_ids'][0])
            if first_output:
                preview_text = asset_text_preview(project_dir, first_output, limit=6000)
        shared_assets = [asset for asset in all_assets(workspace.studio) if asset.get('step_id') != step['step_id']][:300]
        shared_options = ''.join(
            f'<option value="{_escape(asset["asset_id"])}">{_escape(asset.get("filename") or asset.get("name") or asset["asset_id"])} · {_escape(asset.get("library_bucket") or asset.get("module_id") or "")}</option>'
            for asset in shared_assets
        )
        related_packages = [pkg for pkg in reversed(workspace.studio.get('packages', [])) if pkg.get('source_step_id') == step['step_id']][:8]
        template_options = _template_options(workspace.studio, step['step_id'])
        module_progress = f"{module['done_count']}/{module['total_steps']}"
        profile_options = _provider_options(workspace.studio, step.get('provider_profile_id'))
        next_step = next_step_after(workspace.studio, step['step_id'])
        activity_items = _collect_activity_items(workspace.studio, module_id=module_id, step_id=step['step_id'], limit=8)
    else:
        input_assets = []
        output_assets = []
        attempt_count = 0
        selected_attempt = None
        preview_text = ''
        shared_options = ''
        related_packages = []
        template_options = '<option value="">当前还没有模板</option>'
        module_progress = f"{module['done_count']}/{module['total_steps']}"
        profile_options = _provider_options(workspace.studio, None)
        next_step = None
        activity_items = _collect_activity_items(workspace.studio, module_id=module_id, limit=8)

    if step is None:
        header_html = f"""
        <section class="card compact-card workspace-shell-head workspace-focus-head">
          <div class="workspace-focus-top">
            <div class="workspace-header-main">
              <div class="eyebrow">{_escape(_module_label(module_id, long=True))}</div>
              <h1>{_escape(workspace.project.get('title') or summary['brief'])}</h1>
              <div class="workspace-route"><span>当前模块还没有步骤</span><span class="route-sep">•</span><span>先打开左边抽屉新增一步</span></div>
            </div>
            <div class="workspace-focus-actions">
              <button type="button" class="button secondary drawer-toggle" data-drawer="left" aria-controls="step-drawer">步骤</button>
              <button type="button" class="button secondary drawer-toggle" data-drawer="right" aria-controls="files-panel">资料 / 结果</button>
            </div>
          </div>
          <div class="workspace-focus-foot">
            {_module_pills(project_dir, state, module_id)}
            <div class="workspace-kpis">{_badge(f'本线 {module_progress}', 'info')}{_badge(f'总完成 {summary["overall_progress_pct"]}%', 'neutral')}</div>
          </div>
        </section>
        """
        return f"""
        {header_html}
        <button type="button" class="drawer-backdrop" data-drawer-close="all" aria-label="关闭侧边抽屉"></button>
        <section class="studio-layout module-layout focus-layout">
          <aside class="drawer-panel drawer-panel-left" id="step-drawer" aria-label="步骤抽屉">
            <div class="drawer-inline-head"><button type="button" class="ghost drawer-close" data-drawer-close="left">收起步骤</button></div>
            {_render_step_tree(project_dir, summary, state, module_id)}
          </aside>
          <div class="studio-center center-stage">
            <section class="card workspace-card empty-center-card"><h2>当前模块还没有步骤</h2><p>默认只突出中间编辑区；需要新增步骤时，再打开左边抽屉。</p></section>
          </div>
          <aside class="drawer-panel drawer-panel-right" id="files-panel" aria-label="资料与产物抽屉">
            <div class="drawer-inline-head"><button type="button" class="ghost drawer-close" data-drawer-close="right">收起资料</button></div>
            <section class="card side-panel files-panel">
              <div class="line-card-head"><h2>资料 / 结果</h2></div>
              <div class="empty">当前模块还没有步骤，先新增一步后再导入资料或结果。</div>
            </section>
          </aside>
        </section>
        """

    current_surface = _surface_choice_from_step(step)
    current_target = _web_target_meta(step.get('web_target'))
    prompt_pack = _web_prompt_pack(workspace.project, step, input_assets)
    copy_id = f"prompt-pack-{step['step_id']}"
    autosave_id = f"autosave-status-{step['step_id']}"
    selected_label = selected_attempt.get('attempt_id') if selected_attempt else '还没有结果'
    status_badges = ''.join([
        _badge(status_label(step.get('status') or 'todo'), status_tone(step.get('status') or 'todo')),
        _badge(f'历史 {attempt_count}', 'neutral'),
    ])
    current_label = _clean_step_title(step.get('title'))
    next_label = _clean_step_title(next_step.get('title')) if next_step else '本线收尾'
    reference_chip_items = [
        _file_chip(asset.get('filename') or asset.get('name') or asset.get('asset_id') or '未命名资料', 'info')
        for asset in input_assets[:4]
    ]
    if len(input_assets) > 4:
        reference_chip_items.append(_file_chip(f'+{len(input_assets) - 4}', 'neutral'))
    if not reference_chip_items:
        reference_chip_items.append(_file_chip('还没有挂资料', 'neutral'))
    output_chip_items = [
        _file_chip(asset.get('filename') or asset.get('name') or asset.get('asset_id') or '未命名结果', 'ok' if asset.get('is_primary') else 'neutral')
        for asset in output_assets[:3]
    ]
    if len(output_assets) > 3:
        output_chip_items.append(_file_chip(f'+{len(output_assets) - 3}', 'neutral'))
    if not output_chip_items:
        output_chip_items.append(_file_chip('结果会显示在这里', 'neutral'))
    reference_strip = f"""
    <div class="attachment-strip">
      <div class="attachment-strip-label">参考资料</div>
      <div class="file-chip-row">{''.join(reference_chip_items)}</div>
    </div>
    """
    output_strip = f"""
    <div class="attachment-strip output-strip">
      <div class="attachment-strip-label">当前成品</div>
      <div class="file-chip-row">{''.join(output_chip_items)}</div>
    </div>
    """
    surface_meta = {
        'inline': ('页内 AI', '直接在当前页生成；已配 API key 时会直连模型，没配 key 时会先给你一版本地演练结果。', '开始生成'),
        'chatgpt': ('ChatGPT 网页', '系统会先整理 Prompt 和交接包，再去 ChatGPT 继续。', '整理到 ChatGPT'),
        'gemini': ('Gemini 网页', '系统会先整理 Prompt 和交接包，再去 Gemini 继续。', '整理到 Gemini'),
    }
    surface_label, surface_note, submit_label = surface_meta.get(current_surface, surface_meta['inline'])
    surface_picker = f"""
    <div class="editor-surface-picker compact-surface-picker">
      <label class="surface-option"><input type="radio" name="surface_choice" value="inline" {'checked' if current_surface == 'inline' else ''}><span>页内 AI（推荐）</span></label>
      <label class="surface-option"><input type="radio" name="surface_choice" value="chatgpt" {'checked' if current_surface == 'chatgpt' else ''}><span>ChatGPT 网页</span></label>
      <label class="surface-option"><input type="radio" name="surface_choice" value="gemini" {'checked' if current_surface == 'gemini' else ''}><span>Gemini 网页</span></label>
    </div>
    """
    pin_action = ''
    if selected_attempt and selected_attempt.get('output_asset_ids'):
        pin_action = _button(
            '定为主输出',
            'mark_attempt_outputs_primary',
            state,
            project_dir,
            {'tab': module_id, 'task': step['step_id'], 'attempt_id': selected_attempt['attempt_id']},
            button_class='secondary',
        )
    next_action = (
        _button(
            '采纳并下一步',
            'advance_step',
            state,
            project_dir,
            {'tab': module_id, 'task': step['step_id']},
            button_class='primary',
        )
        if next_step
        else _button('标记通过', 'mark_step_done', state, project_dir, {'tab': module_id, 'task': step['step_id']}, button_class='primary')
    )
    selected_attempt_badges = f"{_badge(selected_label, 'info')} {(_attempt_decision_badge(selected_attempt) if selected_attempt else '')}"
    web_tools = f"""
    <div class="inline-tools">
      <button type="button" class="ghost copy-trigger" data-copy-target="{_escape(copy_id)}" data-copied-label="已复制 Prompt">复制 Prompt</button>
      <a class="button ghost{' accent' if current_surface == 'chatgpt' else ''}" target="_blank" rel="noreferrer" href="{_escape(WEB_TARGETS['chatgpt']['url'])}">打开 ChatGPT</a>
      <a class="button ghost{' accent' if current_surface == 'gemini' else ''}" target="_blank" rel="noreferrer" href="{_escape(WEB_TARGETS['gemini']['url'])}">打开 Gemini</a>
    </div>
    """
    handoff_panel = ''
    if related_packages:
        handoff_panel = f"""
        <details class="card section-toggle compact-card" id="web-handoff">
          <summary>网页协同 / 交接包 · {len(related_packages)}</summary>
          <div class="stack-list">{_render_package_rows(project_dir, related_packages)}</div>
        </details>
        """
    prompt_summary = (step.get('prompt') or step.get('goal') or '').strip() or '还没有输入内容。先在上面的主输入区写一句你想让 AI 做的事。'
    if len(prompt_summary) > 420:
        prompt_summary = prompt_summary[:420].rstrip() + '…'
    goal_summary = (step.get('goal') or '').strip() or '还没有写明这一步的任务目标。'
    if len(goal_summary) > 88:
        goal_summary = goal_summary[:85].rstrip() + '…'
    output_summary = (step.get('output_expectation') or '').strip() or '还没有写明希望 AI 交付什么。'
    if len(output_summary) > 88:
        output_summary = output_summary[:85].rstrip() + '…'
    review_excerpt = (selected_attempt.get('human_review') or '').strip() if selected_attempt else ''
    if len(review_excerpt) > 160:
        review_excerpt = review_excerpt[:157].rstrip() + '…'
    decision_map = {
        'candidate': '候选稿，先继续判断再决定是否采纳。',
        'preferred': '当前这版已经被标记为优选，可直接作为主稿继续推进。',
        'discarded': '这一版已被废弃，仅保留作回看参考。',
    }
    decision_note = decision_map.get((selected_attempt or {}).get('review_decision') or 'candidate', '这版还没有正式结论。')
    primary_output = next((asset for asset in output_assets if asset.get('is_primary')), output_assets[0] if output_assets else None)
    if primary_output:
        primary_output_label = primary_output.get('filename') or primary_output.get('name') or primary_output.get('asset_id') or '未命名结果'
        primary_output_note = '采纳后系统会优先把这份输出挂到下一步。'
    else:
        primary_output_label = '还没有主输出'
        primary_output_note = '先生成一次结果，或从右侧抽屉导入已有结果。'
    compare_attempt = next((item for item in workspace.studio.get('attempts', []) if item.get('attempt_id') == step.get('compare_attempt_id')), None)
    compare_label = compare_attempt.get('attempt_id') if compare_attempt else '还没有选择对比稿'
    compare_note = '可以在历史结果里挑一版放进对比线。' if compare_attempt is None else '当前对比稿会保留在下方“对比 / 历史”区域。'
    output_placeholder = '还没有成品。点上面的“开始生成”；如果你不用 API，就在“换一种方式”里切到 ChatGPT / Gemini。'
    project_home_url = _build_url(state, project=project_dir, tab='project', run=None, task=None, artifact=None, session=None, note=None)
    route_switch_links = [f'<a class="module-pill home-link" href="{_escape(project_home_url)}">项目首页</a>']
    for tab, label in MODULE_TABS:
        if tab == 'control':
            continue
        url = _build_url(state, project=project_dir, tab=tab, run=None, artifact=None, session=None, note=None)
        active = ' active' if tab == module_id else ''
        route_switch_links.append(f'<a class="module-pill{active}" href="{_escape(url)}">{_escape(label)}</a>')
    route_switch_links.append(f'<a class="module-pill ghost-link" href="{_escape(_build_url(state, project=project_dir, tab="control", run=None, task=None, artifact=None, session=None, note=None))}">项目设置</a>')
    route_switcher = f"""
    <div class="route-switcher minimal-route-switcher">
      <div class="route-switch-label">切换路线</div>
      <div class="route-switch-grid">{''.join(route_switch_links)}</div>
    </div>
    """
    more_actions = ''
    if pin_action:
        more_actions = f"""
        <details class="inline-details compact-card artifact-actions-details">
          <summary>更多操作</summary>
          <div class="action-row wrap">{pin_action}</div>
        </details>
        """
    flow_badges = ''.join([_badge('自动保存', 'info'), _badge('自动带入下一步', 'neutral')])
    header_html = f"""
    <section class="card compact-card workspace-shell-head work-masthead mission-work-head quiet-work-head minimal-work-head">
      <div class="mission-work-bar quiet-work-bar">
        <div class="mission-work-copy">
          <div class="eyebrow">当前一步</div>
          <h1>{_escape(current_label)}</h1>
          <div class="clarity-route"><a class="inline-home-link" href="{_escape(project_home_url)}">项目首页</a><span class="route-sep">/</span><span>{_escape(_module_label(module_id, long=True))}</span><span class="route-sep">/</span><span>第 {step.get('order_index') or 1} / {module['total_steps']} 步</span></div>
        </div>
        <div class="workspace-focus-actions compact-workspace-actions">
          <button type="button" class="button secondary drawer-toggle" data-drawer="left" aria-controls="step-drawer">步骤</button>
          <button type="button" class="button secondary drawer-toggle" data-drawer="right" aria-controls="files-panel">资料</button>
        </div>
      </div>
      <div class="clarity-head-foot mission-work-foot quiet-work-foot minimal-work-foot">
        {route_switcher}
        <div class="work-step-meta"><span>下一步 · {_escape(next_label)}</span><span>本线 {module_progress}</span><span>历史 {attempt_count}</span></div>
      </div>
    </section>
    """
    center_html = f"""
    <section class="card workspace-card ai-workspace atelier-workspace mission-workspace singletrack-workspace simplified-workspace" id="ai-workspace">
      <div class="line-card-head workspace-title-line mission-title-line quiet-title-line">
        <div>
          <h2>当前一步</h2>
          <div class="helper-text compact-copy">先写当前需求，再判断结果；满意就直接采纳并进入下一步。</div>
        </div>
        <div class="chip-row">{status_badges}</div>
      </div>
      <div class="editor-context-band mission-context-strip minimal-context-strip">
        <div class="context-pill context-pill-wide">
          <span>当前目标</span>
          <strong>{_escape(goal_summary)}</strong>
        </div>
        <div class="context-pill context-pill-wide">
          <span>本步交付</span>
          <strong>{_escape(output_summary)}</strong>
        </div>
      </div>
      <form method="post" action="/action" class="form-stack workspace-form compact-workspace-form editor-shell premium-editor-shell autosave-form" id="current-task" data-autosave-status="{_escape(autosave_id)}">
        {_state_fields(state, project_dir, {'tab': module_id, 'task': step['step_id']})}
        {_hidden_copy_source(copy_id, prompt_pack)}
        <div class="composer-frame atelier-composer-frame mission-composer-frame minimal-composer-frame">
          <div class="composer-head atelier-composer-head mission-composer-head">
            <div>
              <div class="eyebrow">主输入</div>
              <h3>把当前需求直接写给 AI</h3>
            </div>
            <div class="chip-row">{_badge(f'资料 {len(input_assets)}', 'neutral')}{flow_badges}</div>
          </div>
          {reference_strip}
          <label class="composer-main">当前需求{_textarea('prompt', step.get('prompt') or '', '像在给研究搭档写工作说明一样，把你想让 AI 完成的事写在这里。', 12)}</label>
          <details class="inline-details compact-card atelier-details"{' open' if (step.get('goal') or step.get('output_expectation')) else ''}>
            <summary>补充要求</summary>
            <div class="two-col compact-form-grid">
              <label>这一步要完成什么{_textarea('goal', step.get('goal') or '', '例如：把这一节改得更严谨', 3)}</label>
              <label>我希望拿到什么{_textarea('output_expectation', step.get('output_expectation') or '', '例如：给出可直接替换的段落和修改理由', 3)}</label>
            </div>
          </details>
          <div class="composer-toolbar mission-toolbar quiet-toolbar minimal-toolbar">
            <div class="action-row wrap"><button name="action" value="submit_workspace" class="primary">{_escape(submit_label)}</button></div>
            <div class="autosave-status" id="{_escape(autosave_id)}">自动保存已开启 · 采纳后会自动带到“{_escape(next_label)}”</div>
          </div>
          <details class="inline-details compact-card atelier-details"{' open' if current_surface != 'inline' else ''}>
            <summary>换一种方式</summary>
            <div class="helper-text compact-copy editor-note">不用 API 时，再在这里切到 ChatGPT / Gemini；默认仍然优先页内生成。</div>
            {surface_picker}
            <div class="helper-text compact-copy editor-note">{_escape(surface_note)}</div>
            {web_tools}
          </details>
          <details class="inline-details compact-card pro-only atelier-details">
            <summary>更多控制</summary>
            <div class="two-col compact-form-grid">
              <label>标题<input type="text" name="title" value="{_escape(step.get('title') or '')}"></label>
              <label>模板<select name="template_key">{template_options}</select></label>
            </div>
            <div class="action-row wrap">
              <button name="action" value="apply_prompt_template" class="ghost">套模板</button>
              <button name="action" value="mark_step_review" class="ghost">标记待审</button>
              <button name="action" value="reopen_step" class="ghost">重开</button>
            </div>
            <div class="two-col compact-form-grid">
              <label>Profile<select name="provider_profile_id">{profile_options}</select></label>
              <label>provider / 模型<input type="text" name="provider_name" value="{_escape(step.get('provider_name') or '')}" placeholder="可选覆盖"></label>
            </div>
            <div class="two-col compact-form-grid">
              <label>模型说明<input type="text" name="model_hint" value="{_escape(step.get('model_hint') or '')}" placeholder="可选说明"></label>
              <label>模板名<input type="text" name="template_name" placeholder="保存当前 Prompt"></label>
            </div>
            {_template_variable_help()}
            <div class="two-col compact-form-grid">
              <label>保存范围
                <select name="template_scope">
                  <option value="current_step">当前步骤</option>
                  <option value="module">当前模块</option>
                  <option value="project">当前项目</option>
                  <option value="global_personal">全局个人</option>
                </select>
              </label>
              <div></div>
            </div>
            <label>人工备注{_textarea('operator_notes', step.get('operator_notes') or '', '给自己留的说明', 3)}</label>
            <label>审阅备注{_textarea('review_notes', step.get('review_notes') or '', '人类审阅结论', 3)}</label>
            <button name="action" value="save_prompt_template" class="secondary">保存为模板</button>
          </details>
        </div>
      </form>
      <section class="editor-output atelier-output mission-output" id="main-output">
        <div class="artifact-summary-bar mission-artifact-bar quiet-artifact-bar minimal-artifact-bar">
          <div>
            <div class="eyebrow">当前产物</div>
            <h2>{_escape(primary_output_label if primary_output else '第一版成品')}</h2>
            <div class="helper-text compact-copy">默认先看成品，再决定是否采纳并进入下一步。</div>
          </div>
          <div class="action-row wrap">{next_action}</div>
        </div>
        <div class="artifact-board mission-artifact-board minimal-artifact-board">
          <div class="artifact-main mission-artifact-main">
            {output_strip}
            <div class="artifact-canvas{' empty-state' if not preview_text else ''}">
              <div class="artifact-canvas-head"><span>最新结果</span><span>{selected_attempt_badges or _badge('等待生成', 'neutral')}</span></div>
              <div class="artifact-canvas-body"><div class="markdown-preview artifact-preview">{_escape(preview_text or output_placeholder)}</div></div>
            </div>
            {more_actions}
            <details class="artifact-prompt-fold compact-card">
              <summary>本轮输入 / 生成依据</summary>
              <div class="markdown-preview prompt-evidence">{_escape(prompt_summary)}</div>
            </details>
          </div>
          <aside class="artifact-side mission-review-side quiet-artifact-side minimal-artifact-side">
            <div class="review-card result-summary-card summary-stack-card">
              <div class="summary-stack-row">
                <span class="review-label">系统会自动</span>
                <strong>把当前产物带到下一步</strong>
                <p>采纳后会把当前主输出挂到“{_escape(next_label)}”，并补一版默认 Prompt。</p>
              </div>
              <div class="summary-stack-row">
                <span class="review-label">当前版本</span>
                <strong>{_escape(selected_label)}</strong>
                <p>{_escape(decision_note)}</p>
              </div>
              <div class="summary-stack-row">
                <span class="review-label">已采纳主输出</span>
                <strong>{_escape(primary_output_label)}</strong>
                <p>{_escape(primary_output_note)}</p>
              </div>
              <div class="summary-stack-row">
                <span class="review-label">对比稿</span>
                <strong>{_escape(compare_label)}</strong>
                <p>{_escape(compare_note)}</p>
              </div>
            </div>
            <details class="review-card result-summary-card artifact-review-fold"{' open' if review_excerpt else ''}>
              <summary>审阅备注</summary>
              <p>{_escape(review_excerpt or '还没有写审阅意见。你可以在“更多控制”里补充人工判断。')}</p>
            </details>
          </aside>
        </div>
      </section>
    </section>
    <details class="card section-toggle compact-card" id="version-history">
      <summary>历史 / 对比 · {attempt_count}</summary>
      <div class="stack-list">{_render_attempts(project_dir, workspace.studio, step, state, module_id)}</div>
    </details>
    {_render_attempt_comparison(project_dir, workspace.studio, step, state, module_id)}
    {handoff_panel}
    <details class="card section-toggle compact-card" id="activity-stream">
      <summary>最近更新 · {len(activity_items)}</summary>
      {_render_activity_feed('最近更新', activity_items, subtitle='当前步骤的版本、文件和状态会串成一条短流。')}
    </details>
    """
    files_badges = ''.join([
        _badge(f'参考 {len(input_assets)}', 'info'),
        _badge(f'产物 {len(output_assets)}', 'neutral'),
    ])
    left_html = f"""
    <aside class="drawer-panel drawer-panel-left" id="step-drawer" aria-label="步骤抽屉">
      <div class="drawer-inline-head"><button type="button" class="ghost drawer-close" data-drawer-close="left">收起步骤</button></div>
      {_render_step_tree(project_dir, summary, state, module_id)}
    </aside>
    """
    right_html = f"""
    <aside class="drawer-panel drawer-panel-right" id="files-panel" aria-label="资料与产物抽屉">
      <div class="drawer-inline-head"><button type="button" class="ghost drawer-close" data-drawer-close="right">收起资料</button></div>
      <section class="card side-panel files-panel quiet-files-panel">
        <div class="line-card-head"><h2>资料与产物</h2><div class="chip-row">{files_badges}</div></div>
        <div class="helper-text compact-copy">右侧只放支撑当前一步的资料和当前成品；其它内容默认不打断主编辑区。</div>
        <details class="section-toggle compact-card"{' open' if not input_assets else ''}>
          <summary>资料 · {len(input_assets)}</summary>
          <div class="stack-list compact-stack-list">{_render_asset_rows(project_dir, input_assets, state, module_id, step['step_id'], allow_primary=False)}</div>
          <details class="inline-details quick-forms"{' open' if not input_assets else ''}>
            <summary>添加资料</summary>
            <div class="stack-list compact-stack-list">
              <form method="post" action="/action" enctype="multipart/form-data" class="form-stack compact-card panel-muted">
                {_state_fields(state, project_dir, {'action': 'upload_asset', 'tab': module_id, 'task': step['step_id'], 'role': 'input'})}
                <label>上传资料<input type="file" name="upload_file"></label>
                <label>说明<input type="text" name="description" placeholder="可选"></label>
                <button class="secondary">上传到当前一步</button>
              </form>
              <form method="post" action="/action" class="form-stack compact-card panel-muted">
                {_state_fields(state, project_dir, {'action': 'link_asset', 'tab': module_id, 'task': step['step_id']})}
                <label>从共享文件里选<select name="asset_id"><option value="">选择一个文件</option>{shared_options}</select></label>
                <label>用途<select name="role"><option value="reference">参考</option><option value="input">主要输入</option></select></label>
                <button class="secondary">引用到当前一步</button>
              </form>
            </div>
          </details>
        </details>
        <details class="section-toggle compact-card"{' open' if not output_assets else ''}>
          <summary>成品 · {len(output_assets)}</summary>
          <div class="stack-list compact-stack-list">{_render_asset_rows(project_dir, output_assets, state, module_id, step['step_id'], allow_primary=True)}</div>
          <details class="inline-details quick-forms"{' open' if not output_assets else ''}>
            <summary>导入网页结果</summary>
            <form method="post" action="/action" enctype="multipart/form-data" class="form-stack compact-card panel-muted">
              {_state_fields(state, project_dir, {'action': 'upload_asset', 'tab': module_id, 'task': step['step_id'], 'role': 'output'})}
              <label>导入结果<input type="file" name="upload_file"></label>
              <label>说明<input type="text" name="description" placeholder="可选"></label>
              <button class="secondary">导入到当前步骤</button>
            </form>
          </details>
        </details>
      </section>
    </aside>
    """
    return f"""
    {header_html}
    <button type="button" class="drawer-backdrop" data-drawer-close="all" aria-label="关闭侧边抽屉"></button>
    <section class="studio-layout module-layout focus-layout">
      {left_html}
      <div class="studio-center center-stage">{center_html}</div>
      {right_html}
    </section>
    """

def _render_progress_cards(summary: dict[str, Any]) -> str:
    cards = []
    for module in summary['modules']:
        if module['module_id'] == 'control':
            continue
        cards.append(
            f'''
            <div class="metric-card emphasis-card">
              <div class="metric-label">{_escape(_module_label(module['module_id']))}</div>
              <div class="metric-value">{module['progress_pct']}%</div>
              <div class="metric-note">{_escape(module['done_count'])}/{_escape(module['total_steps'])} · 当前 {_escape(_compact_step_title((module.get('active_step') or {}).get('title') or '未开始'))}</div>
            </div>
            '''
        )
    return '<section class="metric-grid">' + ''.join(cards) + '</section>'

def _render_provider_admin(project_dir: str, state: dict[str, str | None], studio: dict[str, Any]) -> str:
    cards = []
    for profile in provider_profiles(studio):
        delete_button = ''
        if not profile.get('is_builtin'):
            delete_button = _button('删除', 'delete_provider_profile', state, project_dir, {'tab': 'control', 'profile_id': profile['profile_id']}, button_class='ghost', confirm_text='确认删除这个 AI 入口？')
        provider_kind = '网页' if profile.get('provider') == 'manual_web' else 'API' if profile.get('provider') != 'mock' else 'Mock'
        cards.append(
            f"""
            <details class="attempt-card">
              <summary>
                <div class="line-card-head"><strong>{_escape(profile.get('name') or profile.get('profile_id') or '未命名入口')}</strong><div>{_badge(provider_kind, 'info')} {_badge(profile.get('provider') or 'openai', 'neutral')}</div></div>
                <div class="project-meta">{_escape(profile.get('base_url') or '使用环境变量 / 默认地址')} · {_escape(profile.get('default_model') or '-')}</div>
              </summary>
              <div class="attempt-body">
                <form method="post" action="/action" class="form-stack compact-card">
                  {_state_fields(state, project_dir, {'tab': 'control'})}
                  <input type="hidden" name="action" value="save_provider_profile">
                  <input type="hidden" name="profile_id" value="{_escape(profile.get('profile_id') or '')}">
                  <label>显示名称<input type="text" name="name" value="{_escape(profile.get('name') or '')}"></label>
                  <div class="two-col compact-form-grid">
                    <label>类型<input type="text" name="provider" value="{_escape(profile.get('provider') or '')}" placeholder="openai / manual_web / custom"></label>
                    <label>默认模型<input type="text" name="default_model" value="{_escape(profile.get('default_model') or '')}"></label>
                  </div>
                  <label>地址<input type="text" name="base_url" value="{_escape(profile.get('base_url') or '')}" placeholder="例如：https://api.openai.com/v1"></label>
                  <label>API Key 环境变量<input type="text" name="api_key_env" value="{_escape(profile.get('api_key_env') or '')}" placeholder="例如：OPENAI_API_KEY"></label>
                  <label>备注{_textarea('notes', profile.get('notes') or '', '记录这个入口的用途', 3)}</label>
                  <div class="action-row wrap"><button class="secondary">保存入口</button>{delete_button}</div>
                </form>
              </div>
            </details>
            """
        )
    new_form = f"""
      <form method="post" action="/action" class="form-stack compact-card">
        {_state_fields(state, project_dir, {'tab': 'control'})}
        <input type="hidden" name="action" value="save_provider_profile">
        <label>新增 AI 入口<input type="text" name="name" placeholder="例如：本地兼容网关"></label>
        <div class="two-col compact-form-grid">
          <label>类型<input type="text" name="provider" value="openai"></label>
          <label>默认模型<input type="text" name="default_model" placeholder="例如：gpt-4.1-mini"></label>
        </div>
        <label>地址<input type="text" name="base_url" placeholder="例如：https://my-gateway/v1"></label>
        <label>API Key 环境变量<input type="text" name="api_key_env" placeholder="例如：OPENAI_API_KEY"></label>
        <label>备注{_textarea('notes', '', '这个入口在项目里什么时候使用', 2)}</label>
        <button class="secondary">新增入口</button>
      </form>
    """
    cards_html = ''.join(cards) or '<div class="empty">当前没有 AI 入口。</div>'
    body = f'<div class="helper-text compact-copy">API 走平台内运行；ChatGPT / Gemini 走网页协同。</div>{new_form}{cards_html}'
    return _details_card(
        'AI 接入',
        body,
        badge_html=_badge(f'{len(provider_profiles(studio))} 个入口', 'info'),
        open=False,
    )

def _render_template_admin(studio: dict[str, Any]) -> str:
    project_templates = studio.get('prompt_templates', [])
    global_templates = []
    try:
        from .studio import _load_global_prompt_templates  # type: ignore

        global_templates = _load_global_prompt_templates().get('templates', [])
    except Exception:
        global_templates = []

    scope_label = {
        'current_step': '当前步骤模板',
        'module': '当前模块模板',
        'project': '当前项目模板',
        'global_personal': '全局个人模板',
        'system_default': '系统默认模板',
        'module_default': '模块默认模板',
        'step_default': '步骤默认模板',
    }

    def make_rows(items: list[dict[str, Any]], origin: str) -> str:
        if not items:
            return '<li>暂无模板。</li>'
        rows = []
        for item in items:
            scope = scope_label.get(item.get('scope') or 'project', item.get('scope') or 'project')
            refs = []
            if item.get('module_id'):
                refs.append(f"模块：{item['module_id']}")
            if item.get('step_id'):
                refs.append(f"步骤：{item['step_id']}")
            rows.append(f'<li><strong>{_escape(item.get("name") or item.get("template_id") or "未命名模板")}</strong><br><span>{_escape(origin)} · {_escape(scope)} · {_escape(" / ".join(refs) or "全局")}</span></li>')
        return ''.join(rows)

    body = f"""
    <div class="two-col">
      <div>
        <div class="section-title">项目模板</div>
        <ul class="doctor-list">{make_rows(project_templates, '项目内')}</ul>
      </div>
      <div>
        <div class="section-title">全局个人模板</div>
        <ul class="doctor-list">{make_rows(global_templates, '个人')}</ul>
      </div>
    </div>
    <p>创建和保存模板的主入口在每个步骤的 Prompt 区；这里主要负责集中查看。</p>
    """
    return _details_card(
        'Prompt 模板',
        body,
                badge_html=_badge(f'{len(project_templates) + len(global_templates)} 个模板', 'info'),
        open=False,
    )

def _render_master_snapshot(summary: dict[str, Any], project_dir: str) -> str:
    cards: list[str] = []
    control = summary.get('control', {})
    status_by_module = {
        'paper': control.get('paper_master_status') or '未锁定',
        'experiments': control.get('experiment_master_status') or '未锁定',
        'figures': control.get('figure_master_status') or '未锁定',
        'control': control.get('writeback_status') or '未开始',
    }
    for module_id, label in MODULE_TABS:
        module_assets = summary.get('master_assets_by_module', {}).get(module_id, [])
        entries = ''.join(f'<li>{_asset_download_link(project_dir, asset)}<br><span>{_escape(asset.get("library_bucket") or "-")} · {_escape(asset.get("step_id") or asset.get("source_step_id") or "-")}</span></li>' for asset in module_assets[:6]) or '<li>还没有锁定主文件。</li>'
        cards.append(
            f'''
            <section class="card compact-card">
              <div class="line-card-head"><h2>{_escape(label)}</h2>{_badge(status_by_module.get(module_id) or '未锁定', 'info')}</div>
              <ul class="doctor-list">{entries}</ul>
            </section>
            '''
        )
    bucket_counts = summary.get('bucket_counts', {})
    bucket_cards = ''.join(f'<div class="metric-card compact-card"><div class="metric-title">library/{_escape(bucket)}</div><div class="metric-value">{bucket_counts.get(bucket, 0)}</div></div>' for bucket in ['paper', 'experiments', 'figures', 'shared', 'handoff_packages'])
    return f'''
    <section class="card">
      <div class="line-card-head"><h2>主输出快照</h2>{_badge(f"未引用文件 {len(summary.get('unreferenced_assets', []))}", 'warn' if summary.get('unreferenced_assets') else 'ok')}</div>
      <div class="two-col">{''.join(cards[:2])}</div>
      <div class="two-col">{''.join(cards[2:4])}</div>
      <div class="metric-grid compact-grid">{bucket_cards}</div>
    </section>
    '''


def _render_library_admin(project_dir: str, state: dict[str, str | None], studio: dict[str, Any]) -> str:
    assets = all_assets(studio)
    if not assets:
        return _details_card('共享文件库', '<div class="empty">当前还没有文件。</div>', badge_html=_badge('0 个文件', 'neutral'), open=False)
    cards = []
    for asset in assets[:180]:
        refs = asset_reference_summary(studio, asset['asset_id'])
        ref_text = '；'.join(f"{item.get('step_id')}({item.get('role')})" for item in refs) or '当前无引用'
        ref_chips = ''.join(_badge(f"{item.get('step_id')} · {item.get('role')}", 'neutral') for item in refs) or _badge('当前无引用', 'warn')
        type_family = 'image' if str(asset.get('mime_type') or '').startswith('image/') else ('text' if Path(str(asset.get('filename') or asset.get('name') or '')).suffix.lower() in {'.md', '.txt', '.tex', '.py', '.json', '.yaml', '.yml', '.csv', '.tsv', '.html', '.xml', '.log', '.sh', '.rst'} else 'binary')
        search_blob = ' '.join(str(part or '') for part in [asset.get('asset_id'), asset.get('filename'), asset.get('name'), asset.get('local_path'), asset.get('module_id'), asset.get('step_id'), ref_text]).lower()
        set_primary_action = _button('设主输出', 'mark_asset_primary', state, project_dir, {'tab': 'control', 'asset_id': asset['asset_id']}, button_class='ghost') if asset.get('role') in {'output', 'final'} else ''
        cards.append(
            f"""
            <details class="attempt-card library-card" data-bucket="{_escape(asset.get('library_bucket') or '-')}" data-module="{_escape(asset.get('module_id') or '-')}" data-type="{_escape(type_family)}" data-primary="{'yes' if asset.get('is_primary') else 'no'}" data-hasrefs="{'yes' if len(refs) > 1 else 'no'}" data-search="{_escape(search_blob)}">
              <summary>
                <div class="line-card-head"><strong>{_asset_download_link(project_dir, asset)}</strong><div>{_badge(asset.get('library_bucket') or '-', 'info')} {_badge('主输出', 'ok') if asset.get('is_primary') else ''}</div></div>
                <div class="project-meta">{_escape(_module_label(asset.get('module_id') or 'paper'))} / {_escape(asset.get('step_id') or '-')} · {_escape(asset.get('local_path') or '-')}</div>
              </summary>
              <div class="attempt-body">
                {_asset_preview_fragment(project_dir, asset)}
                <div class="chip-row">{ref_chips}</div>
                <div class="helper-text compact-copy">类型：{_escape(type_family)} · MIME：{_escape(asset.get('mime_type') or '-')}</div>
                <form method="post" action="/action" class="form-stack compact-card">
                  {_state_fields(state, project_dir, {'tab': 'control', 'asset_id': asset['asset_id']})}
                  <input type="hidden" name="action" value="rename_asset">
                  <label>文件名<input type="text" name="filename" value="{_escape(asset.get('filename') or asset.get('name') or '')}"></label>
                  <button class="secondary">重命名</button>
                </form>
                <form method="post" action="/action" class="form-stack compact-card">
                  {_state_fields(state, project_dir, {'tab': 'control', 'asset_id': asset['asset_id']})}
                  <input type="hidden" name="action" value="move_asset_bucket">
                  <label>移动到
                    <select name="bucket">
                      <option value="paper" {'selected' if asset.get('library_bucket') == 'paper' else ''}>library/paper</option>
                      <option value="experiments" {'selected' if asset.get('library_bucket') == 'experiments' else ''}>library/experiments</option>
                      <option value="figures" {'selected' if asset.get('library_bucket') == 'figures' else ''}>library/figures</option>
                      <option value="handoff_packages" {'selected' if asset.get('library_bucket') == 'handoff_packages' else ''}>library/handoff_packages</option>
                      <option value="shared" {'selected' if asset.get('library_bucket') == 'shared' else ''}>library/shared</option>
                    </select>
                  </label>
                  <button class="secondary">移动</button>
                </form>
                <div class="action-row wrap">
                  {set_primary_action}
                  {_button('删除文件', 'delete_asset', state, project_dir, {'tab': 'control', 'asset_id': asset['asset_id']}, button_class='ghost', confirm_text='确认删除这个文件？它会从共享文件库和引用关系中移除。')}
                </div>
              </div>
            </details>
            """
        )
    body = f"""
    <section id="library-admin-root">
      <div class="library-filter-bar compact-card">
        <label>搜索<input type="text" id="library-search" placeholder="文件名 / 步骤 / 路径"></label>
        <label>分区
          <select id="library-bucket-filter">
            <option value="all">全部</option>
            <option value="paper">paper</option>
            <option value="experiments">experiments</option>
            <option value="figures">figures</option>
            <option value="shared">shared</option>
            <option value="handoff_packages">handoff_packages</option>
          </select>
        </label>
        <label>模块
          <select id="library-module-filter">
            <option value="all">全部</option>
            <option value="paper">写论文</option>
            <option value="experiments">做实验</option>
            <option value="figures">做图表</option>
            <option value="control">看总览</option>
          </select>
        </label>
        <label>类型
          <select id="library-type-filter">
            <option value="all">全部</option>
            <option value="text">文本</option>
            <option value="image">图片</option>
            <option value="binary">二进制</option>
          </select>
        </label>
        <label>筛选
          <select id="library-special-filter">
            <option value="all">全部</option>
            <option value="primary">仅主输出</option>
            <option value="referenced">仅多步引用</option>
            <option value="unreferenced">仅待整理</option>
          </select>
        </label>
      </div>
      <div class="helper-text" id="library-filter-result">显示 {len(assets)} / {len(assets)} 个文件</div>
      <div class="stack-list">{"".join(cards)}</div>
      <script>
      (function() {{
        const root = document.getElementById('library-admin-root');
        if (!root) return;
        const search = root.querySelector('#library-search');
        const bucket = root.querySelector('#library-bucket-filter');
        const mod = root.querySelector('#library-module-filter');
        const type = root.querySelector('#library-type-filter');
        const special = root.querySelector('#library-special-filter');
        const result = root.querySelector('#library-filter-result');
        const cards = Array.from(root.querySelectorAll('.library-card'));
        const apply = () => {{
          const q = (search.value || '').trim().toLowerCase();
          let shown = 0;
          cards.forEach((card) => {{
            const okSearch = !q || (card.dataset.search || '').includes(q);
            const okBucket = bucket.value === 'all' || card.dataset.bucket === bucket.value;
            const okModule = mod.value === 'all' || card.dataset.module === mod.value;
            const okType = type.value === 'all' || card.dataset.type === type.value;
            let okSpecial = true;
            if (special.value === 'primary') okSpecial = card.dataset.primary === 'yes';
            if (special.value === 'referenced') okSpecial = card.dataset.hasrefs === 'yes';
            if (special.value === 'unreferenced') okSpecial = card.dataset.hasrefs === 'no' && card.dataset.primary !== 'yes';
            const visible = okSearch && okBucket && okModule && okType && okSpecial;
            card.style.display = visible ? '' : 'none';
            if (visible) shown += 1;
          }});
          result.textContent = `显示 ${{shown}} / {len(assets)} 个文件`;
        }};
        [search, bucket, mod, type, special].forEach((node) => node && node.addEventListener('input', apply));
        [bucket, mod, type, special].forEach((node) => node && node.addEventListener('change', apply));
        apply();
      }})();
      </script>
    </section>
    """
    return _details_card(
        '共享文件库',
        body,
                badge_html=_badge(f'{len(assets)} 个文件', 'info'),
        open=False,
    )

def _render_handoff_admin(project_dir: str, studio: dict[str, Any]) -> str:
    packages = list(reversed(studio.get('packages', [])))
    handoffs = list(reversed(studio.get('handoffs', [])))
    pkg_rows = ''.join(
        f'<li><strong>{_package_download_link(project_dir, pkg)}</strong><br><span>{_escape(pkg.get("source_step_id") or "-")} -> {_escape(pkg.get("target_label") or "-")} / {_escape(pkg.get("target_step_label") or "-")}</span></li>'
        for pkg in packages[:40]
    ) or '<li>还没有交接包。</li>'
    handoff_rows = ''.join(
        f'<li><strong>{_escape(item.get("handoff_id") or "-")}</strong><br><span>{_escape(item.get("from_step_id") or "-")} -> {_escape(item.get("to_provider") or item.get("to_label") or "-")} · {_escape(item.get("status") or "-")}</span></li>'
        for item in handoffs[:40]
    ) or '<li>还没有交接记录。</li>'
    body = f"""
    <section class="two-col">
      <section class="card compact-card"><h2>交接包</h2><ul class="doctor-list">{pkg_rows}</ul></section>
      <section class="card compact-card"><h2>交接记录</h2><ul class="doctor-list">{handoff_rows}</ul></section>
    </section>
    """
    return _details_card(
        '交接记录',
        body,
                badge_html=_badge(f'{len(packages)} 个包 / {len(handoffs)} 条记录', 'info' if packages or handoffs else 'neutral'),
        open=False,
    )


def render_control(project_dir: str, state: dict[str, str | None]) -> str:
    workspace = WorkspaceSnapshot.load(project_dir)
    normalize_studio(workspace.studio, workspace.project)
    summary = summarize_tree(workspace.studio)
    control = summary['control']
    blocked_items = summary['blocked_steps'] + summary['review_steps']
    blocked_rows = ''.join(
        f'<li><strong>{_escape(_clean_step_title(step["title"]))} </strong><br><span>{_escape(status_label(step.get("status") or "todo"))} · {_escape(step.get("review_notes") or step.get("operator_notes") or step.get("goal") or "")}</span></li>'
        for step in blocked_items[:40]
    ) or '<li>当前没有等待审阅或被阻塞的步骤。</li>'
    advanced_url = _build_url(state, project=project_dir, tab='advanced', run=None, artifact=None, session=None, note=None)
    doctor_url = _build_url(state, project=project_dir, tab='doctor', run=None, artifact=None, session=None, note=None)
    control_nav = '''
    <nav class="tabs control-subtabs">
      <a class="tab" href="#control-overview">总览</a>
      <a class="tab" href="#control-activity">活动</a>
      <a class="tab" href="#control-masters">主输出</a>
      <a class="tab" href="#control-library">文件</a>
      <a class="tab" href="#control-templates">模板</a>
      <a class="tab" href="#control-providers">AI</a>
      <a class="tab" href="#control-handoff">交接</a>
    </nav>
    '''
    ai_mode_cards = '''
    <details class="card section-toggle compact-card simple-run-modes">
      <summary>运行方式</summary>
      <div class="simple-copy-stack">
        <p>默认优先页内 AI；没配 API 时，再切到 ChatGPT / Gemini 网页协同。Mock 只用来先检查步骤流程。</p>
        <div class="chip-row"><span class="badge info">页内 AI</span><span class="badge neutral">ChatGPT 网页</span><span class="badge neutral">Gemini 网页</span><span class="badge neutral">Mock</span></div>
      </div>
    </details>
    '''
    activity_html = _render_activity_feed('项目活动流', _collect_activity_items(workspace.studio, limit=10), card_id='control-activity', subtitle='把步骤、文件、版本、交接和总控更新放到一条时间线上。')
    pending_html = _details_card(
        '待处理队列',
        f'<ul class="doctor-list">{blocked_rows}</ul>',
        badge_html=_badge(f'{len(blocked_items)} 项', 'warn' if blocked_items else 'neutral'),
        open=bool(blocked_items),
    )
    return f'''
    {_module_links(project_dir, state, 'control')}
    {control_nav}
    <section class="card compact-card project-strip minimal-control-head" id="control-overview">
      <div class="project-strip-main">
        <div class="eyebrow">{_escape(_module_label('control', long=True))}</div>
        <h1>{_escape(workspace.project.get('title') or summary['brief'])}</h1>
      </div>
      <div class="chip-row">
        {_badge(f'总完成 {summary["overall_progress_pct"]}%', 'info')}
        {_badge(f'文件 {summary["asset_count"]}', 'neutral')}
        {_badge(f'AI 入口 {summary["provider_count"]}', 'neutral')}
      </div>
    </section>
    <section class="card compact-card control-focus-card minimal-control-focus">
      <div class="focus-lane">
        <div class="focus-node current"><span>项目目标</span><strong>{_escape(control.get('program_goal') or summary['brief'])}</strong></div>
        <div class="focus-node"><span>下一里程碑</span><strong>{_escape(control.get('next_milestone') or '未设定')}</strong></div>
        <div class="focus-node"><span>待处理</span><strong>{_escape(len(blocked_items))}</strong></div>
      </div>
    </section>
    {ai_mode_cards}
    {_render_progress_cards(summary)}
    <section class="two-col">
      <section class="card">
        <div class="line-card-head"><h2>项目设置</h2><div class="action-row wrap"><a class="button ghost" href="{_escape(advanced_url)}">高级视图</a><a class="button ghost" href="{_escape(doctor_url)}">健康检查</a></div></div>
        <form method="post" action="/action" class="form-stack compact-workspace-form">
          {_state_fields(state, project_dir, {'action': 'save_control', 'tab': 'control'})}
          <label>项目目标{_textarea('program_goal', control.get('program_goal') or summary['brief'], '一句话概括项目目标', 2)}</label>
          <div class="two-col compact-form-grid">
            <label>下一里程碑<input type="text" name="next_milestone" value="{_escape(control.get('next_milestone') or '')}"></label>
            <label>仓库 / 链接<input type="text" name="github_repo" value="{_escape(control.get('github_repo') or '')}" placeholder="可选"></label>
          </div>
          <button class="primary">保存概览</button>
          <details class="inline-details pro-only">
            <summary>更多状态</summary>
            <div class="two-col compact-form-grid">
              <label>投稿状态<input type="text" name="submission_status" value="{_escape(control.get('submission_status') or '')}"></label>
              <label>开源状态<input type="text" name="open_source_status" value="{_escape(control.get('open_source_status') or '')}"></label>
            </div>
            <div class="two-col compact-form-grid">
              <label>论文主输出<input type="text" name="paper_master_status" value="{_escape(control.get('paper_master_status') or '')}"></label>
              <label>实验主输出<input type="text" name="experiment_master_status" value="{_escape(control.get('experiment_master_status') or '')}"></label>
            </div>
            <div class="two-col compact-form-grid">
              <label>图片主输出<input type="text" name="figure_master_status" value="{_escape(control.get('figure_master_status') or '')}"></label>
              <label>结果回写<input type="text" name="writeback_status" value="{_escape(control.get('writeback_status') or '')}"></label>
            </div>
            <label>风险{_textarea('risk_notes', control.get('risk_notes') or '', '主要风险', 2)}</label>
            <label>阻塞{_textarea('blocking_notes', control.get('blocking_notes') or '', '当前卡点', 2)}</label>
            <label>备注{_textarea('manager_notes', control.get('manager_notes') or '', '补充判断', 3)}</label>
          </details>
        </form>
      </section>
      {activity_html}
    </section>
    {pending_html}
    <div id="control-masters">{_render_master_snapshot(summary, project_dir)}</div>
    <div id="control-templates">{_render_template_admin(workspace.studio)}</div>
    <div id="control-providers">{_render_provider_admin(project_dir, state, workspace.studio)}</div>
    <div id="control-library">{_render_library_admin(project_dir, state, workspace.studio)}</div>
    <div id="control-handoff">{_render_handoff_admin(project_dir, workspace.studio)}</div>
    '''


def render_library(project_dir: str, state: dict[str, str | None]) -> str:
    return render_control(project_dir, {**state, 'tab': 'control'})
