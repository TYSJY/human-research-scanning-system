from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as email_policy
import html
import json
import mimetypes
import shutil
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from .bootstrap import copy_demo_project, create_project_from_template
from .common import now_iso, resolve_within_root
from .executors import approve_run, cancel_run, retry_run, run_worker
from .orchestrator import run_once, run_workloop
from .reporting import build_audit_report, build_showcase_package
from .sqlite_sync import sync_project_sqlite
from .studio import (
    add_step,
    add_substep,
    apply_prompt_template,
    apply_starter_ai_profile,
    branch_step_from_attempt,
    complete_step_and_advance,
    create_handoff_package,
    delete_asset,
    delete_provider_profile,
    delete_step,
    find_step,
    link_existing_asset,
    link_uploaded_result_to_latest_handoff,
    make_download_filename,
    mark_asset_primary,
    mark_attempt_outputs_primary,
    move_asset,
    move_step,
    normalize_studio,
    register_asset,
    reopen_step,
    review_attempt,
    save_prompt_template,
    set_compare_attempt,
    select_attempt,
    set_active_step,
    status_label,
    steps_for_line,
    summarize_tree,
    unlink_step_asset,
    update_control_from_form,
    update_step_from_form,
    upsert_provider_profile,
    write_active_context,
)
from .studio_runtime import run_mock_attempt, run_openai_attempt
from .studio_ui import render_control, render_library, render_project_home, render_workspace
from .ux import (
    APP_NAME,
    APP_VERSION,
    STAGE_SEQUENCE,
    detect_default_owner,
    doctor_report,
    eval_status_title,
    humanize_exception,
    list_projects,
    next_available_name,
    pick_pending_approval,
    project_artifact_details,
    project_dashboard,
    project_note_details,
    project_run_details,
    project_session_details,
    project_task_details,
    run_status_title,
    stage_title,
)
from .workspace import WorkspaceSnapshot


STATE_KEYS = ["project", "tab", "mode", "run", "task", "artifact", "session", "note"]
TASK_STATUS_LABELS = {
    "todo": "待开始",
    "blocked": "等待前置条件",
    "done": "已完成",
    "in_progress": "进行中",
}


PAGE_CSS = """
:root {
  --bg: #f6f7fb;
  --panel: #ffffff;
  --panel-soft: #fbfcfe;
  --panel-muted: #f8fafc;
  --line: #e5e7eb;
  --line-strong: #dbe3ee;
  --text: #111827;
  --muted: #667085;
  --muted-2: #94a3b8;
  --shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
  --shadow-soft: 0 2px 12px rgba(15, 23, 42, 0.04);
  --ok: #166534;
  --info: #2563eb;
  --warn: #b45309;
  --bad: #be123c;
  --accent-weak: #eff6ff;
  --accent-line: #bfdbfe;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}
a { color: inherit; text-decoration: none; }
p { line-height: 1.72; color: var(--muted); margin: 0; }
h1, h2, h3 { margin: 0; line-height: 1.18; color: var(--text); }
h1 { font-size: 31px; letter-spacing: -0.02em; }
h2 { font-size: 20px; }
h3 { font-size: 15px; }
ul, ol { padding-left: 20px; color: var(--muted); line-height: 1.72; }
li { margin-bottom: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 12px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--text); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
code { background: #f3f4f6; padding: 2px 6px; border-radius: 6px; color: #1f2937; }
pre { margin: 0; white-space: pre-wrap; }
.app { display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: 100vh; }
.sidebar {
  padding: 24px;
  border-right: 1px solid var(--line);
  background: #fbfcff;
  position: sticky;
  top: 0;
  align-self: start;
  min-height: 100vh;
}
.main { padding: 28px 30px 40px; max-width: 1480px; width: 100%; margin: 0 auto; }
.brand-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.brand { font-size: 21px; font-weight: 800; letter-spacing: -0.02em; }
.brand-note { color: var(--muted); line-height: 1.65; margin-bottom: 18px; }
.section-title {
  margin: 18px 0 10px;
  text-transform: uppercase;
  letter-spacing: .08em;
  font-size: 11px;
  color: var(--muted-2);
  font-weight: 800;
}
.section-head, .line-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.card, .metric-card, .continue-card, .note-card, .project-link {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow-soft);
}
.card { padding: 20px; margin-bottom: 16px; }
.compact-card { padding: 14px 16px; }
.sidebar-card { padding: 14px; }
.sidebar-details > summary { list-style: none; }
.sidebar-details > summary::-webkit-details-marker { display: none; }
.sidebar-details > summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: pointer; }
.sidebar-details > summary::after { content: "▾"; color: var(--muted-2); font-size: 14px; font-weight: 700; }
.sidebar-details[open] > summary::after { content: "▴"; }
.project-list { display: grid; gap: 10px; }
.project-link { display: block; padding: 14px 15px; transition: border-color .15s ease, transform .15s ease, background .15s ease; }
.project-link:hover, .project-link.active-project { border-color: var(--accent-line); background: var(--accent-weak); transform: translateY(-1px); }
.project-title { font-weight: 700; margin-bottom: 4px; }
.project-meta, .project-next, .subtitle, .helper-text, .detail-meta, .goal-text, .timeline-detail, .timeline-time, .note-status, .row-sub {
  color: var(--muted);
}
.project-meta, .project-next, .helper-text, .detail-meta, .row-sub { font-size: 13px; }
.project-next { margin-top: 6px; }
.mini-progress, .progress-bar {
  margin-top: 10px;
  height: 6px;
  border-radius: 999px;
  background: #eef2f7;
  overflow: hidden;
}
.mini-progress span, .progress-bar span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #2563eb 0%, #60a5fa 100%);
}
.hero { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(300px, .65fr); gap: 16px; align-items: stretch; margin-bottom: 18px; }
.home-hero { grid-template-columns: 1fr; }
.hero-side, .stack-card {
  padding: 18px 20px;
  border-radius: 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
}
.page-intro { padding: 24px; }
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--info);
  margin-bottom: 10px;
  font-weight: 800;
}
.subtitle { margin-top: 10px; font-size: 16px; max-width: 920px; }
.action-row { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
.action-row.vertical { flex-direction: column; }
button, .button {
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 10px 14px;
  color: var(--text);
  font-weight: 700;
  background: #ffffff;
  box-shadow: none;
  text-align: center;
  transition: border-color .15s ease, background .15s ease, transform .15s ease;
}
button:hover, .button:hover { transform: translateY(-1px); }
button.primary, .button.primary {
  background: var(--info);
  color: white;
}
button.secondary, .button.secondary {
  background: var(--panel);
  border-color: var(--line-strong);
}
button.ghost, .button.ghost {
  background: transparent;
  border-color: var(--line);
  color: var(--muted);
}
button.wide, .button.wide { width: 100%; }
.inline-form { display: inline-block; }
.inline-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.quick-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.stat-pill { padding: 12px 14px; border-radius: 14px; border: 1px solid var(--line); background: var(--panel-muted); }
.stat-pill span { display: block; margin-bottom: 6px; font-size: 11px; color: var(--muted-2); text-transform: uppercase; letter-spacing: .08em; font-weight: 800; }
.stat-pill strong { display: block; font-size: 14px; color: var(--text); line-height: 1.45; }
.mode-segment-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.mode-segment-grid .inline-form { display: block; }
.mode-segment { width: 100%; background: var(--panel-soft); border-color: var(--line); color: var(--muted); }
.mode-segment.active { background: var(--accent-weak); border-color: var(--accent-line); color: var(--info); }
.launch-card { margin-bottom: 16px; }
.launch-note { margin-top: 12px; color: var(--muted); line-height: 1.65; }
.quick-forms { margin-top: 12px; }
.hidden-copy-source { position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
.badge {
  display: inline-flex;
  align-items: center;
  padding: 7px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  border: 1px solid transparent;
}
.badge.ok { background: #ecfdf3; color: var(--ok); border-color: #bbf7d0; }
.badge.info { background: #eff6ff; color: var(--info); border-color: #bfdbfe; }
.badge.warn { background: #fffbeb; color: var(--warn); border-color: #fcd34d; }
.badge.bad { background: #fff1f2; color: var(--bad); border-color: #fecdd3; }
.badge.neutral { background: #f8fafc; color: var(--muted); border-color: var(--line); }
.flash {
  margin-bottom: 16px;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: white;
}
.flash.ok { border-color: #86efac; background: #f0fdf4; }
.flash.warn { border-color: #fcd34d; background: #fffbeb; }
.flash.error { border-color: #fecdd3; background: #fff1f2; }
.flash pre { margin: 0; font-family: inherit; white-space: pre-wrap; color: #1f2937; }
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.crumbs { display: flex; gap: 8px; color: var(--muted); font-size: 14px; align-items: center; flex-wrap: wrap; }
.page-summary { margin-top: 6px; color: var(--muted); }
.mode-switch, .topbar-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.mode-pill {
  padding: 9px 13px;
  border-radius: 999px;
  background: white;
  border: 1px solid var(--line);
  color: var(--muted);
  font-weight: 700;
}
.mode-pill.active { background: var(--accent-weak); border-color: var(--accent-line); color: var(--info); }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.tab {
  padding: 10px 14px;
  border-radius: 999px;
  background: white;
  border: 1px solid var(--line);
  color: var(--muted);
  font-weight: 700;
}
.tab.active-tab { background: var(--accent-weak); color: var(--info); border-color: var(--accent-line); }
.module-tabs {
  gap: 10px;
  margin-bottom: 18px;
  padding: 12px;
  background: white;
  border: 1px solid var(--line);
  border-radius: 18px;
  position: sticky;
  top: 18px;
  z-index: 5;
  box-shadow: var(--shadow-soft);
}
.module-tabs .tab { min-width: 136px; text-align: center; background: #f8fafc; }
.module-pills { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
.module-pill {
  padding: 10px 14px;
  border-radius: 999px;
  background: white;
  border: 1px solid var(--line);
  color: var(--muted);
  font-weight: 700;
}
.module-pill.active { background: var(--accent-weak); color: var(--info); border-color: var(--accent-line); }
.workspace-shell-head { padding: 20px 22px; margin-bottom: 18px; }
.workspace-header-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.workspace-header-main { min-width: 0; }
.workspace-route { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; color: var(--muted); font-size: 14px; }
.route-sep { color: var(--muted-2); }
.workspace-kpis { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.ai-workspace { display: grid; gap: 18px; }
.editor-shell { display: grid; gap: 16px; }
.editor-utility-line { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.editor-note { margin-top: -6px; }
.editor-surface-picker { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.surface-option { position: relative; display: block; }
.surface-option input { position: absolute; opacity: 0; pointer-events: none; }
.surface-option span {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 52px;
  padding: 10px 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  color: var(--muted);
  font-weight: 800;
  text-align: center;
}
.surface-option input:checked + span { background: var(--accent-weak); border-color: var(--accent-line); color: var(--info); }
.inline-tools { display: flex; flex-wrap: wrap; gap: 10px; }
.editor-output { display: grid; gap: 12px; padding-top: 4px; border-top: 1px solid var(--line); }
.output-shell {
  padding: 16px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  min-height: 220px;
}
.output-shell.empty-state { display: flex; align-items: center; }
.output-shell .markdown-preview { margin: 0; }
.files-panel .line-card-head h2 { margin-right: 8px; }
.metric-grid { display: grid; grid-template-columns: repeat(6, minmax(130px, 1fr)); gap: 12px; margin-bottom: 16px; }
.compact-grid { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
.metric-card { padding: 16px; }
.metric-card.compact { padding: 14px; margin: 0; }
.metric-label, .metric-title { color: var(--muted-2); font-size: 11px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: .08em; font-weight: 800; }
.metric-note { margin-top: 6px; font-size: 13px; color: var(--muted); line-height: 1.55; }
.metric-value { font-size: 28px; font-weight: 800; letter-spacing: -0.03em; }
.metric-value.small { font-size: 18px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.home-grid { align-items: stretch; }
.continue-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.continue-card { display: block; padding: 18px; background: var(--panel-soft); }
.continue-card:hover { border-color: var(--accent-line); background: var(--accent-weak); }
.continue-title { font-weight: 800; margin-bottom: 8px; }
.continue-meta { font-size: 13px; color: var(--muted); }
.continue-next { margin-top: 14px; color: var(--info); font-weight: 700; }
.status-line { padding: 10px 0; border-bottom: 1px solid var(--line); color: var(--muted); }
.status-line:last-child { border-bottom: 0; }
.progress-block { margin-top: 2px; }
.progress-meta { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.progress-note { color: var(--muted); font-size: 13px; margin-top: 8px; }
.journey { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; }
.journey-step {
  position: relative;
  padding: 16px;
  border-radius: 16px;
  background: var(--panel-soft);
  border: 1px solid var(--line);
}
.journey-step.current { border-color: var(--accent-line); background: var(--accent-weak); }
.journey-step.done { border-color: #bbf7d0; }
.journey-bullet { width: 12px; height: 12px; border-radius: 999px; background: #cbd5e1; margin-bottom: 10px; }
.journey-step.done .journey-bullet { background: #22c55e; }
.journey-step.current .journey-bullet { background: #3b82f6; }
.journey-title { font-weight: 800; margin-bottom: 6px; }
.journey-meta { color: var(--muted); font-size: 12px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: .05em; }
.journey-desc { color: var(--muted); font-size: 14px; line-height: 1.6; }
.readiness-card.ok { border-color: #86efac; }
.readiness-card.info { border-color: #bfdbfe; }
.readiness-card.warn { border-color: #fcd34d; }
.readiness-card.bad { border-color: #fecdd3; }
.readiness-title, .doctor-title { font-size: 18px; font-weight: 800; margin-bottom: 8px; }
.guide-list { color: var(--muted); line-height: 1.8; }
.guide-list.compact { margin-top: 10px; }
.note-grid { display: grid; gap: 12px; }
.note-card {
  display: block;
  padding: 16px;
  border-radius: 16px;
  background: var(--panel-soft);
  border: 1px solid var(--line);
}
.note-card:hover { border-color: var(--accent-line); background: var(--accent-weak); }
.note-head { font-weight: 800; margin-bottom: 6px; }
.note-card p { margin: 0; font-size: 14px; }
.timeline { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }
.timeline li { padding: 14px; border-radius: 16px; background: var(--panel-soft); border: 1px solid var(--line); }
.timeline-title { font-weight: 800; margin-bottom: 6px; }
.timeline-time { font-size: 12px; margin-top: 8px; }
.detail-card { margin-bottom: 16px; }
.detail-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 14px; }
.detail-grid { margin-top: 14px; }
.stack-list { display: grid; gap: 12px; }
.stack-item { padding: 14px 0; border-bottom: 1px solid var(--line); }
.stack-item:last-child { border-bottom: 0; }
.doctor-list, .check-list { list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }
.doctor-list li, .check-item {
  padding: 13px 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
}
.check-item.ok { border-color: #86efac; }
.check-item.info { border-color: #bfdbfe; }
.check-item.warn { border-color: #fcd34d; }
.check-item.bad { border-color: #fecdd3; }
.check-title { font-weight: 800; margin-bottom: 6px; }
.check-detail, .check-fix { color: var(--muted); font-size: 14px; line-height: 1.7; }
.empty { color: var(--muted); padding: 8px 0; }
.inline-link { color: var(--info); font-weight: 600; }
.row-sub { margin-top: 4px; }
.done-row td { color: #9ca3af; }
.attention-row td { color: #be123c; }
.doctor-summary.ok { border-color: #86efac; }
.doctor-summary.warn { border-color: #fcd34d; }
.doctor-summary.bad { border-color: #fecdd3; }
.markdown-preview {
  padding: 15px 16px;
  border-radius: 14px;
  background: var(--panel-muted);
  border: 1px solid var(--line);
  max-height: 420px;
  overflow: auto;
  white-space: pre-wrap;
  color: #1f2937;
}
details summary { cursor: pointer; font-weight: 700; list-style: none; }
details summary::-webkit-details-marker { display: none; }
details > summary::after { content: "▾"; color: var(--muted-2); font-size: 14px; font-weight: 700; margin-left: auto; }
details[open] > summary::after { content: "▴"; }
label { display: grid; gap: 7px; font-weight: 700; color: #111827; }
input[type="text"], textarea, select, input[type="file"] {
  width: 100%;
  border-radius: 12px;
  border: 1px solid var(--line-strong);
  background: #ffffff;
  color: var(--text);
  padding: 10px 12px;
}
input[type="text"]::placeholder, textarea::placeholder { color: #98a2b3; }
textarea { min-height: 88px; resize: vertical; font: inherit; line-height: 1.6; }
select { appearance: none; }
.form-stack { display: grid; gap: 10px; }
.studio-layout { display: grid; grid-template-columns: 228px minmax(0, 1.6fr) minmax(300px, .78fr); gap: 18px; align-items: flex-start; }
.studio-left, .studio-center, .studio-right { display: grid; gap: 16px; }
.module-layout { align-items: flex-start; }
.tree-card { position: sticky; top: 84px; }
.step-tree { display: grid; gap: 8px; }
.tree-line-title { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--info); margin: 10px 0 4px; font-weight: 800; }
.step-tree-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--panel-soft);
  border: 1px solid var(--line);
  transition: border-color .15s ease, background .15s ease;
}
.step-tree-row.is-child { margin-left: 16px; }
.step-tree-row.active-step-row { border-color: var(--accent-line); background: var(--accent-weak); }
.step-tree-main { min-width: 0; }

.step-tree-meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.mini-actions { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; opacity: 0; transition: opacity .15s ease; }
.step-tree-row:hover .mini-actions, .step-tree-row.active-step-row .mini-actions { opacity: 1; }
.inset-form {
  margin-top: 14px;
  background: var(--panel-muted);
  border: 1px dashed var(--line-strong);
}
.workspace-card h1 { font-size: 28px; letter-spacing: -0.03em; }
.workspace-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.project-strip { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.project-strip-main { min-width: 0; }
.workflow-card { margin-top: -2px; }
.step-rail { display: grid; grid-template-columns: repeat(auto-fit, minmax(52px, 1fr)); gap: 10px; margin: 14px 0; }
.rail-step {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 54px;
  padding: 10px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--panel-muted);
  color: var(--muted);
  font-weight: 800;
}
.rail-step.done { background: #ecfdf3; border-color: #bbf7d0; color: var(--ok); }
.rail-step.current { background: var(--accent-weak); border-color: var(--accent-line); color: var(--info); }
.rail-step.upcoming { background: var(--panel-soft); }
.rail-index { font-size: 16px; line-height: 1; }
.focus-lane { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.focus-node { padding: 12px 14px; border-radius: 14px; border: 1px solid var(--line); background: var(--panel-muted); }
.focus-node span { display: block; margin-bottom: 6px; font-size: 11px; color: var(--muted-2); text-transform: uppercase; letter-spacing: .08em; font-weight: 800; }
.focus-node strong { display: block; line-height: 1.45; }
.focus-node.current { border-color: var(--accent-line); background: var(--accent-weak); }
.step-tree-row-link { display: block; }
.step-tree-row-link:hover .step-tree-row { border-color: var(--accent-line); }
.step-tree-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: white;
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.step-tree-side { display: flex; align-items: center; }
.step-tree-title { font-weight: 700; color: var(--text); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.files-panel .section-toggle:first-of-type { margin-top: 0; }
.home-start-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.start-card { padding: 16px; border: 1px solid var(--line); border-radius: 16px; background: var(--panel-muted); }
.start-index { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 999px; background: white; border: 1px solid var(--line); font-weight: 800; margin-bottom: 10px; }
.start-title { font-weight: 800; margin-bottom: 4px; }
.control-focus-card { margin-top: -2px; }
.status-stack { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.focus-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.mini-stat {
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--panel-muted);
}
.mini-stat-label { font-size: 11px; color: var(--muted-2); text-transform: uppercase; letter-spacing: .08em; margin-bottom: 6px; font-weight: 800; }
.mini-stat-value { font-weight: 800; color: var(--text); }
.mini-stat-note { margin-top: 4px; font-size: 12px; color: var(--muted); line-height: 1.5; }
.workspace-form .action-row { margin-top: 8px; }
.primary-action-row { padding-top: 6px; border-top: 1px solid var(--line); }
.template-toolbar { grid-template-columns: minmax(0, 1.25fr) auto; align-items: end; }
.toolbar-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.toolbar-bottom { margin-top: 12px; }
.compact-copy { color: var(--muted); }
.kpi-row { margin-bottom: 16px; }
.compact-hero-side { display: flex; align-items: center; justify-content: flex-end; }
.compact-form-grid { align-items: start; }
.compact-stack-list { gap: 10px; }
.compact-inner { padding-top: 10px; }
.compact-workspace-form textarea { min-height: 84px; }
.compact-workspace-form textarea[name="prompt"] { min-height: 220px; }
.mode-pill.focus-toggle { user-select: none; }
body.focus-ui .compact-copy,
body.focus-ui .card-subtitle,
body.focus-ui .brand-note,
body.focus-ui .helper-text {
  display: none !important;
}
body.focus-ui .card,
body.focus-ui .metric-card,
body.focus-ui .continue-card,
body.focus-ui .note-card,
body.focus-ui .project-link {
  box-shadow: none;
}
body.focus-ui .module-tabs { top: 12px; }
.mode-pill.focus-toggle, .mode-pill.pro-toggle { user-select: none; }
.command-toggle { border-color: var(--line-strong); background: var(--panel); }
.priority-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.priority-card { padding: 14px; border-radius: 16px; border: 1px solid var(--line); background: var(--panel-soft); }
.priority-card.ok { border-color: rgba(22, 101, 52, 0.18); background: rgba(22, 101, 52, 0.05); }
.priority-card.warn { border-color: rgba(180, 83, 9, 0.18); background: rgba(180, 83, 9, 0.06); }
.priority-card.info { border-color: rgba(37, 99, 235, 0.18); background: rgba(37, 99, 235, 0.06); }
.priority-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.priority-eyebrow { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted-2); font-weight: 800; margin-bottom: 6px; }
.activity-feed { display: grid; gap: 10px; margin-top: 14px; }
.activity-item { display: grid; grid-template-columns: 12px minmax(0, 1fr); gap: 12px; align-items: start; padding: 12px 0; border-bottom: 1px solid var(--line); }
.activity-item:last-child { border-bottom: 0; padding-bottom: 0; }
.activity-dot { width: 12px; height: 12px; border-radius: 999px; margin-top: 5px; background: #cbd5e1; }
.activity-dot.info { background: #60a5fa; }
.activity-dot.ok { background: #4ade80; }
.activity-dot.warn { background: #f59e0b; }
.activity-dot.bad { background: #f43f5e; }
.activity-copy { min-width: 0; }
.activity-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
.activity-time { margin-top: 8px; font-size: 12px; color: var(--muted-2); }
.command-dialog[hidden] { display: none !important; }
.command-dialog { position: fixed; inset: 0; z-index: 50; background: rgba(15, 23, 42, 0.38); display: flex; align-items: flex-start; justify-content: center; padding: 64px 20px 24px; }
.command-panel { width: min(760px, calc(100vw - 40px)); max-height: calc(100vh - 88px); overflow: hidden; background: var(--panel); border: 1px solid var(--line); border-radius: 24px; box-shadow: 0 30px 80px rgba(15, 23, 42, 0.24); display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; }
.command-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px 10px; }
.command-head h2 { font-size: 22px; }
.command-search-wrap { padding: 0 20px 16px; }
.command-search { width: 100%; border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; font: inherit; background: var(--panel-soft); }
.command-search:focus { outline: none; border-color: var(--accent-line); background: #fff; }
.command-list { padding: 0 12px 16px; overflow: auto; display: grid; gap: 6px; }
.command-group { padding: 2px 8px 8px; }
.command-group-label { padding: 10px 10px 6px; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted-2); font-weight: 800; }
.command-item { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border-radius: 14px; border: 1px solid transparent; background: transparent; color: var(--text); text-align: left; }
.command-item:hover { background: var(--panel-soft); border-color: var(--line); }
.command-copy { display: grid; gap: 4px; min-width: 0; }
.command-copy strong { font-size: 14px; }
.command-meta { font-size: 12px; color: var(--muted); }
.command-side { display: inline-flex; align-items: center; gap: 8px; color: var(--muted-2); font-size: 12px; white-space: nowrap; }
.kbd { display: inline-flex; align-items: center; justify-content: center; min-width: 24px; padding: 3px 8px; border-radius: 8px; border: 1px solid var(--line); background: var(--panel-soft); color: var(--muted); font-size: 12px; font-weight: 700; }
.command-footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; padding: 14px 20px 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }
.command-empty { padding: 18px 14px; color: var(--muted); }
.home-hints { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.starter-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.starter-card { padding: 18px; border: 1px solid var(--line); border-radius: 18px; background: var(--panel-soft); display: grid; gap: 12px; }
.starter-card.recommended { border-color: var(--accent-line); background: #f8fbff; }
.starter-card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.starter-title { font-weight: 800; font-size: 18px; margin-bottom: 4px; }
.starter-note { font-size: 13px; color: var(--muted); line-height: 1.6; }
.novice-only { display: block; }
body:not(.pro-ui) .pro-only { display: none !important; }
body.pro-ui .novice-only { display: none !important; }
body.focus-ui .kpi-row { margin-bottom: 10px; }
.section-toggle, .inline-details, .admin-toggle {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-soft);
  padding: 14px 16px;
  margin-top: 12px;
}
.section-toggle > summary, .inline-details > summary, .admin-toggle > summary { display: flex; align-items: center; gap: 10px; }
.section-toggle .stack-list, .admin-toggle .stack-list { margin-top: 10px; }
.attempt-card {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-soft);
  padding: 14px;
  margin-bottom: 12px;
}
.attempt-card > summary { display: block; }
.attempt-body { display: grid; gap: 12px; margin-top: 12px; }
.comparison-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.diff-block {
  margin: 0;
  padding: 14px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid var(--line);
  max-height: 360px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  color: #1f2937;
}
.asset-row { display: flex; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.asset-row:last-child { border-bottom: 0; }
.asset-title { font-weight: 700; }
.asset-meta { color: var(--muted); font-size: 12px; margin-top: 6px; line-height: 1.6; }
.asset-actions { display: flex; align-items: center; }
.chip-row { display: flex; flex-wrap: wrap; gap: 8px; }
.compact-preview { max-height: 260px; font-size: 13px; }
.asset-preview-image {
  display: block;
  max-width: 100%;
  max-height: 280px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: white;
}
.library-filter-bar { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 14px 0; }
.wrap { flex-wrap: wrap; }
.emphasis-card { border-color: var(--accent-line); background: #f8fbff; }
.info-card { border-color: var(--accent-line); }
.control-subtabs { margin: -4px 0 16px; }
.control-subtabs .tab { background: #f8fafc; }
.panel-muted { background: var(--panel-muted); }
.accent { border-color: var(--accent-line) !important; background: var(--accent-weak) !important; color: var(--info) !important; }
.focus-layout { grid-template-columns: minmax(0, 1fr); position: relative; }
.center-stage { width: min(980px, 100%); margin: 0 auto; display: grid; gap: 16px; }
.drawer-backdrop { position: fixed; inset: 0; z-index: 18; background: rgba(15, 23, 42, 0.28); border: 0; display: none; }
.drawer-panel {
  position: fixed;
  top: 88px;
  bottom: 18px;
  width: min(360px, calc(100vw - 32px));
  overflow: auto;
  z-index: 20;
  transition: transform .22s ease;
  pointer-events: none;
}
.drawer-panel > * { pointer-events: auto; }
.drawer-panel-left { left: 16px; transform: translateX(calc(-100% - 24px)); }
.drawer-panel-right { right: 16px; transform: translateX(calc(100% + 24px)); }
body.show-left-drawer .drawer-panel-left { transform: translateX(0); }
body.show-right-drawer .drawer-panel-right { transform: translateX(0); }
body.show-left-drawer .drawer-backdrop, body.show-right-drawer .drawer-backdrop { display: block; }
body.show-left-drawer, body.show-right-drawer { overflow: hidden; }
.drawer-inline-head { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.drawer-panel .tree-card, .drawer-panel .side-panel { box-shadow: 0 18px 50px rgba(15, 23, 42, 0.16); }
.workspace-focus-head { margin-bottom: 16px; }
.workspace-focus-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.workspace-focus-actions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }
.workspace-focus-foot { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line); }
.workspace-focus-head .module-pills { margin-bottom: 0; }
.empty-center-card { min-height: 260px; text-align: center; display: grid; place-content: center; }
.composer-frame { display: grid; gap: 14px; padding: 18px; border-radius: 18px; border: 1px solid var(--line); background: var(--panel-soft); }
.composer-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.composer-main textarea { min-height: 280px; font-size: 15px; line-height: 1.75; }
.composer-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.autosave-status { font-size: 13px; color: var(--muted); }
.autosave-status.saving { color: #b45309; }
.autosave-status.saved { color: #166534; }
.autosave-status.error { color: #be123c; }
.chat-thread { display: grid; gap: 12px; }
.thread-bubble { padding: 16px; border-radius: 18px; border: 1px solid var(--line); }
.thread-bubble.user { background: #ffffff; margin-right: 12%; }
.thread-bubble.assistant { background: var(--panel-soft); margin-left: 6%; }
.thread-role { margin-bottom: 8px; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted-2); font-weight: 800; }
.thread-content { line-height: 1.7; white-space: pre-wrap; }
.prompt-summary { color: #111827; }
.chat-preview { margin: 0; padding: 0; border: 0; background: transparent; max-height: none; }
.compact-surface-picker { margin-top: 4px; }
@media (max-width: 1220px) {
  .metric-grid { grid-template-columns: repeat(3, minmax(130px, 1fr)); }
  .continue-grid { grid-template-columns: 1fr; }
  .journey { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .studio-layout { grid-template-columns: 1fr; }
  .template-toolbar, .focus-grid, .focus-lane, .home-start-grid, .mode-segment-grid, .quick-stats, .priority-grid, .starter-grid, .editor-surface-picker { grid-template-columns: 1fr; }
  .command-dialog { padding-top: 24px; }
  .command-panel { width: calc(100vw - 24px); max-height: calc(100vh - 48px); }
  .comparison-grid { grid-template-columns: 1fr; }
  .library-filter-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tree-card { position: static; }
  .module-tabs { position: static; }
  .drawer-panel { top: 72px; width: min(420px, calc(100vw - 24px)); }
  .center-stage { width: 100%; }
}
@media (max-width: 1020px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { position: static; min-height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
  .hero, .two-col, .studio-layout { grid-template-columns: 1fr; }
  .drawer-panel { top: 68px; }
}

@media (max-width: 720px) {
  .main, .sidebar { padding: 16px; }
  .metric-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .journey, .focus-grid, .focus-lane, .home-start-grid, .mode-segment-grid, .quick-stats, .priority-grid, .starter-grid, .editor-surface-picker { grid-template-columns: 1fr; }
  .library-filter-bar { grid-template-columns: 1fr; }
  .tabs { overflow-x: auto; padding-bottom: 4px; }
  .detail-header, .topbar, .workspace-head, .workspace-header-top, .editor-utility-line { flex-direction: column; align-items: flex-start; }
  .mode-switch { width: 100%; }
  .step-tree-row .mini-actions { opacity: 1; }
  .workspace-focus-top, .workspace-focus-foot, .composer-head, .composer-toolbar { flex-direction: column; align-items: flex-start; }
  .thread-bubble.user, .thread-bubble.assistant { margin-left: 0; margin-right: 0; }
  .drawer-panel { width: calc(100vw - 16px); top: 8px; bottom: 8px; }
  .drawer-panel-left { left: 8px; transform: translateX(-110%); }
  .drawer-panel-right { right: 8px; transform: translateX(110%); }
}

/* ===== 0.6.2 premium aesthetic refinement ===== */
:root {
  --bg: #eef2ff;
  --panel: rgba(255, 255, 255, 0.82);
  --panel-soft: rgba(250, 252, 255, 0.92);
  --panel-muted: rgba(246, 248, 253, 0.96);
  --line: rgba(148, 163, 184, 0.20);
  --line-strong: rgba(99, 102, 241, 0.18);
  --text: #0f172a;
  --muted: #5b6477;
  --muted-2: #8b95a7;
  --shadow: 0 28px 90px rgba(35, 53, 97, 0.16);
  --shadow-soft: 0 16px 44px rgba(35, 53, 97, 0.10);
  --ok: #11795b;
  --info: #4f46e5;
  --warn: #d97706;
  --bad: #d9485f;
  --accent-weak: rgba(99, 102, 241, 0.10);
  --accent-line: rgba(99, 102, 241, 0.28);
}
html {
  background:
    radial-gradient(1100px 520px at 12% 0%, rgba(129, 140, 248, 0.22), transparent 62%),
    radial-gradient(900px 520px at 92% 0%, rgba(59, 130, 246, 0.18), transparent 58%),
    linear-gradient(180deg, #f8f9ff 0%, #eef2ff 100%);
}
body {
  background: transparent;
  color: var(--text);
  letter-spacing: -0.008em;
  position: relative;
}
body::before,
body::after {
  content: "";
  position: fixed;
  inset: auto;
  z-index: -1;
  border-radius: 999px;
  filter: blur(86px);
  opacity: 0.55;
  pointer-events: none;
}
body::before {
  width: 360px;
  height: 360px;
  top: 80px;
  left: -110px;
  background: rgba(99, 102, 241, 0.20);
}
body::after {
  width: 340px;
  height: 340px;
  top: 20px;
  right: -110px;
  background: rgba(56, 189, 248, 0.18);
}
::-webkit-scrollbar { width: 11px; height: 11px; }
::-webkit-scrollbar-track { background: rgba(15, 23, 42, 0.02); }
::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(129, 140, 248, 0.78), rgba(59, 130, 246, 0.72));
  border-radius: 999px;
  border: 2px solid rgba(255, 255, 255, 0.7);
}
a, button, .button, input, textarea, select { transition: all .18s ease; }
.sidebar {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.78), rgba(247, 249, 255, 0.62));
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border-right: 1px solid rgba(255, 255, 255, 0.55);
  box-shadow: inset -1px 0 0 rgba(148, 163, 184, 0.10);
}
.main { padding: 34px 38px 48px; }
.card, .metric-card, .continue-card, .note-card, .project-link, .hero-side, .stack-card {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 255, 0.78));
  border: 1px solid rgba(255, 255, 255, 0.65);
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}
.card { border-radius: 24px; }
.compact-card { border-radius: 22px; }
.project-link:hover,
.project-link.active-project,
.continue-card:hover,
.note-card:hover {
  box-shadow: 0 20px 50px rgba(79, 70, 229, 0.10);
}
button, .button {
  border-radius: 14px;
  font-weight: 780;
  padding: 11px 16px;
  border-color: rgba(255, 255, 255, 0.76);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(246, 248, 255, 0.86));
}
button:hover, .button:hover { transform: translateY(-1px) scale(1.01); }
button.primary, .button.primary {
  background: linear-gradient(135deg, #5b5cf0 0%, #3b82f6 100%);
  color: #fff;
  border: 0;
  box-shadow: 0 14px 34px rgba(79, 70, 229, 0.24);
}
button.secondary, .button.secondary {
  border-color: rgba(99, 102, 241, 0.12);
  color: #1f2a44;
}
button.ghost, .button.ghost {
  background: rgba(255, 255, 255, 0.48);
  border-color: rgba(148, 163, 184, 0.18);
  color: var(--muted);
}
.mode-pill, .module-pill, .tab {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.86), rgba(247, 249, 255, 0.76));
  border-color: rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
}
.mode-pill.active, .module-pill.active, .tab.active-tab {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(59, 130, 246, 0.12));
  border-color: rgba(99, 102, 241, 0.24);
}
.badge {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.66);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.project-topbar {
  padding: 14px 2px 18px;
  border-bottom-color: rgba(148, 163, 184, 0.16);
  margin-bottom: 18px;
}
.brand-note.compact-copy { max-width: 600px; }
.premium-home-landing,
.premium-shell-head,
.workspace-card.ai-workspace,
.command-panel,
.drawer-panel .tree-card,
.drawer-panel .side-panel {
  position: relative;
  overflow: hidden;
}
.premium-home-landing::before,
.premium-shell-head::before,
.workspace-card.ai-workspace::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(480px 220px at 100% 0%, rgba(56, 189, 248, 0.12), transparent 60%),
    radial-gradient(420px 240px at 0% 0%, rgba(129, 140, 248, 0.14), transparent 62%);
  pointer-events: none;
}
.premium-home-landing { padding: 28px; }
.premium-home-landing .subtitle { max-width: 780px; font-size: 16px; }
.starter-card {
  padding: 22px;
  border-radius: 24px;
  gap: 16px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(245, 248, 255, 0.82));
}
.starter-card.recommended {
  background:
    linear-gradient(160deg, rgba(237, 242, 255, 0.98), rgba(248, 250, 255, 0.90));
  border-color: rgba(99, 102, 241, 0.18);
  box-shadow: 0 24px 56px rgba(79, 70, 229, 0.14);
}
.start-card,
.continue-card,
.note-card,
.priority-card,
.mini-stat,
.focus-node,
.journey-step,
.status-line,
.doctor-list li,
.check-item,
.attempt-card,
.section-toggle,
.inline-details,
.admin-toggle {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.78), rgba(246, 248, 255, 0.78));
  border-color: rgba(148, 163, 184, 0.18);
}
.workspace-shell-head {
  padding: 24px 24px 20px;
  border-radius: 28px;
  box-shadow: var(--shadow);
}
.premium-workspace-top { align-items: flex-start; }
.premium-focus-actions .button { min-width: 128px; }
.workspace-route {
  font-size: 14px;
  color: #4a5872;
  margin-top: 12px;
}
.workspace-hero-panel {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}
.hero-mini-card {
  padding: 15px 16px;
  border-radius: 20px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.86), rgba(243, 246, 255, 0.76));
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}
.hero-mini-card span,
.attachment-strip-label {
  display: block;
  font-size: 11px;
  letter-spacing: .10em;
  text-transform: uppercase;
  color: var(--muted-2);
  margin-bottom: 7px;
  font-weight: 800;
}
.hero-mini-card strong {
  display: block;
  font-size: 26px;
  letter-spacing: -0.04em;
  color: var(--text);
  line-height: 1;
}
.hero-mini-card small {
  display: block;
  margin-top: 8px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}
.workspace-focus-foot {
  border-top-color: rgba(148, 163, 184, 0.16);
}
.workspace-card.ai-workspace {
  border-radius: 30px;
  padding: 24px;
  box-shadow: var(--shadow);
}
.line-card-head h2 { letter-spacing: -0.03em; }
.premium-editor-shell { gap: 18px; }
.composer-frame {
  gap: 16px;
  padding: 24px;
  border-radius: 28px;
  border: 1px solid rgba(255, 255, 255, 0.66);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.93), rgba(247, 249, 255, 0.82));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.70),
    0 20px 44px rgba(35, 53, 97, 0.10);
}
.composer-head {
  align-items: center;
  gap: 16px;
}
.attachment-strip {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 20px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background:
    linear-gradient(180deg, rgba(248, 250, 255, 0.96), rgba(243, 246, 255, 0.90));
}
.output-strip {
  margin-bottom: 2px;
  background:
    linear-gradient(180deg, rgba(241, 245, 255, 0.96), rgba(247, 250, 255, 0.90));
}
.file-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background: rgba(255, 255, 255, 0.88);
  color: #334155;
}
.file-chip.info {
  background: rgba(79, 70, 229, 0.10);
  border-color: rgba(79, 70, 229, 0.16);
  color: #4338ca;
}
.file-chip.ok {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.18);
  color: #047857;
}
.file-chip.neutral {
  background: rgba(255, 255, 255, 0.90);
  color: #64748b;
}
.composer-main textarea,
input[type="text"], textarea, select, input[type="file"] {
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 255, 0.90));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.80);
}
.composer-main textarea {
  min-height: 320px;
  padding: 18px 20px;
  font-size: 16px;
  line-height: 1.82;
}
input[type="text"]:focus,
textarea:focus,
select:focus,
input[type="file"]:focus {
  outline: none;
  border-color: rgba(99, 102, 241, 0.36);
  box-shadow:
    0 0 0 4px rgba(99, 102, 241, 0.10),
    inset 0 1px 0 rgba(255, 255, 255, 0.84);
}
.composer-toolbar {
  padding-top: 4px;
  align-items: center;
}
.autosave-status {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.70);
  border: 1px solid rgba(148, 163, 184, 0.14);
}
.inline-details summary,
.section-toggle summary,
.admin-toggle summary {
  font-size: 14px;
}
.editor-output {
  gap: 16px;
  padding-top: 18px;
  border-top-color: rgba(148, 163, 184, 0.14);
}
.chat-thread { gap: 16px; }
.thread-bubble {
  padding: 18px 20px;
  border-radius: 24px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 14px 30px rgba(35, 53, 97, 0.06);
}
.thread-bubble.user {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 249, 255, 0.90));
  margin-right: 10%;
}
.thread-bubble.assistant {
  background:
    linear-gradient(180deg, rgba(237, 242, 255, 0.84), rgba(255, 255, 255, 0.94));
  border-color: rgba(99, 102, 241, 0.18);
  margin-left: 4%;
}
.thread-role { color: #7c89a4; }
.markdown-preview {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.80), rgba(248, 250, 255, 0.74));
  border-color: rgba(148, 163, 184, 0.16);
}
.drawer-backdrop {
  background: rgba(15, 23, 42, 0.26);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.drawer-panel {
  top: 94px;
  bottom: 24px;
  width: min(378px, calc(100vw - 32px));
}
.drawer-panel .tree-card,
.drawer-panel .side-panel {
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.90), rgba(247, 249, 255, 0.84));
  border: 1px solid rgba(255, 255, 255, 0.68);
  box-shadow: 0 22px 62px rgba(15, 23, 42, 0.16);
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
}
.command-dialog {
  background: rgba(15, 23, 42, 0.32);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
.command-panel {
  width: min(760px, calc(100vw - 32px));
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(245, 247, 255, 0.86));
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 28px;
  box-shadow: 0 34px 90px rgba(15, 23, 42, 0.24);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
}
.command-search {
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 255, 0.88));
}
.activity-item,
.asset-row,
.stack-item {
  border-bottom-color: rgba(148, 163, 184, 0.14);
}
@media (max-width: 1220px) {
  .workspace-hero-panel { grid-template-columns: 1fr; }
}
@media (max-width: 1020px) {
  .main { padding: 24px 18px 38px; }
}

.project-link.active-project {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(59, 130, 246, 0.12));
  border-color: rgba(99, 102, 241, 0.20);
}
.workspace-shell-head {
  background:
    linear-gradient(160deg, rgba(255, 255, 255, 0.92), rgba(236, 242, 255, 0.82));
}
.workspace-card.ai-workspace {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(240, 244, 255, 0.84));
}
.hero-mini-card:nth-child(1) {
  background: linear-gradient(160deg, rgba(236, 242, 255, 0.94), rgba(255, 255, 255, 0.82));
}
.hero-mini-card:nth-child(2) {
  background: linear-gradient(160deg, rgba(235, 245, 255, 0.94), rgba(255, 255, 255, 0.82));
}
.hero-mini-card:nth-child(3) {
  background: linear-gradient(160deg, rgba(238, 250, 255, 0.94), rgba(255, 255, 255, 0.82));
}
.composer-head {
  padding: 14px 16px;
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(246, 248, 255, 0.98), rgba(239, 243, 255, 0.90));
  border: 1px solid rgba(148, 163, 184, 0.16);
}
.composer-toolbar {
  padding: 8px 12px 0 0;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}
.composer-main textarea {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 255, 0.92));
}
.thread-bubble.assistant {
  background:
    linear-gradient(180deg, rgba(233, 239, 255, 0.92), rgba(247, 250, 255, 0.98));
}
.badge.info {
  background: rgba(79, 70, 229, 0.10);
  border-color: rgba(79, 70, 229, 0.20);
}
@media (max-width: 720px) {
  .workspace-shell-head,
  .workspace-card.ai-workspace,
  .composer-frame,
  .command-panel,
  .drawer-panel .tree-card,
  .drawer-panel .side-panel,
  .starter-card {
    border-radius: 22px;
  }
  .premium-home-landing,
  .workspace-card.ai-workspace { padding: 20px; }
  .composer-main textarea { min-height: 260px; }
  .hero-mini-card strong { font-size: 22px; }
}


/* v0.6.2 atelier refinement */
:root {
  --bg: #f2efe9;
  --panel: rgba(255, 255, 255, 0.94);
  --panel-soft: rgba(252, 249, 244, 0.96);
  --panel-muted: rgba(248, 244, 238, 0.94);
  --line: rgba(90, 76, 60, 0.12);
  --line-strong: rgba(70, 80, 120, 0.18);
  --text: #18161c;
  --muted: #5c6372;
  --muted-2: #8c93a3;
  --shadow: 0 26px 80px rgba(28, 26, 32, 0.10);
  --shadow-soft: 0 12px 34px rgba(28, 26, 32, 0.06);
  --accent-weak: rgba(65, 88, 208, 0.08);
  --accent-line: rgba(65, 88, 208, 0.18);
}
html {
  background:
    radial-gradient(1100px 520px at 0% 0%, rgba(212, 208, 247, 0.32), transparent 62%),
    radial-gradient(820px 460px at 100% 0%, rgba(214, 232, 244, 0.22), transparent 58%),
    #f2efe9;
}
body {
  background:
    radial-gradient(1200px 540px at 100% 0%, rgba(214, 230, 255, 0.14), transparent 58%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.35), rgba(242, 239, 233, 0.70));
}
h1,
.atelier-title-stack h1,
.atelier-composer-head h3,
.atelier-output-head h2 {
  font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
  letter-spacing: -0.04em;
}
.brand,
.atelier-title-stack .eyebrow,
.review-card strong,
.context-pill strong,
.hero-mini-card strong {
  text-rendering: geometricPrecision;
}
.project-topbar {
  padding: 14px 18px;
  border-radius: 22px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background: rgba(255, 255, 255, 0.60);
  box-shadow: 0 10px 28px rgba(28, 26, 32, 0.05);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}
.tabs {
  gap: 10px;
  padding: 4px 0 2px;
}
.tabs .tab {
  background: rgba(255, 255, 255, 0.64);
  border-color: rgba(90, 76, 60, 0.10);
}
.tabs .tab.active-tab {
  background: rgba(255, 255, 255, 0.96);
  color: #31406f;
  border-color: rgba(65, 88, 208, 0.16);
  box-shadow: 0 6px 16px rgba(65, 88, 208, 0.08);
}
.workspace-shell-head.atelier-shell-head {
  position: relative;
  overflow: hidden;
  padding: 22px 24px 18px;
  border-radius: 30px;
  border: 1px solid rgba(255, 255, 255, 0.72);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(247, 242, 235, 0.88));
  box-shadow: 0 22px 72px rgba(28, 26, 32, 0.10);
}
.workspace-shell-head.atelier-shell-head::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(480px 220px at 0% 0%, rgba(110, 116, 212, 0.10), transparent 58%),
    radial-gradient(420px 180px at 100% 0%, rgba(117, 177, 208, 0.12), transparent 58%);
  pointer-events: none;
}
.atelier-header-grid,
.atelier-nav-foot,
.workspace-title-line,
.atelier-output-head {
  position: relative;
  z-index: 1;
}
.atelier-title-stack {
  display: grid;
  gap: 4px;
}
.atelier-title-stack h1 {
  font-size: 42px;
  line-height: 0.98;
  max-width: 13ch;
}
.atelier-title-stack .eyebrow {
  color: #4a5bb2;
}
.atelier-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.workspace-hero-panel.atelier-status-strip {
  gap: 10px;
  margin-top: 16px;
  position: relative;
  z-index: 1;
}
.stat-mini-card {
  border-radius: 20px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background: rgba(255, 255, 255, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.84);
}
.atelier-nav-foot {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}
.module-pills {
  gap: 8px;
}
.module-pill {
  background: rgba(255, 255, 255, 0.72);
  border-color: rgba(90, 76, 60, 0.10);
  color: #556072;
}
.module-pill.active {
  background: rgba(255, 255, 255, 0.98);
  border-color: rgba(65, 88, 208, 0.18);
  color: #31406f;
  box-shadow: 0 8px 22px rgba(65, 88, 208, 0.08);
}
.workspace-card.atelier-workspace {
  padding: 26px;
  border-radius: 32px;
  border: 1px solid rgba(255, 255, 255, 0.78);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(246, 241, 235, 0.88));
  box-shadow: 0 28px 86px rgba(28, 26, 32, 0.10);
}
.workspace-title-line h2,
.atelier-output-head h2 {
  font-size: 32px;
  line-height: 1.02;
}
.editor-context-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 12px;
  margin-top: 4px;
}
.context-pill {
  padding: 14px 16px;
  border-radius: 20px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background: rgba(251, 248, 243, 0.86);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}
.context-pill span,
.review-label {
  display: block;
  margin-bottom: 8px;
  font-size: 11px;
  letter-spacing: .10em;
  text-transform: uppercase;
  color: var(--muted-2);
  font-weight: 800;
}
.context-pill strong {
  display: block;
  font-size: 14px;
  line-height: 1.62;
  font-weight: 700;
  color: var(--text);
}
.context-pill-compact strong {
  white-space: nowrap;
}
.atelier-composer-frame {
  gap: 18px;
  padding: 26px;
  border-radius: 32px;
  border: 1px solid rgba(255, 255, 255, 0.80);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(250, 247, 241, 0.94));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.86),
    0 18px 52px rgba(28, 26, 32, 0.08);
}
.atelier-composer-head {
  padding: 0;
  background: transparent;
  border: 0;
}
.atelier-composer-head h3 {
  margin-top: 4px;
  font-size: 34px;
  line-height: 1.02;
  max-width: 16ch;
}
.atelier-composer-head .helper-text {
  max-width: 62ch;
}
.slash-hints {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
}
.slash-hints span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background: rgba(255, 255, 255, 0.72);
}
.composer-main {
  gap: 12px;
}
.composer-main textarea {
  min-height: 360px;
  padding: 24px 24px 28px;
  border-radius: 28px;
  border: 1px solid rgba(90, 76, 60, 0.12);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(252, 249, 245, 0.96));
  font-size: 17px;
  line-height: 1.92;
  color: #15151c;
}
.atelier-details {
  background: rgba(250, 247, 241, 0.80);
  border-color: rgba(90, 76, 60, 0.10);
}
.atelier-toolbar {
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid rgba(90, 76, 60, 0.10);
}
.atelier-toolbar .action-row { margin-top: 0; }
.autosave-status {
  background: rgba(255, 255, 255, 0.80);
  border-color: rgba(90, 76, 60, 0.10);
}
.atelier-output {
  gap: 18px;
  padding-top: 24px;
  border-top: 1px solid rgba(90, 76, 60, 0.10);
}
.artifact-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.artifact-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background: rgba(255, 255, 255, 0.68);
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}
.artifact-tab.active {
  background: rgba(255, 255, 255, 0.98);
  border-color: rgba(65, 88, 208, 0.18);
  color: #31406f;
  box-shadow: 0 8px 20px rgba(65, 88, 208, 0.08);
}
.artifact-board {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 288px;
  gap: 16px;
  align-items: flex-start;
}
.artifact-main {
  min-width: 0;
  display: grid;
  gap: 14px;
}
.artifact-side {
  display: grid;
  gap: 12px;
}
.review-card {
  padding: 16px 16px 18px;
  border-radius: 22px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background: rgba(250, 247, 241, 0.86);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}
.review-card strong {
  display: block;
  margin-bottom: 8px;
  font-size: 16px;
  line-height: 1.42;
  color: var(--text);
}
.review-card p {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--muted);
}
.atelier-thread {
  gap: 18px;
}
.atelier-thread .thread-bubble.user {
  margin-right: 7%;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(250, 247, 242, 0.94));
}
.atelier-thread .thread-bubble.assistant {
  margin-left: 0;
  background:
    linear-gradient(180deg, rgba(240, 241, 255, 0.94), rgba(252, 250, 245, 0.98));
  border-color: rgba(65, 88, 208, 0.14);
}
.atelier-thread .thread-content .markdown-preview {
  min-height: 340px;
  max-height: none;
  padding: 22px 22px 26px;
  border-radius: 26px;
  border: 1px solid rgba(90, 76, 60, 0.10);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(251, 248, 242, 0.90));
  line-height: 1.9;
}
.atelier-thread .prompt-summary {
  font-size: 15px;
  line-height: 1.8;
}
.thread-role {
  color: #6f7690;
  letter-spacing: .04em;
}
.file-chip,
.badge,
.module-pill,
.mode-pill,
.button,
button {
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.drawer-panel {
  top: 92px;
}
.drawer-panel .tree-card,
.drawer-panel .side-panel {
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(249, 245, 239, 0.88));
  border-color: rgba(255, 255, 255, 0.72);
  box-shadow: 0 24px 72px rgba(28, 26, 32, 0.14);
}
.command-panel {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(250, 247, 241, 0.92));
  border-color: rgba(255, 255, 255, 0.74);
}

.slim-project-topbar {
  padding: 0 0 10px;
  margin-bottom: 12px;
  background: transparent;
  border: 0;
  box-shadow: none;
}
.project-home-shell {
  padding: 28px 30px;
  border-radius: 28px;
  margin-bottom: 18px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 245, 240, 0.92));
  border-color: rgba(226, 232, 240, 0.78);
  box-shadow: 0 22px 60px rgba(15, 23, 42, 0.06);
}
.project-home-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
}
.project-home-subtitle {
  max-width: 760px;
  margin-top: 12px;
}
.project-home-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.project-home-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 24px;
}
.project-metric {
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.74);
}
.project-metric span {
  display: block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted-2);
  margin-bottom: 8px;
  font-weight: 800;
}
.project-metric strong {
  display: block;
  font-size: 22px;
  line-height: 1.2;
  letter-spacing: -0.02em;
}
.project-metric small {
  display: block;
  margin-top: 8px;
  color: var(--muted);
  line-height: 1.5;
}
.project-home-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.34fr) 320px;
  gap: 18px;
}
.project-home-main,
.project-home-side {
  display: grid;
  gap: 16px;
}
.project-home-section,
.project-home-sidecard {
  padding: 20px;
  border-radius: 22px;
}
.module-home-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.module-home-card {
  padding: 18px;
  border-radius: 20px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 10px 32px rgba(15, 23, 42, 0.04);
}
.module-home-card.current {
  border-color: #bfdbfe;
  box-shadow: 0 16px 40px rgba(37, 99, 235, 0.10);
}
.module-home-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.module-home-kicker {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted-2);
  margin-bottom: 8px;
  font-weight: 800;
}
.module-home-card h3 {
  font-size: 20px;
  line-height: 1.25;
}
.module-home-progress {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--text);
}
.module-home-meta {
  margin-top: 10px;
  color: var(--muted);
  font-size: 13px;
}
.module-home-actions {
  margin-top: 14px;
}
.project-home-lower {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.project-home-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 12px;
}
.project-home-list li {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}
.project-home-list li:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}
.project-home-list li span {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}
.work-masthead {
  padding: 18px 20px;
  margin-bottom: 16px;
  border-radius: 20px;
}
.work-masthead-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}
.work-masthead-main h1 {
  font-size: 28px;
}
.work-masthead-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.work-shell-nav {
  gap: 8px;
}
.work-shell-nav .home-link {
  background: var(--text);
  color: #fff;
  border-color: var(--text);
}
.work-shell-nav .ghost-link {
  background: transparent;
  color: var(--muted);
}
.work-step-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 13px;
}
.compact-workspace-actions .button {
  min-width: 84px;
}
.quiet-hints {
  color: var(--muted-2);
}
.result-stage,
.editor-output.atelier-output {
  margin-top: 14px;
}
.editor-output.atelier-output .artifact-board {
  margin-top: 14px;
}
.editor-output.atelier-output .thread-role {
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: .08em;
}
@media (max-width: 1180px) {
  .artifact-board {
    grid-template-columns: 1fr;
  }
  .artifact-side {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .project-home-grid {
    grid-template-columns: 1fr;
  }
  .project-home-metrics,
  .module-home-grid,
  .project-home-lower {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 900px) {
  .atelier-nav-foot,
  .editor-context-band {
    grid-template-columns: 1fr;
  }
  .atelier-title-stack h1,
  .atelier-output-head h2 {
    font-size: 34px;
  }
  .atelier-composer-head h3 {
    font-size: 30px;
  }
  .composer-main textarea {
    min-height: 300px;
  }
  .project-home-hero,
  .work-masthead-row,
  .work-masthead-foot {
    flex-direction: column;
    align-items: flex-start;
  }
  .project-home-metrics,
  .module-home-grid,
  .project-home-lower {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 720px) {
  .artifact-side {
    grid-template-columns: 1fr;
  }
  .workspace-shell-head.atelier-shell-head,
  .workspace-card.atelier-workspace,
  .atelier-composer-frame,
  .review-card {
    border-radius: 24px;
  }
}


/* goal clarity refinement */
:root {
  --bg: #f6f5f3;
  --panel: #fffdfa;
  --panel-soft: #fbf8f3;
  --panel-muted: #f6f1ea;
  --line: rgba(62, 72, 96, 0.10);
  --line-strong: rgba(47, 67, 132, 0.18);
  --text: #171b25;
  --muted: #5d6574;
  --muted-2: #8a92a3;
  --shadow: 0 18px 48px rgba(16, 24, 40, 0.06);
  --shadow-soft: 0 10px 24px rgba(16, 24, 40, 0.04);
  --accent-weak: rgba(52, 76, 160, 0.08);
  --accent-line: rgba(52, 76, 160, 0.16);
}
html {
  background:
    radial-gradient(900px 420px at 0% 0%, rgba(203, 214, 255, 0.20), transparent 62%),
    radial-gradient(820px 420px at 100% 0%, rgba(222, 233, 248, 0.16), transparent 58%),
    #f6f5f3;
}
body {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.62), rgba(246, 245, 243, 0.92));
}
.goal-home-shell {
  padding: 30px 32px;
  border-radius: 26px;
  border: 1px solid rgba(255, 255, 255, 0.84);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(250, 247, 241, 0.94));
  box-shadow: 0 22px 58px rgba(15, 23, 42, 0.06);
}
.goal-home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 24px;
  align-items: start;
}
.goal-home-copy h1 {
  font-size: 54px;
  line-height: 0.96;
  max-width: 12ch;
}
.goal-home-actions {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.goal-home-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}
.goal-mini {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.84);
}
.goal-mini span,
.goal-spotlight-label {
  display: block;
  font-size: 11px;
  letter-spacing: .10em;
  text-transform: uppercase;
  color: var(--muted-2);
  font-weight: 800;
}
.goal-mini strong {
  display: block;
  margin-top: 6px;
  font-size: 22px;
  line-height: 1.08;
}
.goal-mini small {
  display: block;
  margin-top: 8px;
  font-size: 13px;
  color: var(--muted);
}
.goal-home-summary {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.95fr);
  gap: 16px;
  margin-top: 18px;
}
.goal-spotlight,
.goal-summary-card {
  border-radius: 22px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.88);
}
.goal-spotlight {
  padding: 22px 24px 24px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.goal-spotlight h2 {
  margin: 10px 0 8px;
  font-size: 36px;
  line-height: 1.04;
}
.goal-spotlight p {
  margin: 0 0 14px;
  max-width: 62ch;
  font-size: 15px;
  line-height: 1.86;
  color: var(--muted);
}
.goal-summary-stack {
  display: grid;
  gap: 14px;
}
.goal-summary-card {
  padding: 18px 20px;
}
.goal-summary-card h3 {
  margin: 8px 0 8px;
  font-size: 20px;
  line-height: 1.25;
}
.goal-summary-card p {
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: var(--muted);
}
.clarity-home-grid {
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 18px;
}
.route-card-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.route-card-grid .module-home-card {
  border-radius: 20px;
  border-color: var(--line);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: none;
}
.route-card-grid .module-home-card.current {
  border-color: var(--accent-line);
  box-shadow: 0 10px 24px rgba(52, 76, 160, 0.08);
}
.route-card-grid .module-home-card h3 {
  font-size: 24px;
}
.side-list-card ul {
  margin-top: 0;
}
.project-home-sidecard p,
.project-home-list li span {
  color: var(--muted);
}
.clarity-work-head {
  padding: 18px 22px 16px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.84);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(249, 246, 240, 0.94));
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.05);
}
.clarity-head-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.clarity-title-block {
  display: grid;
  gap: 6px;
}
.clarity-title-block h1 {
  font-size: 40px;
  line-height: 0.98;
  max-width: 15ch;
}
.clarity-route {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  font-size: 13px;
  color: var(--muted);
}
.clarity-head-foot {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.singletrack-workspace {
  padding: 24px;
  border-radius: 30px;
  border: 1px solid rgba(255, 255, 255, 0.86);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.97), rgba(248, 245, 239, 0.94));
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.07);
}
.clarity-context-strip {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.clarity-composer-frame {
  padding: 24px;
  border-radius: 24px;
  gap: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.97), rgba(250, 247, 242, 0.95));
}
.clarity-composer-head h3 {
  font-size: 32px;
  line-height: 1.04;
  max-width: 14ch;
}
.clarity-toolbar {
  padding-top: 14px;
}
.clarity-output {
  padding-top: 22px;
}
.artifact-summary-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.artifact-summary-bar h2 {
  margin: 0;
  font-size: 30px;
  line-height: 1.02;
}
.clarity-artifact-board {
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 16px;
}
.result-summary-card {
  background: rgba(255, 255, 255, 0.9);
}
.result-summary-card strong {
  font-size: 17px;
  line-height: 1.42;
}
.thread-bubble.user .thread-role,
.thread-bubble.assistant .thread-role {
  letter-spacing: .08em;
}
.drawer-panel .tree-card,
.drawer-panel .side-panel {
  border-radius: 24px;
}
@media (max-width: 1180px) {
  .goal-home-strip,
  .route-card-grid,
  .clarity-artifact-board {
    grid-template-columns: 1fr 1fr;
  }
  .goal-home-summary,
  .clarity-home-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 900px) {
  .goal-home-hero,
  .clarity-head-main,
  .clarity-head-foot,
  .artifact-summary-bar {
    grid-template-columns: 1fr;
    display: grid;
  }
  .goal-home-copy h1,
  .clarity-title-block h1 {
    font-size: 38px;
  }
  .goal-home-strip,
  .route-card-grid,
  .clarity-context-strip,
  .clarity-artifact-board {
    grid-template-columns: 1fr;
  }
}

/* product launchpad refinement */
.mission-home-shell {
  padding: 28px 30px;
  border-radius: 28px;
  border: 1px solid rgba(255,255,255,0.86);
  background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(247,244,238,0.95));
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.06);
}
.mission-home-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
  gap: 24px;
  align-items: start;
}
.mission-home-copy h1 { font-size: 52px; line-height: 0.96; max-width: 12ch; }
.mission-home-actions { display: grid; gap: 12px; justify-items: start; }
.mission-cta-note { font-size: 13px; line-height: 1.8; color: var(--muted); max-width: 30ch; }
.mission-home-rail {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}
.mission-home-board {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.9fr);
  gap: 16px;
  margin-top: 18px;
}
.mission-spotlight {
  padding: 24px 24px 22px;
  border-radius: 24px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.90);
}
.mission-spotlight h2 { margin: 10px 0 10px; font-size: 36px; line-height: 1.02; }
.mission-spotlight p { margin: 0 0 16px; font-size: 15px; line-height: 1.85; color: var(--muted); }
.mission-loop {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.mission-loop-card {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: rgba(248,245,239,0.92);
}
.mission-loop-card span {
  display: block;
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted-2);
  font-weight: 800;
}
.mission-loop-card strong { display: block; margin-top: 8px; font-size: 15px; line-height: 1.65; }
.mission-side-stack { display: grid; gap: 14px; }
.mission-launchpad-grid { grid-template-columns: minmax(0, 1fr) 340px; gap: 18px; }
.route-list-grid { display: grid; gap: 12px; }
.route-row {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(180px, 0.7fr) auto;
  gap: 16px;
  align-items: center;
  padding: 18px;
  border-radius: 22px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,0.84);
}
.route-row.current {
  border-color: var(--accent-line);
  background: linear-gradient(180deg, rgba(244,248,255,0.96), rgba(255,255,255,0.88));
  box-shadow: 0 14px 28px rgba(52, 76, 160, 0.08);
}
.route-row-main h3 { margin: 4px 0 6px; font-size: 26px; line-height: 1.04; }
.route-row-main p { margin: 0; color: var(--muted); line-height: 1.75; }
.route-row-meta { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }
.route-row-meta strong { color: var(--text); }
.mission-work-head {
  padding: 18px 22px 16px;
  border-radius: 24px;
  border: 1px solid rgba(255,255,255,0.86);
  background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(247,244,238,0.94));
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.05);
}
.mission-work-bar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.mission-workspace {
  padding: 24px;
  border-radius: 30px;
  border: 1px solid rgba(255,255,255,0.86);
  background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(248,245,239,0.95));
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.07);
}
.mission-title-line h2, .mission-artifact-bar h2 { margin: 0; font-size: 30px; line-height: 1.02; }
.mission-context-strip { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.mission-composer-frame {
  padding: 24px;
  border-radius: 24px;
  gap: 16px;
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(250,247,242,0.95));
}
.mission-composer-head h3 { font-size: 32px; line-height: 1.04; max-width: 14ch; }
.mission-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 14px; }
.mission-output { padding-top: 22px; }
.mission-artifact-board { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 16px; }
.artifact-canvas {
  border-radius: 24px;
  border: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(255,255,255,0.97), rgba(248,245,239,0.92));
  overflow: hidden;
}
.artifact-canvas-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
}
.artifact-canvas-body { padding: 20px 22px 22px; }
.artifact-preview {
  margin: 0;
  background: transparent;
  border: 0;
  padding: 0;
  max-height: none;
  line-height: 1.88;
}
.artifact-prompt-fold { margin-top: 14px; }
.prompt-evidence { margin-top: 10px; }
.mission-review-side { display: grid; gap: 12px; }
@media (max-width: 1180px) {
  .mission-home-hero,
  .mission-home-board,
  .mission-launchpad-grid,
  .mission-artifact-board { grid-template-columns: 1fr; }
  .mission-home-rail,
  .mission-loop,
  .mission-context-strip,
  .route-row { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .mission-work-bar,
  .mission-toolbar { flex-direction: column; align-items: flex-start; }
  .mission-home-copy h1,
  .mission-work-copy h1 { font-size: 40px; }
}

/* v0.6.5 silent power refinement */
.quiet-launch-shell {
  background: linear-gradient(180deg, rgba(255,255,255,0.985), rgba(250,248,244,0.97));
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.05);
}
.quiet-launch-hero { gap: 20px; }
.quiet-launch-actions { align-content: start; }
.quiet-launch-rail .goal-mini,
.quiet-launch-shell .mission-summary-card,
.launch-route-fold,
.quiet-files-panel .section-toggle,
.route-switcher,
.artifact-actions-details {
  border-radius: 20px;
  border: 1px solid rgba(214, 219, 230, 0.92);
  background: rgba(255,255,255,0.9);
}
.quiet-launch-spotlight {
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(252,249,244,0.96));
}
.quiet-launch-loop .mission-loop-card {
  background: rgba(248, 249, 252, 0.9);
}
.quiet-launch-grid {
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 16px;
}
.quiet-launch-main,
.quiet-launch-aside {
  display: grid;
  gap: 14px;
}
.launch-route-fold > summary {
  font-size: 15px;
  font-weight: 800;
}
.quiet-work-head {
  padding: 14px 18px 13px;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.04);
}
.quiet-work-foot {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-top: 12px;
}
.route-switcher {
  min-width: 180px;
}
.route-switcher > summary {
  font-size: 14px;
  font-weight: 800;
}
.route-switch-grid {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.route-switch-grid .module-pill {
  width: 100%;
  justify-content: center;
}
.inline-home-link {
  color: var(--text);
  text-decoration: none;
  font-weight: 700;
}
.inline-home-link:hover { text-decoration: underline; }
.quiet-title-line {
  padding-bottom: 6px;
}
.quiet-workspace {
  background: linear-gradient(180deg, rgba(255,255,255,0.985), rgba(251,249,245,0.97));
}
.quiet-toolbar {
  padding-top: 16px;
  border-top: 1px solid rgba(214, 219, 230, 0.7);
}
.quiet-toolbar .autosave-status {
  font-weight: 600;
}
.quiet-artifact-bar {
  align-items: flex-start;
}
.artifact-actions-details {
  margin-top: 14px;
}
.artifact-actions-details > summary,
.artifact-review-fold > summary {
  font-weight: 800;
}
.quiet-artifact-side {
  display: grid;
  gap: 12px;
  align-content: start;
}
.emphasis-review-card {
  background: linear-gradient(180deg, rgba(247,249,255,0.96), rgba(255,255,255,0.93));
  border: 1px solid rgba(186, 201, 242, 0.86);
}
.quiet-files-panel {
  gap: 14px;
}
.quiet-files-panel > .helper-text {
  margin-bottom: 8px;
}
@media (max-width: 1180px) {
  .quiet-launch-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .quiet-work-foot { flex-direction: column; }
  .route-switcher { width: 100%; }
}

/* v0.6.5 layout polish */
.project-home-grid,
.mission-home-board,
.quiet-launch-grid {
  align-items: start;
}
.project-home-side,
.mission-home-side,
.quiet-launch-aside {
  align-content: start;
  grid-auto-rows: max-content;
  align-self: start;
}
.route-list-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}
.route-row-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
}
@media (max-width: 900px) {
  .route-row-actions {
    justify-content: flex-start;
  }
}

/* v0.6.5 simplified surface */
:root {
  --bg: #f7f6f3;
  --panel: #ffffff;
  --panel-soft: #fbfaf7;
  --panel-muted: #f6f4ef;
  --line: #e8e5de;
  --line-strong: #ddd8cf;
  --text: #171717;
  --muted: #66645d;
  --muted-2: #908b81;
  --shadow: 0 4px 18px rgba(15, 23, 42, 0.04);
  --shadow-soft: 0 1px 6px rgba(15, 23, 42, 0.03);
  --accent-weak: #f2f5ff;
  --accent-line: #d8e1ff;
}
body {
  background: var(--bg);
  color: var(--text);
}
.app {
  grid-template-columns: 280px minmax(0, 1fr);
}
.sidebar {
  padding: 20px;
  background: rgba(255, 255, 255, 0.74);
  border-right: 1px solid var(--line);
}
.main {
  max-width: 1340px;
  padding: 22px 24px 40px;
}
.card,
.metric-card,
.continue-card,
.note-card,
.project-link,
.hero-side,
.stack-card,
.drawer-panel .tree-card,
.drawer-panel .side-panel,
.command-panel {
  background: var(--panel);
  border-color: var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow-soft);
}
.card {
  padding: 18px;
  margin-bottom: 14px;
}
button,
.button,
.mode-pill,
.module-pill,
.tab {
  border-radius: 11px;
  font-weight: 700;
}
button,
.button {
  padding: 10px 14px;
}
.mode-pill,
.module-pill,
.tab {
  padding: 8px 12px;
  background: #fff;
  border-color: var(--line);
}
.mode-pill.active,
.module-pill.active,
.tab.active-tab {
  background: var(--panel-muted);
  border-color: var(--line-strong);
  color: var(--text);
  box-shadow: none;
}
.badge {
  padding: 5px 9px;
  border-radius: 999px;
  background: var(--panel-muted);
  border-color: var(--line);
  color: var(--muted);
  font-weight: 700;
}
.badge.info {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.18);
  color: #355dce;
}
.badge.ok {
  background: rgba(22, 101, 52, 0.08);
  border-color: rgba(22, 101, 52, 0.18);
  color: #166534;
}
.badge.warn {
  background: rgba(180, 83, 9, 0.08);
  border-color: rgba(180, 83, 9, 0.18);
  color: #9a5a10;
}
input,
select,
textarea {
  border-radius: 12px;
  background: #fff;
  border: 1px solid var(--line);
}
textarea {
  line-height: 1.65;
}
.section-toggle,
.inline-details,
.admin-toggle {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
}
.section-toggle > summary,
.inline-details > summary,
.admin-toggle > summary {
  padding: 14px 16px;
}

.project-home-shell.minimal-home-shell {
  padding: 22px;
}
.minimal-home-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: start;
  margin-bottom: 18px;
}
.minimal-home-actions {
  align-items: flex-start;
}
.minimal-home-actions .chip-row {
  margin: 0 0 2px;
}
.minimal-home-strip {
  margin: 0 0 18px;
}
.minimal-home-strip .goal-mini {
  background: var(--panel-muted);
  border: 1px solid var(--line);
  border-radius: 13px;
  padding: 14px 16px;
}
.minimal-home-focus {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
  display: grid;
  gap: 16px;
}
.minimal-home-focus-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.minimal-home-focus h2 {
  font-size: 26px;
}
.minimal-home-summary-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.minimal-home-summary-row .mission-loop-card {
  background: var(--panel-muted);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px;
  box-shadow: none;
}
.focus-summary-note {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
  color: var(--muted);
}
.focus-summary-note strong {
  color: var(--text);
  font-size: 14px;
}
.simplified-home-grid,
.project-home-grid {
  grid-template-columns: 1fr;
  gap: 14px;
}
.route-row {
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: none;
  gap: 14px;
}
.route-row.current {
  border-color: var(--line-strong);
  background: var(--panel-soft);
}
.route-row-main h3 {
  font-size: 18px;
  margin-bottom: 6px;
}

.work-masthead.minimal-work-head {
  padding: 18px;
}
.minimal-work-foot {
  align-items: flex-end;
  gap: 16px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.minimal-route-switcher {
  display: grid;
  gap: 10px;
}
.route-switch-label {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--muted-2);
}
.route-switch-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.route-switch-grid .module-pill {
  width: auto;
  justify-content: center;
  background: var(--panel);
}
.simplified-workspace {
  padding: 18px;
}
.simplified-workspace > .workspace-title-line {
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.minimal-context-strip {
  gap: 10px;
  margin-bottom: 14px;
}
.minimal-context-strip .context-pill {
  background: var(--panel-muted);
  border-color: var(--line);
  border-radius: 12px;
  padding: 14px 15px;
}
.minimal-composer-frame {
  background: var(--panel-soft);
  border-color: var(--line);
  border-radius: 14px;
  gap: 12px;
  padding: 16px;
}
.attachment-strip {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.76);
}
.attachment-strip-label {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: var(--muted-2);
}
.file-chip {
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  background: var(--panel-muted);
  border: 1px solid var(--line);
  color: var(--muted);
}
.file-chip.ok {
  background: rgba(22, 101, 52, 0.08);
  border-color: rgba(22, 101, 52, 0.18);
  color: #166534;
}
.file-chip.info {
  background: rgba(37, 99, 235, 0.08);
  border-color: rgba(37, 99, 235, 0.18);
  color: #355dce;
}
.minimal-toolbar {
  padding-top: 12px;
  border-top: 1px solid var(--line);
}
.minimal-toolbar .autosave-status {
  font-weight: 600;
  color: var(--muted);
}
.minimal-artifact-bar {
  padding-top: 2px;
  margin-top: 8px;
}
.minimal-artifact-board {
  grid-template-columns: minmax(0, 1.5fr) minmax(300px, .78fr);
  gap: 14px;
  align-items: start;
}
.artifact-canvas {
  border-radius: 14px;
  border: 1px solid var(--line);
  background: #fff;
  min-height: 360px;
}
.artifact-canvas-head {
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-soft);
}
.artifact-preview {
  padding: 16px;
  min-height: 280px;
}
.minimal-artifact-side {
  display: grid;
  gap: 12px;
  align-content: start;
}
.summary-stack-card {
  display: grid;
  gap: 0;
  padding: 0;
  overflow: hidden;
}
.summary-stack-row {
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
.summary-stack-row:last-child {
  border-bottom: 0;
}
.summary-stack-row strong {
  display: block;
  margin: 6px 0 4px;
}
.summary-stack-row p {
  font-size: 13px;
  line-height: 1.6;
}
.drawer-panel {
  top: 74px;
  width: min(400px, calc(100vw - 32px));
}
.drawer-panel .tree-card,
.drawer-panel .side-panel {
  box-shadow: var(--shadow);
  border-radius: 16px;
}

.control-subtabs {
  gap: 6px;
  margin: 0 0 12px;
}
.control-subtabs .tab {
  background: transparent;
}
.minimal-control-head {
  margin-bottom: 14px;
}
.minimal-control-focus .focus-lane {
  gap: 12px;
}
.minimal-control-focus .focus-node {
  background: var(--panel-muted);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px;
}
.simple-run-modes .simple-copy-stack {
  display: grid;
  gap: 12px;
}

.project-strip,
.control-focus-card,
.workspace-shell-head,
.workspace-card.ai-workspace,
.mission-spotlight,
.route-row,
.drawer-panel .tree-card,
.drawer-panel .side-panel,
.command-panel {
  box-shadow: none;
}

@media (max-width: 1180px) {
  .minimal-home-head,
  .minimal-artifact-board,
  .clarity-head-foot.minimal-work-foot {
    display: grid;
    grid-template-columns: 1fr;
  }
  .minimal-home-focus-top {
    display: grid;
  }
  .minimal-home-summary-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .app {
    grid-template-columns: 1fr;
  }
  .sidebar {
    position: static;
    min-height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .main,
  .sidebar {
    padding: 16px;
  }
  .minimal-home-head,
  .minimal-artifact-board {
    grid-template-columns: 1fr;
  }
  .minimal-work-foot {
    align-items: stretch;
  }
  .focus-summary-note {
    display: grid;
  }
}

"""

def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)



def _normalize_state(raw: dict[str, str] | None = None, initial_project: str | None = None) -> dict[str, str | None]:
    data = raw or {}
    state = {key: (data.get(key, "") or "").strip() or None for key in STATE_KEYS}
    state["project"] = state["project"] or initial_project or None
    legacy_tab = state.get("tab")
    if legacy_tab == "studio":
        legacy_tab = "paper"
    elif legacy_tab == "library":
        legacy_tab = "control"
    elif legacy_tab == "overview":
        legacy_tab = "project"
    if state["project"]:
        state["tab"] = legacy_tab or "project"
    else:
        state["tab"] = legacy_tab or None
    state["mode"] = "advanced" if state.get("mode") == "advanced" else "guided"
    return state

def _build_url(state: dict[str, str | None], **updates: str | None) -> str:
    params: dict[str, str] = {}
    for key in STATE_KEYS:
        value = updates[key] if key in updates else state.get(key)
        if value:
            params[key] = str(value)
    encoded = urlencode(params)
    return f"/?{encoded}" if encoded else "/"



def _button(
    label: str,
    action: str,
    state: dict[str, str | None] | None = None,
    project_dir: str | None = None,
    extra: dict[str, str | None] | None = None,
    button_class: str = "",
    confirm_text: str | None = None,
) -> str:
    fields: list[str] = [f'<input type="hidden" name="action" value="{_escape(action)}">']
    current_state = state or {}
    for key in STATE_KEYS:
        value = current_state.get(key)
        if key == "project" and project_dir:
            value = project_dir
        if value:
            field_name = "project" if key == "project" else key
            fields.append(f'<input type="hidden" name="{_escape(field_name)}" value="{_escape(value)}">')
    if project_dir:
        fields.append(f'<input type="hidden" name="project_dir" value="{_escape(project_dir)}">')
    for key, value in (extra or {}).items():
        if value is None:
            continue
        fields.append(f'<input type="hidden" name="{_escape(key)}" value="{_escape(value)}">')
    cls = f' class="{button_class}"' if button_class else ""
    onclick = ""
    if confirm_text:
        js_literal = html.escape(json.dumps(confirm_text, ensure_ascii=False), quote=True)
        onclick = f' onclick="return confirm({js_literal})"'
    return f'<form method="post" action="/action" class="inline-form">{"".join(fields)}<button{cls}{onclick}>{_escape(label)}</button></form>'



def _badge(label: str, tone: str = "neutral") -> str:
    return f'<span class="badge {tone}">{_escape(label)}</span>'

def _apply_surface_choice(data: dict[str, str], *, force: str | None = None) -> dict[str, str]:
    payload = dict(data)
    choice = (force or payload.get('surface_choice') or '').strip().lower()
    if choice == 'chatgpt':
        payload['provider_mode'] = 'manual_web'
        payload['provider_profile_id'] = 'chatgpt-web'
        payload['provider_name'] = 'manual_web'
        payload['model_hint'] = payload.get('model_hint') or 'ChatGPT Web'
        payload['web_target'] = 'chatgpt'
    elif choice == 'gemini':
        payload['provider_mode'] = 'manual_web'
        payload['provider_profile_id'] = 'gemini-web'
        payload['provider_name'] = 'manual_web'
        payload['model_hint'] = payload.get('model_hint') or 'Gemini Web'
        payload['web_target'] = 'gemini'
    elif choice == 'inline':
        payload['provider_mode'] = 'openai_api'
        payload['provider_profile_id'] = payload.get('provider_profile_id') or 'openai-default'
        payload['provider_name'] = payload.get('provider_name') or 'openai'
        payload['model_hint'] = payload.get('model_hint') or 'gpt-4.1-mini'
    elif choice == 'mock':
        payload['provider_mode'] = 'mock'
        payload['provider_profile_id'] = 'mock-local'
        payload['provider_name'] = 'mock'
        payload['model_hint'] = 'mock'
    return payload


def _save_step_with_surface_choice(workspace: WorkspaceSnapshot, step_id: str, data: dict[str, str], *, force: str | None = None) -> dict:
    payload = _apply_surface_choice(data, force=force)
    update_step_from_form(workspace.studio, step_id, payload)
    return find_step(workspace.studio, step_id)



def _health_tone(health: dict) -> str:
    state = health.get("state", "healthy")
    return {
        "healthy": "ok",
        "needs_decision": "info",
        "active": "info",
        "needs_attention": "warn",
        "needs_repair": "bad",
    }.get(state, "neutral")



def _task_status_title(status: str | None) -> str:
    return TASK_STATUS_LABELS.get(status or "todo", status or "待开始")



def _task_priority_rank(priority: str | None) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "critical": 0, "high": 1, "normal": 2, "low": 3}.get(priority or "normal", 4)



def _task_sort_key(task: dict) -> tuple[int, int, int, str]:
    stage = task.get("stage")
    return (
        0 if task.get("status") != "done" else 1,
        STAGE_SEQUENCE.index(stage) if stage in STAGE_SEQUENCE else len(STAGE_SEQUENCE),
        _task_priority_rank(task.get("priority")),
        task.get("title", ""),
    )



def _run_sort_key(run: dict) -> tuple[int, float]:
    from .common import parse_iso

    for key in ["ended_at", "started_at", "queued_at", "created_at"]:
        value = parse_iso(run.get(key))
        if value is not None:
            return (1, value.timestamp())
    return (0, 0.0)



def _render_project_selector(projects: list[dict], state: dict[str, str | None]) -> str:
    if not projects:
        return '<div class="empty">还没有检测到项目。先创建一个项目，再进入科研助手首页。</div>'

    cards = []
    for item in projects:
        selected = item["path"] == state.get("project")
        card_url = _build_url(state, project=item["path"], tab="project", run=None, task=None, artifact=None, session=None, note=None)
        active_text = ''
        try:
            workspace = WorkspaceSnapshot.load(item['path'])
            normalize_studio(workspace.studio, workspace.project)
            summary = summarize_tree(workspace.studio)
            paper_module = next((module for module in summary['modules'] if module['module_id'] == 'paper'), None)
            active_step = (paper_module or {}).get('active_step') or summary.get('active_step')
            if active_step:
                active_text = f"当前工作：{active_step['title']}"
        except Exception:
            active_text = item.get('health', {}).get('summary') or '打开项目'
        cards.append(
            f"""
            <a class="project-link{' active-project' if selected else ''}" href="{_escape(card_url)}">
              <div class="project-title">{_escape(item['title'])}</div>
              <div class="project-meta">{_escape(active_text or '查看项目概览')}</div>
              <div class="project-next">进入项目页</div>
            </a>
            """
        )
    return "".join(cards)


def _command_item(label: str, meta: str, *, href: str | None = None, action: str | None = None, shortcut: str = '', keywords: str = '') -> str:
    attrs = [f'data-command-search="{_escape((label + " " + meta + " " + keywords).lower())}"']
    side = f'<span class="command-side">{shortcut}</span>' if shortcut else '<span class="command-side">↵</span>'
    if href:
        return f'<a class="command-item" href="{_escape(href)}" {" ".join(attrs)}><span class="command-copy"><strong>{_escape(label)}</strong><span class="command-meta">{_escape(meta)}</span></span>{side}</a>'
    if action:
        return f'<button type="button" class="command-item" data-command-action="{_escape(action)}" {" ".join(attrs)}><span class="command-copy"><strong>{_escape(label)}</strong><span class="command-meta">{_escape(meta)}</span></span>{side}</button>'
    return ''


def _render_command_center(project_root: str, projects: list[dict], state: dict[str, str | None]) -> str:
    selected_project = state.get('project')
    groups: list[tuple[str, list[str]]] = []
    if selected_project:
        try:
            workspace = WorkspaceSnapshot.load(selected_project)
            normalize_studio(workspace.studio, workspace.project)
            summary = summarize_tree(workspace.studio)
        except Exception:
            summary = None
        current_tab = state.get('tab') or 'project'
        current_task = state.get('task')
        current_module = None
        current_step = None
        if summary is not None:
            current_module = next((module for module in summary['modules'] if module['module_id'] == current_tab), None)
            if current_tab in {'paper', 'experiments', 'figures'}:
                current_step = next((step for step in (current_module or {}).get('steps', []) if step.get('step_id') == current_task), None) or (current_module or {}).get('active_step')
        workspace_items: list[str] = []
        if current_tab in {'paper', 'experiments', 'figures'}:
            workspace_items.extend([
                _command_item('当前任务', '直接跳到当前步骤编辑区', href='#current-task', shortcut='<span class="kbd">G</span>'),
                _command_item('主输出', '查看当前主输出和版本比较', href='#main-output', shortcut='<span class="kbd">O</span>'),
                _command_item('文件', '查看输入、输出和导入结果', href='#files-panel', shortcut='<span class="kbd">F</span>'),
                _command_item('最近动作', '查看当前步骤的活动流', href='#activity-stream', shortcut='<span class="kbd">A</span>'),
                _command_item('加一步', '跳到新增步骤入口', href='#step-add', shortcut='<span class="kbd">N</span>'),
            ])
        if not workspace_items:
            workspace_items.append(_command_item('项目首页', '查看整体进度、三条工作线和最近结果', href=_build_url(state, project=selected_project, tab='project', run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">D</span>'))
        groups.append(('当前页面', workspace_items))
        nav_items: list[str] = [_command_item('项目首页', '看整体、进度和三条工作线', href=_build_url(state, project=selected_project, tab='project', run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">P</span>', keywords='project home 概览 项目页')]
        if summary is not None:
            for module in summary['modules']:
                module_id = module['module_id']
                active_step = module.get('active_step') or (module.get('steps') or [None])[0]
                step_title = (active_step or {}).get('title') or '打开模块'
                href = _build_url(state, project=selected_project, tab=module_id, task=(active_step or {}).get('step_id') if module_id != 'control' else None, run=None, artifact=None, session=None, note=None)
                nav_items.append(_command_item(module.get('label') or module_id, f"当前：{step_title}", href=href, shortcut='<span class="kbd">↵</span>', keywords=f"{module_id} 模块 工作区"))
        nav_items.append(_command_item('共享文件库', '打开文件、模板和 AI 管理', href=_build_url(state, project=selected_project, tab='library', run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">L</span>', keywords='library file'))
        nav_items.append(_command_item('系统视图', '查看高级视图、运行记录与旧系统页面', href=_build_url(state, project=selected_project, tab='advanced', run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">S</span>', keywords='advanced runs'))
        groups.append(('切换工作区', nav_items))
        tools_items = [
            _command_item('专注模式', '隐藏更多说明文字', action='toggle-focus', shortcut='<span class="kbd">⌥</span><span class="kbd">F</span>', keywords='focus 简洁'),
            _command_item('专业模式', '展开更多设置和流程调整', action='toggle-pro', shortcut='<span class="kbd">⌥</span><span class="kbd">P</span>', keywords='pro 高级'),
            _command_item('返回首页', '回到项目列表和新建入口', href=_build_url(state, project=None, tab=None, run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">H</span>'),
        ]
        if current_step:
            tools_items.append(_command_item('继续当前步骤', f"{current_step.get('title')}", href='#ai-workspace', shortcut='<span class="kbd">R</span>', keywords='run next action'))
        groups.append(('工具', tools_items))
    else:
        start = [_command_item('新建项目', '展开左侧创建表单，开始一个新项目', href='#sidebar-create', shortcut='<span class="kbd">N</span>', keywords='create project')]
        if projects:
            start.append(_command_item('继续上次项目', '打开最近项目的项目首页', href=_build_url(state, project=projects[0]['path'], tab='project', run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">C</span>', keywords='continue last project home'))
        recent = [
            _command_item(item['title'], '打开项目首页', href=_build_url(state, project=item['path'], tab='project', run=None, task=None, artifact=None, session=None, note=None), shortcut='<span class="kbd">↵</span>', keywords='project continue recent home')
            for item in projects[:8]
        ]
        groups.append(('开始', start))
        groups.append(('最近项目', recent or ['<div class="command-empty">当前还没有项目。先在左侧创建一个。</div>']))
        groups.append(('工具', [
            _command_item('专注模式', '隐藏更多说明文字', action='toggle-focus', shortcut='<span class="kbd">⌥</span><span class="kbd">F</span>'),
            _command_item('专业模式', '展开更多设置和流程调整', action='toggle-pro', shortcut='<span class="kbd">⌥</span><span class="kbd">P</span>'),
        ]))
    groups_html = ''.join(f'<section class="command-group"><div class="command-group-label">{_escape(title)}</div>{"".join(items)}</section>' for title, items in groups if items)
    return f'''
    <div class="command-dialog" id="global-command-dialog" hidden>
      <div class="command-panel" role="dialog" aria-modal="true" aria-label="命令中心">
        <div class="command-head">
          <div>
            <div class="eyebrow">命令中心</div>
            <h2>直接搜入口、模块和当前任务</h2>
          </div>
          <button type="button" class="button ghost command-close">关闭</button>
        </div>
        <div class="command-search-wrap"><input id="global-command-search" class="command-search" type="search" placeholder="搜步骤、模块、文件、当前任务" autocomplete="off"></div>
        <div class="command-list" id="global-command-list">{groups_html}</div>
        <div class="command-footer"><span><span class="kbd">Ctrl / Cmd + K</span> 打开</span><span><span class="kbd">Esc</span> 关闭</span><span><span class="kbd">/</span> 聚焦搜索</span></div>
      </div>
    </div>
    '''

def _render_sidebar(projects: list[dict], state: dict[str, str | None], project_root: str) -> str:
    home_link = _build_url(state, project=None, tab=None, run=None, task=None, artifact=None, session=None, note=None)
    should_open = ' open' if not projects else ''
    return f"""
    <aside class="sidebar">
      <div class="sidebar-shell">
        <div class="brand-row">
          <a class="brand" href="{_escape(home_link)}">{APP_NAME} <span class="brand-version">{APP_VERSION}</span></a>
          {_badge('专业科研助手', 'info')}
        </div>
        <div class="brand-note">围绕 evidence、claim、run 和 deliverable 持续推进研究，而不是把工作留在聊天记录里。</div>

        <div class="section-title">已有项目</div>
        <div class="project-list">{_render_project_selector(projects, state)}</div>

        <details id="sidebar-create" class="card compact-card subtle-details sidebar-create"{should_open}>
          <summary>新建项目</summary>
          <form method="post" action="/action" class="form-stack">
            <input type="hidden" name="action" value="create_project">
            <input type="text" name="root" value="{_escape(project_root)}" placeholder="项目根目录">
            <input type="text" name="title" value="我的研究项目" placeholder="项目标题">
            <input type="text" name="name" value="" placeholder="目录名（可留空）">
            <input type="text" name="owner" value="{_escape(detect_default_owner())}" placeholder="负责人">
            <input type="text" name="venue" value="未设定" placeholder="目标 venue">
            <label>开始方式
              <select name="starter_ai">
                <option value="recommended">推荐开始（ChatGPT）</option>
                <option value="gemini">Gemini 网页</option>
                <option value="api">API（已配 Key）</option>
              </select>
            </label>
            <textarea name="brief" rows="3" placeholder="一句话写总目标"></textarea>
            <button class="primary">创建并开始</button>
          </form>
        </details>
      </div>
    </aside>
    """

def _render_flash(message: str | None, level: str) -> str:
    if not message:
        return ""
    return f'<section class="flash {level}"><pre>{_escape(message)}</pre></section>'




def _starter_meta(starter_ai: str) -> dict[str, str]:
    mapping = {
        "recommended": {
            "title": "推荐开始（ChatGPT）",
            "detail": "适合大多数普通用户，不需要先配 API。",
            "button": "用推荐方式开始",
            "badge": _badge("推荐", "info"),
            "card_class": "starter-card recommended",
        },
        "gemini": {
            "title": "用 Gemini 网页",
            "detail": "如果你更习惯 Gemini，这里可以直接开始。",
            "button": "用 Gemini 开始",
            "badge": _badge("不用 API", "neutral"),
            "card_class": "starter-card",
        },
        "api": {
            "title": "已配 API 再选这里",
            "detail": "适合已经有 key 和模型配置的人。",
            "button": "用 API 开始",
            "badge": _badge("高级", "warn"),
            "card_class": "starter-card",
        },
    }
    return mapping[starter_ai]



def _starter_card(project_root: str, starter_ai: str) -> str:
    meta = _starter_meta(starter_ai)
    return f"""
    <form method=\"post\" action=\"/action\" class=\"{meta['card_class']}\">
      <input type=\"hidden\" name=\"action\" value=\"create_project\">
      <input type=\"hidden\" name=\"root\" value=\"{_escape(project_root)}\">
      <input type=\"hidden\" name=\"title\" value=\"我的研究项目\">
      <input type=\"hidden\" name=\"name\" value=\"\">
      <input type=\"hidden\" name=\"owner\" value=\"{_escape(detect_default_owner())}\">
      <input type=\"hidden\" name=\"venue\" value=\"未设定\">
      <input type=\"hidden\" name=\"starter_ai\" value=\"{_escape(starter_ai)}\">
      <div class=\"starter-card-top\">
        <div>
          <div class=\"starter-title\">{_escape(meta['title'])}</div>
          <div class=\"starter-note\">{_escape(meta['detail'])}</div>
        </div>
        <div>{meta['badge']}</div>
      </div>
      <button class=\"{'primary wide' if starter_ai == 'recommended' else 'secondary wide'}\">{_escape(meta['button'])}</button>
    </form>
    """



def _render_home_main(projects: list[dict], state: dict[str, str | None], project_root: str) -> str:
    continue_cards = []
    for item in projects[:6]:
        link = _build_url(state, project=item["path"], tab="project", run=None, task=None, artifact=None, session=None, note=None)
        next_step = item.get("next_step") or {}
        continue_meta = next_step.get("title") or "回到上次做到这里"
        continue_cards.append(
            f"""
            <a class="continue-card" href="{_escape(link)}">
              <div class="continue-title">{_escape(item['title'])}</div>
              <div class="continue-meta">{_escape(continue_meta)}</div>
              <div class="continue-next">打开项目</div>
            </a>
            """
        )

    return f"""
    <section class="card home-landing premium-home-landing">
      <div class="eyebrow">专业科研助手 · 快速开始</div>
      <h1>{APP_NAME}</h1>
      <div class="subtitle">先看项目整体，再进入专注工作页；把 evidence、claim、run 和 deliverable 分开管理之后，主页面会更像专业科研助手，而不是普通聊天面板。</div>
      <div class="starter-grid">
        {_starter_card(project_root, 'recommended')}
        {_starter_card(project_root, 'gemini')}
        {_starter_card(project_root, 'api')}
      </div>
      <div class="action-row">
        <button type="button" class="button secondary command-toggle">命令中心 / Ctrl+K</button>
      </div>
      <div class="home-hints">{_badge('不会用 API 也没关系', 'info')}{_badge('Ctrl / Cmd + K 搜入口', 'neutral')}{_badge('Esc 关闭', 'neutral')}</div>
      <div class="home-start-grid">
        <div class="start-card"><div class="start-index">1</div><div class="start-title">先建项目</div><p>先进入项目首页，看整体目标、关键证据、当前优先项和下一步。</p></div>
        <div class="start-card"><div class="start-index">2</div><div class="start-title">再进入专注工作页</div><p>项目页看整体，工作页只做当前步骤，逻辑更清楚。</p></div>
        <div class="start-card"><div class="start-index">3</div><div class="start-title">生成并采纳</div><p>拿到结果后采纳并进入下一步；之后你还可以导出 research brief、evidence matrix 和 deliverable index。</p></div>
      </div>
    </section>

    <section class="card">
      <div class="line-card-head"><h2>继续项目</h2></div>
      <div class="continue-grid">{''.join(continue_cards) if continue_cards else '<div class="empty">当前还没有项目。先选上面的开始方式创建一个。</div>'}</div>
    </section>
    """

def _render_topbar(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    title = dashboard["project"]["title"]
    current_tab = state.get('tab') or 'project'
    page_label = {
        'project': '项目首页',
        'paper': '专注工作页',
        'experiments': '专注工作页',
        'figures': '专注工作页',
        'control': '项目设置',
        'advanced': '系统视图',
        'doctor': '健康检查',
    }.get(current_tab, '项目')
    project_home_url = _build_url(state, project=project_dir, tab='project', run=None, task=None, artifact=None, session=None, note=None)
    return f"""
    <section class="topbar project-topbar slim-project-topbar">
      <div>
        <div class="crumbs"><a href="{_escape(_build_url(state, project=None, tab=None, run=None, task=None, artifact=None, session=None, note=None))}">项目列表</a><span>/</span><a href="{_escape(project_home_url)}">{_escape(title)}</a><span>/</span><span>{_escape(page_label)}</span></div>
      </div>
      <div class="mode-switch">
        <button type="button" class="mode-pill command-toggle">命令中心 / Ctrl+K</button>
        <button type="button" class="mode-pill focus-toggle" data-label-on="返回默认" data-label-off="极简视图" aria-pressed="false">极简视图</button>
        <button type="button" class="mode-pill pro-toggle" data-label-on="返回简洁" data-label-off="高级功能" aria-pressed="false">高级功能</button>
        <a class="mode-pill" href="{_escape(project_home_url)}">项目首页</a>
      </div>
    </section>
    """

def _render_tabs(project_dir: str, state: dict[str, str | None]) -> str:
    tabs = [
        ("paper", "写论文"),
        ("experiments", "做实验"),
        ("figures", "做图表"),
        ("control", "看总览"),
    ]
    links = []
    for tab, label in tabs:
        url = _build_url(state, project=project_dir, tab=tab, run=None, task=None, artifact=None, session=None, note=None)
        active = " active-tab" if state.get("tab") == tab else ""
        links.append(f'<a class="tab{active}" href="{_escape(url)}">{_escape(label)}</a>')
    return f'<nav class="tabs">{"".join(links)}</nav>'

def _render_metric_cards(dashboard: dict) -> str:
    stats = dashboard["stats"]
    items = [
        ("证据", stats["evidence"]),
        ("对照基线", stats["baselines"]),
        ("核心主张", stats["claims"]),
        ("任务", stats["runs"]),
        ("结果", stats["results"]),
        ("输出文件", stats["artifacts"]),
    ]
    return "".join(
        f'<div class="metric-card"><div class="metric-label">{_escape(label)}</div><div class="metric-value">{_escape(value)}</div></div>'
        for label, value in items
    )



def _step_button(project_dir: str, step: dict, state: dict[str, str | None]) -> str:
    action = step.get("action")
    command = step.get("command", "")
    if action == "approve_gate" and "--gate" in command:
        gate_id = command.split("--gate", 1)[1].strip().strip('"')
        return _button(step["title"], "approve_gate", state, project_dir, {"gate_id": gate_id}, button_class="secondary")
    if action == "approve_run" and "--run" in command:
        run_id = command.split("--run", 1)[1].strip().strip('"')
        return _button(step["title"], "approve_run", state, project_dir, {"run": run_id, "run_id": run_id, "tab": "advanced"}, button_class="secondary")
    if action == "doctor":
        return _button(step["title"], "doctor", state, project_dir, {"tab": "advanced"}, button_class="secondary")
    if action == "ui":
        return f'<a class="button secondary" href="{_escape(_build_url(state, project=project_dir, tab="overview"))}">{_escape(step["title"])}</a>'
    return _button(step["title"], "run_next", state, project_dir, {"tab": "advanced"}, button_class="secondary")



def _render_stage_journey(dashboard: dict) -> str:
    items = []
    for item in dashboard["stage_journey"]:
        tone = "done" if item["is_done"] else "current" if item["is_current"] else "upcoming"
        items.append(
            f"""
            <div class="journey-step {tone}">
              <div class="journey-bullet"></div>
              <div class="journey-title">{_escape(item['title'])}</div>
              <div class="journey-meta">{_escape(item['status_title'])}</div>
              <div class="journey-desc">{_escape(item['description'])}</div>
            </div>
            """
        )
    return f'<section class="card"><h2>项目路径</h2><div class="journey">{"".join(items)}</div></section>'



def _render_next_steps(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    steps = dashboard["next_steps"]
    actions = "".join(_step_button(project_dir, step, state) for step in steps)
    details = []
    for step in steps:
        command = f"<code>{_escape(step['command'])}</code>" if state.get("mode") == "advanced" else ""
        details.append(f"<li><strong>{_escape(step['title'])}</strong><br><span>{_escape(step['why'])}</span>{command}</li>")
    return f"""
    <section class="card">
      <h2>你现在最适合做什么</h2>
      <div class="action-row">{actions}</div>
      <ul class="guide-list">{"".join(details)}</ul>
    </section>
    """



def _render_readiness(dashboard: dict) -> str:
    readiness = dashboard["stage_readiness"]
    tone = {
        "ready": "ok",
        "needs_decision": "info",
        "active": "info",
        "blocked": "warn",
        "needs_repair": "bad",
        "in_progress": "neutral",
    }.get(readiness["state"], "neutral")
    items = "".join(f"<li>{_escape(item)}</li>" for item in readiness["items"]) or '<li>当前没有额外阻塞项。</li>'
    return f"""
    <section class="card readiness-card {tone}">
      <h2>距离下一阶段还差什么</h2>
      <div class="readiness-title">{_escape(readiness['title'])}</div>
      <p>{_escape(readiness['message'])}</p>
      <ul class="guide-list compact">{items}</ul>
    </section>
    """



def _render_attention_table(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    if not dashboard["attention"]:
        return '<div class="empty">当前没有需要立刻人工介入的事项。</div>'
    rows = []
    for item in dashboard["attention"]:
        action_html = ""
        if item["kind"] == "gate":
            action_html = _button("批准", "approve_gate", state, project_dir, {"gate_id": item["id"], "tab": "overview"})
        elif item["kind"] == "run":
            action_html = _button("批准并继续", "approve_run", state, project_dir, {"run": item["id"], "run_id": item["id"], "tab": "runs"})
        elif item["kind"] == "run_state":
            action_html = f'<a class="inline-link" href="{_escape(_build_url(state, project=project_dir, tab="runs", run=item["id"]))}">查看详情</a>'
        rows.append(
            f"<tr><td>{_escape(item['title'])}</td><td>{_escape(item['status'])}</td><td>{_escape(item['reason'])}</td><td>{action_html}</td></tr>"
        )
    return f'<table><thead><tr><th>事项</th><th>状态</th><th>原因</th><th>操作</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'



def _render_open_tasks(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    if not dashboard["tasks"]:
        return '<div class="empty">当前阶段没有额外待办。你可以先看“最近进展”或直接继续推进一步。</div>'
    rows = []
    for task in dashboard["tasks"]:
        link = _build_url(state, project=project_dir, tab="tasks", task=task["task_id"], run=None, artifact=None, session=None, note=None)
        rows.append(
            f'<tr><td><a class="inline-link" href="{_escape(link)}">{_escape(task.get("title") or task.get("task_id") or "未命名任务")}</a></td><td>{_escape(stage_title(task.get("stage", "")))}</td><td>{_escape(task.get("acceptance") or task.get("acceptance_notes") or "-")}</td></tr>'
        )
    return f'<table><thead><tr><th>待办</th><th>阶段</th><th>完成标准</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'



def _render_notes_preview(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    if not dashboard["notes"]:
        return '<div class="empty">系统还没有产出可读内容。</div>'
    cards = []
    for item in dashboard["notes"][:4]:
        url = _build_url(state, project=project_dir, tab="outputs", note=item["name"], artifact=None, run=None, task=None, session=None)
        cards.append(
            f"""
            <a class="note-card" href="{_escape(url)}">
              <div class="note-head">{_escape(item['label'])}</div>
              <div class="note-status">{_escape(item['status'])}</div>
              <p>{_escape(item['preview'])}</p>
            </a>
            """
        )
    return '<div class="note-grid">' + "".join(cards) + "</div>"



def _render_milestones(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    if not dashboard["recent_milestones"]:
        return '<div class="empty">还没有最近进展记录。</div>'
    rows = []
    for item in dashboard["recent_milestones"]:
        link = None
        if item["kind"] == "run":
            link = _build_url(state, project=project_dir, tab="runs", run=item["id"], task=None, artifact=None, session=None, note=None)
        elif item["kind"] == "artifact":
            link = _build_url(state, project=project_dir, tab="outputs", artifact=item["id"], run=None, task=None, session=None, note=None)
        elif item["kind"] == "session":
            link = _build_url(state, project=project_dir, tab="history", session=item["id"], run=None, task=None, artifact=None, note=None)
        title = f'<a class="inline-link" href="{_escape(link)}">{_escape(item["title"])}</a>' if link else _escape(item["title"])
        rows.append(
            f'<li><div class="timeline-title">{title}</div><div class="timeline-detail">{_escape(item.get("detail") or "")}</div><div class="timeline-time">{_escape(item.get("at") or "-")}</div></li>'
        )
    return '<ul class="timeline">' + "".join(rows) + "</ul>"



def _render_status_block(dashboard: dict) -> str:
    progress = dashboard["progress"]
    health = dashboard["health"]
    experience = dashboard["experience"]
    return f"""
    <div class="hero-status">
      {_badge(dashboard['stage']['title'], 'info')}
      {_badge(experience['label'], 'neutral')}
      {_badge(health['summary'], _health_tone(health))}
      <div class="progress-block">
        <div class="progress-meta"><span>整体进度</span><strong>{progress['pct']}%</strong></div>
        <div class="progress-bar"><span style="width:{progress['pct']}%"></span></div>
        <div class="progress-note">{_escape(progress['label'])}</div>
      </div>
    </div>
    """



def _render_overview(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    starter_card = ""
    if dashboard["experience"]["mode"] == "new":
        starter_card = f"""
        <section class="card emphasis-card">
          <h2>第一次体验只要 3 个动作</h2>
          <ol>
            <li>点“继续推进一步”，让系统自动生成第一批背景、baseline 和方向判断</li>
            <li>看“距离下一阶段还差什么”，理解现在不是哪里坏了，而是还差哪一步</li>
            <li>如果出现“等待你的确认”，直接点批准，然后再继续推进</li>
          </ol>
          <div class="action-row">
            {_button('继续推进一步', 'run_next', state, project_dir, {'tab': 'overview'}, button_class='primary')}
            {_button('打开健康检查', 'doctor', state, project_dir, {'tab': 'doctor'})}
          </div>
        </section>
        """
    elif dashboard["health"].get("state") == "needs_decision":
        starter_card = f"""
        <section class="card emphasis-card info-card">
          <h2>这不是报错：系统正在等你点头</h2>
          <p>机器侧已经把当前阶段能自动完成的部分做完了。现在最适合先批准，再继续推进下一步。</p>
          <div class="action-row">
            {_button('批准下一个待确认项', 'approve_next', state, project_dir, {'tab': 'overview'}, button_class='primary')}
            {_button('看为什么要确认', 'doctor', state, project_dir, {'tab': 'doctor'})}
          </div>
        </section>
        """

    return f"""
    {starter_card}
    <section class="hero project-hero">
      <div>
        <div class="eyebrow">项目总览</div>
        <h1>{_escape(dashboard['project']['title'])}</h1>
        <div class="subtitle">{_escape(dashboard['stage']['description'])}</div>
        <p>{_escape(dashboard['story'])}</p>
        <div class="goal-text">当前目标：{_escape(dashboard['project'].get('goal') or '未设定')}</div>
      </div>
      <div class="hero-side stack-card">
        {_render_status_block(dashboard)}
        <div class="action-row vertical">
          {_button('继续推进一步', 'run_next', state, project_dir, {'tab': 'overview'}, button_class='primary wide')}
          {_button('连续推进 3 步', 'run_loop', state, project_dir, {'steps': '3', 'tab': 'overview'}, button_class='wide')}
          {_button('批准下一个待确认项', 'approve_next', state, project_dir, {'tab': 'overview'}, button_class='wide')}
          {_button('生成审计报告', 'audit', state, project_dir, {'tab': 'doctor'}, button_class='wide')}
          {_button('做一次健康检查', 'doctor', state, project_dir, {'tab': 'doctor'}, button_class='wide')}
        </div>
      </div>
    </section>

    <section class="metric-grid">{_render_metric_cards(dashboard)}</section>
    {_render_stage_journey(dashboard)}

    <section class="two-col">
      {_render_readiness(dashboard)}
      {_render_next_steps(project_dir, dashboard, state)}
    </section>

    <section class="two-col">
      <section class="card">
        <h2>需要你处理</h2>
        {_render_attention_table(project_dir, dashboard, state)}
      </section>
      <section class="card">
        <h2>当前阶段待办</h2>
        {_render_open_tasks(project_dir, dashboard, state)}
      </section>
    </section>

    <section class="two-col">
      <section class="card">
        <h2>最近可读内容</h2>
        {_render_notes_preview(project_dir, dashboard, state)}
      </section>
      <section class="card">
        <h2>最近进展</h2>
        {_render_milestones(project_dir, dashboard, state)}
      </section>
    </section>
    """



def _render_task_detail(project_dir: str, detail: dict | None, state: dict[str, str | None]) -> str:
    if not detail:
        return ""
    task = detail["task"]
    dependency_items = detail["dependencies"]
    downstream_items = detail["downstream"]
    related_runs = detail["related_runs"]
    advanced = state.get("mode") == "advanced"
    dependency_html = "".join(f"<li>{_escape(item.get('title') or item.get('task_id'))}</li>" for item in dependency_items) or "<li>没有前置依赖。</li>"
    downstream_html = "".join(f"<li>{_escape(item.get('title') or item.get('task_id'))}</li>" for item in downstream_items) or "<li>当前没有后续任务依赖它。</li>"
    related_runs_html = "".join(
        f'<li><a class="inline-link" href="{_escape(_build_url(state, project=project_dir, tab="runs", run=item.get("run_id"), task=None, artifact=None, session=None, note=None))}">{_escape(item.get("run_id"))}</a> · {run_status_title(item.get("status"))}</li>'
        for item in related_runs
    ) or "<li>还没有和这项任务绑定的任务记录。</li>"
    advanced_html = ""
    if advanced:
        advanced_html = f"<details><summary>高级信息</summary><pre>{_escape(json.dumps(task, ensure_ascii=False, indent=2))}</pre></details>"
    return f"""
    <section class="card detail-card">
      <div class="detail-header">
        <div>
          <div class="eyebrow">任务详情</div>
          <h2>{_escape(task.get('title') or task.get('task_id') or '未命名任务')}</h2>
          <div class="detail-meta">{_escape(stage_title(task.get('stage', '')))} · {_escape(_task_status_title(task.get('status')))} · {_escape(task.get('priority') or '-')}</div>
        </div>
        <a class="button ghost" href="{_escape(_build_url(state, project=project_dir, tab='tasks', task=None, run=None, artifact=None, session=None, note=None))}">关闭详情</a>
      </div>
      <p>{_escape(task.get('notes') or '这是一条系统维护的项目任务。')}</p>
      <div class="two-col detail-grid">
        <div>
          <h3>完成标准</h3>
          <p>{_escape(task.get('acceptance_notes') or '当前没有额外完成标准。')}</p>
          <h3>前置依赖</h3>
          <ul class="guide-list compact">{dependency_html}</ul>
        </div>
        <div>
          <h3>后续会影响</h3>
          <ul class="guide-list compact">{downstream_html}</ul>
          <h3>关联任务记录</h3>
          <ul class="guide-list compact">{related_runs_html}</ul>
        </div>
      </div>
      {advanced_html}
    </section>
    """



def _render_tasks_tab(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    workspace = WorkspaceSnapshot.load(project_dir)
    tasks = sorted(workspace.task_graph.get("tasks", []), key=_task_sort_key)
    selected = project_task_details(project_dir, state.get("task") or "") if state.get("task") else None
    rows = []
    for task in tasks:
        link = _build_url(state, project=project_dir, tab="tasks", task=task.get("task_id"), run=None, artifact=None, session=None, note=None)
        row_class = "done-row" if task.get("status") == "done" else ""
        rows.append(
            f'<tr class="{row_class}"><td><a class="inline-link" href="{_escape(link)}">{_escape(task.get("title") or task.get("task_id") or "未命名任务")}</a></td><td>{_escape(stage_title(task.get("stage", "")))}</td><td>{_escape(_task_status_title(task.get("status")))}</td><td>{_escape(task.get("acceptance_notes") or "-")}</td></tr>'
        )
    return f"""
    {_render_task_detail(project_dir, selected, state)}
    <section class="two-col">
      <section class="card">
        <h2>当前最需要处理</h2>
        {_render_attention_table(project_dir, dashboard, state)}
      </section>
      <section class="card">
        <h2>这一阶段为什么还没结束</h2>
        {_render_readiness(dashboard)}
      </section>
    </section>
    <section class="card">
      <h2>全部任务</h2>
      <table><thead><tr><th>任务</th><th>阶段</th><th>状态</th><th>完成标准</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="4">还没有任务。</td></tr>'}</tbody></table>
    </section>
    """



def _render_run_detail(project_dir: str, detail: dict | None, state: dict[str, str | None]) -> str:
    if not detail:
        return ""
    run = detail["run"]
    manifest = detail["manifest"]
    request = detail["request"]
    advanced = state.get("mode") == "advanced"

    action_buttons = []
    if detail["summary"].get("can_approve"):
        action_buttons.append(_button("批准并继续", "approve_run", state, project_dir, {"run_id": run.get("run_id"), "run": run.get("run_id"), "tab": "runs"}, button_class="primary"))
    if detail["summary"].get("can_retry"):
        action_buttons.append(_button("重新排队重试", "retry_run", state, project_dir, {"run_id": run.get("run_id"), "run": run.get("run_id"), "tab": "runs"}, button_class="secondary"))
    if detail["summary"].get("can_cancel"):
        action_buttons.append(
            _button(
                "取消这个任务",
                "cancel_run",
                state,
                project_dir,
                {"run_id": run.get("run_id"), "run": run.get("run_id"), "tab": "runs"},
                button_class="secondary",
                confirm_text="取消后，这个任务会停止等待或执行。确定继续吗？",
            )
        )
    if advanced:
        action_buttons.append(_button("让本地执行器再处理一次", "run_worker", state, project_dir, {"run": run.get("run_id"), "tab": "runs"}, button_class="ghost"))

    metric_cards = []
    for item in detail["metrics"][:6]:
        metric_cards.append(f'<div class="metric-card compact"><div class="metric-label">{_escape(item["key"])}</div><div class="metric-value small">{_escape(item["value"])}</div></div>')
    results_rows = []
    for item in detail["results"]:
        results_rows.append(f"<tr><td>{_escape(item.get('metric') or item.get('result_id'))}</td><td>{_escape(item.get('value'))}</td><td>{_escape(item.get('notes') or '-')}</td></tr>")
    eval_rows = []
    for item in detail["evaluations"]:
        eval_rows.append(f"<tr><td>{_escape(item.get('evaluator'))}</td><td>{_escape(eval_status_title(item.get('status')))}</td><td>{_escape(item.get('summary') or '-')}</td></tr>")
    file_rows = []
    for item in detail["output_manifest"].get("files", []):
        file_rows.append(f"<tr><td>{_escape(item.get('path'))}</td><td>{_escape(item.get('size_bytes'))}</td><td>{_escape(item.get('sha256') or '-')}</td></tr>")
    attempts_rows = []
    for item in run.get("attempts", []):
        attempts_rows.append(f"<tr><td>{_escape(item.get('attempt'))}</td><td>{_escape(run_status_title(item.get('status')))}</td><td>{_escape(item.get('started_at') or '-')}</td><td>{_escape(item.get('ended_at') or '-')}</td></tr>")

    advanced_html = ""
    if advanced:
        raw = {
            "run": run,
            "manifest": manifest,
            "request": request,
            "claims": detail["claims"],
        }
        advanced_html = f'<details><summary>高级信息</summary><pre>{_escape(json.dumps(raw, ensure_ascii=False, indent=2))}</pre></details>'

    return f"""
    <section class="card detail-card">
      <div class="detail-header">
        <div>
          <div class="eyebrow">任务详情</div>
          <h2>{_escape(detail['summary']['title'])}</h2>
          <div class="detail-meta">{_escape(run.get('run_id'))} · {_escape(detail['summary']['status'])} · {_escape(detail['summary']['evaluation'])}</div>
        </div>
        <a class="button ghost" href="{_escape(_build_url(state, project=project_dir, tab='runs', run=None, task=None, artifact=None, session=None, note=None))}">关闭详情</a>
      </div>
      <p>{_escape(manifest.get('question') or request.get('notes') or '这是一条系统记录下来的任务。')}</p>
      <div class="action-row">{''.join(action_buttons) or '<span class="helper-text">当前没有可直接执行的人工操作。</span>'}</div>
      <div class="two-col detail-grid">
        <div>
          <h3>任务背景</h3>
          <ul class="guide-list compact">
            <li>模型：{_escape(manifest.get('model') or '-')}</li>
            <li>数据：{_escape(manifest.get('dataset') or '-')}</li>
            <li>硬件：{_escape(manifest.get('hardware') or '-')}</li>
            <li>优先级：{_escape(run.get('priority') or '-')}</li>
          </ul>
        </div>
        <div>
          <h3>系统判断</h3>
          <ul class="guide-list compact">
            <li>当前状态：{_escape(detail['summary']['status'])}</li>
            <li>结果检查：{_escape(detail['summary']['evaluation'])}</li>
            <li>上次更新时间：{_escape(run.get('ended_at') or run.get('started_at') or run.get('queued_at') or run.get('created_at') or '-')}</li>
            <li>审批状态：{_escape(run.get('approval', {}).get('status') or 'not_required')}</li>
          </ul>
        </div>
      </div>
      <h3>关键指标</h3>
      <div class="metric-grid compact-grid">{''.join(metric_cards) or '<div class="empty">还没有可展示的指标。</div>'}</div>
      <h3>注册结果</h3>
      <table><thead><tr><th>指标</th><th>值</th><th>备注</th></tr></thead><tbody>{''.join(results_rows) or '<tr><td colspan="3">还没有注册结果。</td></tr>'}</tbody></table>
      <h3>结果检查</h3>
      <table><thead><tr><th>检查项</th><th>状态</th><th>说明</th></tr></thead><tbody>{''.join(eval_rows) or '<tr><td colspan="3">还没有检查记录。</td></tr>'}</tbody></table>
      <h3>输出文件</h3>
      <table><thead><tr><th>文件</th><th>大小（字节）</th><th>sha256</th></tr></thead><tbody>{''.join(file_rows) or '<tr><td colspan="3">还没有输出清单。</td></tr>'}</tbody></table>
      <h3>执行尝试</h3>
      <table><thead><tr><th>尝试</th><th>状态</th><th>开始</th><th>结束</th></tr></thead><tbody>{''.join(attempts_rows) or '<tr><td colspan="4">还没有尝试记录。</td></tr>'}</tbody></table>
      {advanced_html}
    </section>
    """



def _render_runs_tab(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    workspace = WorkspaceSnapshot.load(project_dir)
    runs = sorted(workspace.run_registry.get("runs", []), key=_run_sort_key, reverse=True)
    selected = project_run_details(project_dir, state.get("run") or "") if state.get("run") else None
    rows = []
    for run in runs:
        manifest = workspace.load_run_manifest(run.get("run_id"))
        title = manifest.get("question") or run.get("run_id") or "未命名任务"
        link = _build_url(state, project=project_dir, tab="runs", run=run.get("run_id"), task=None, artifact=None, session=None, note=None)
        row_class = "attention-row" if run.get("status") in {"blocked", "retryable", "failed"} else ""
        rows.append(
            f'<tr class="{row_class}"><td><a class="inline-link" href="{_escape(link)}">{_escape(title)}</a><div class="row-sub">{_escape(run.get("run_id") or "")}</div></td><td>{_escape(run_status_title(run.get("status")))}</td><td>{_escape(eval_status_title(run.get("evaluation_status")))}</td><td>{_escape(run.get("ended_at") or run.get("started_at") or run.get("queued_at") or run.get("created_at") or "-")}</td></tr>'
        )
    return f"""
    {_render_run_detail(project_dir, selected, state)}
    <section class="card">
      <h2>任务记录</h2>
      <table><thead><tr><th>任务</th><th>状态</th><th>结果检查</th><th>最近时间</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="4">还没有任务记录。</td></tr>'}</tbody></table>
    </section>
    """



def _render_artifact_detail(project_dir: str, detail: dict | None, state: dict[str, str | None]) -> str:
    if not detail:
        return ""
    artifact = detail["artifact"]
    related_run = detail["related_run"]
    related_html = "还没有关联到具体任务。"
    if related_run:
        related_html = f'<a class="inline-link" href="{_escape(_build_url(state, project=project_dir, tab="runs", run=related_run.get("run_id"), task=None, artifact=None, session=None, note=None))}">{_escape(related_run.get("run_id"))}</a>'
    return f"""
    <section class="card detail-card">
      <div class="detail-header">
        <div>
          <div class="eyebrow">输出文件详情</div>
          <h2>{_escape(artifact.get('name') or '未命名输出')}</h2>
          <div class="detail-meta">{_escape(artifact.get('status') or 'ready')} · 负责人：{_escape(artifact.get('owner') or '-')}</div>
        </div>
        <a class="button ghost" href="{_escape(_build_url(state, project=project_dir, tab='outputs', artifact=None, note=None, run=None, task=None, session=None))}">关闭详情</a>
      </div>
      <p>{_escape(artifact.get('notes') or '这是项目输出清单里的一个条目。')}</p>
      <ul class="guide-list compact">
        <li>状态：{_escape(artifact.get('status') or 'ready')}</li>
        <li>关联任务：{related_html}</li>
        <li>磁盘路径：{_escape(detail.get('resolved_path') or '未登记')}</li>
        <li>是否存在：{_escape('是' if detail.get('exists_on_disk') else '未知 / 未登记')}</li>
      </ul>
    </section>
    """



def _render_note_detail(project_dir: str, detail: dict | None, state: dict[str, str | None]) -> str:
    if not detail:
        return ""
    placeholder_note = '<div class="helper-text">当前还是占位内容。继续推进后，这里通常会变成更可读的项目材料。</div>' if detail.get("placeholder") else ""
    return f"""
    <section class="card detail-card">
      <div class="detail-header">
        <div>
          <div class="eyebrow">项目材料</div>
          <h2>{_escape(detail['label'])}</h2>
          <div class="detail-meta">{_escape(detail['path'])}</div>
        </div>
        <a class="button ghost" href="{_escape(_build_url(state, project=project_dir, tab='outputs', note=None, artifact=None, run=None, task=None, session=None))}">关闭内容</a>
      </div>
      {placeholder_note}
      <pre class="markdown-preview">{_escape(detail['content'])}</pre>
    </section>
    """



def _render_outputs_tab(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    workspace = WorkspaceSnapshot.load(project_dir)
    artifacts = sorted(workspace.artifact_registry.get("items", []), key=lambda item: (item.get("status") or "", item.get("name") or ""))
    selected_artifact = project_artifact_details(project_dir, state.get("artifact") or "") if state.get("artifact") else None
    selected_note = project_note_details(project_dir, state.get("note") or "") if state.get("note") else None
    artifact_rows = []
    for item in artifacts:
        link = _build_url(state, project=project_dir, tab="outputs", artifact=item.get("name"), note=None, run=None, task=None, session=None)
        artifact_rows.append(
            f'<tr><td><a class="inline-link" href="{_escape(link)}">{_escape(item.get("name") or "未命名输出")}</a></td><td>{_escape(item.get("status") or "ready")}</td><td>{_escape(item.get("owner") or "-")}</td><td>{_escape(item.get("notes") or "-")}</td></tr>'
        )
    evaluation_rows = []
    for item in dashboard["recent_evaluations"]:
        evaluation_rows.append(f"<tr><td>{_escape(item['evaluator'])}</td><td>{_escape(item['target'])}</td><td>{_escape(item['status'])}</td><td>{_escape(item.get('summary') or '-')}</td></tr>")
    return f"""
    {_render_artifact_detail(project_dir, selected_artifact, state)}
    {_render_note_detail(project_dir, selected_note, state)}
    <section class="two-col">
      <section class="card">
        <h2>输出文件</h2>
        <table><thead><tr><th>名称</th><th>状态</th><th>负责人</th><th>备注</th></tr></thead><tbody>{''.join(artifact_rows) or '<tr><td colspan="4">还没有输出文件。</td></tr>'}</tbody></table>
      </section>
      <section class="card">
        <h2>项目材料</h2>
        {_render_notes_preview(project_dir, dashboard, state)}
      </section>
    </section>
    <section class="card">
      <h2>最近结果检查</h2>
      <table><thead><tr><th>检查项</th><th>对象</th><th>状态</th><th>说明</th></tr></thead><tbody>{''.join(evaluation_rows) or '<tr><td colspan="4">还没有检查记录。</td></tr>'}</tbody></table>
    </section>
    """



def _render_session_detail(project_dir: str, detail: dict | None, state: dict[str, str | None]) -> str:
    if not detail:
        return ""
    session = detail["session"]
    advanced = state.get("mode") == "advanced"
    raw_html = f'<details><summary>高级信息</summary><pre>{_escape(json.dumps(session, ensure_ascii=False, indent=2))}</pre></details>' if advanced else ""
    return f"""
    <section class="card detail-card">
      <div class="detail-header">
        <div>
          <div class="eyebrow">推进记录</div>
          <h2>{_escape(session.get('session_id') or '未命名会话')}</h2>
          <div class="detail-meta">{_escape(session.get('agent') or 'controller')} / {_escape(session.get('profile') or '-')} · {_escape(session.get('status') or '-')}</div>
        </div>
        <a class="button ghost" href="{_escape(_build_url(state, project=project_dir, tab='history', session=None, run=None, task=None, artifact=None, note=None))}">关闭详情</a>
      </div>
      <p>这是系统一次自动推进留下的记录。普通用户通常只需要关心：这一步是谁推进的、是否完成、现在到了哪一阶段。</p>
      <ul class="guide-list compact">
        <li>开始时间：{_escape(session.get('started_at') or '-')}</li>
        <li>结束时间：{_escape(session.get('ended_at') or '-')}</li>
        <li>当时阶段：{_escape(stage_title(session.get('current_stage') or ''))}</li>
        <li>交接原因：{_escape(session.get('handoff_reason') or '-')}</li>
      </ul>
      {raw_html}
    </section>
    """



def _render_history_tab(project_dir: str, dashboard: dict, state: dict[str, str | None]) -> str:
    selected = project_session_details(project_dir, state.get("session") or "") if state.get("session") else None
    session_rows = []
    for item in dashboard["recent_sessions"]:
        link = _build_url(state, project=project_dir, tab="history", session=item["session_id"], run=None, task=None, artifact=None, note=None)
        session_rows.append(
            f'<tr><td><a class="inline-link" href="{_escape(link)}">{_escape(item["session_id"])}</a></td><td>{_escape(item.get("agent") or "-")}</td><td>{_escape(item.get("profile") or "-")}</td><td>{_escape(item.get("status") or "-")}</td><td>{_escape(item.get("started_at") or "-")}</td></tr>'
        )
    return f"""
    {_render_session_detail(project_dir, selected, state)}
    <section class="two-col">
      <section class="card">
        <h2>最近进展时间线</h2>
        {_render_milestones(project_dir, dashboard, state)}
      </section>
      <section class="card">
        <h2>最近系统推进记录</h2>
        <table><thead><tr><th>会话</th><th>角色</th><th>模式</th><th>状态</th><th>开始时间</th></tr></thead><tbody>{''.join(session_rows) or '<tr><td colspan="5">还没有推进记录。</td></tr>'}</tbody></table>
      </section>
    </section>
    """



def _render_doctor_checks(report: dict) -> str:
    rows = []
    for item in report["checks"]:
        tone = {
            "pass": "ok",
            "warn": "warn" if item.get("health_impact") != "neutral" else "info",
            "fail": "bad",
        }.get(item["level"], "neutral")
        fix = f'<div class="check-fix">建议：{_escape(item.get("fix") or "-")}</div>' if item.get("fix") else ""
        rows.append(
            f'<li class="check-item {tone}"><div class="check-title">{_escape(item["title"])}</div><div class="check-detail">{_escape(item.get("detail") or "")}</div>{fix}</li>'
        )
    return '<ul class="check-list">' + "".join(rows) + "</ul>"



def _render_doctor_tab(project_dir: str, dashboard: dict, state: dict[str, str | None], project_root: str) -> str:
    report = doctor_report(project_dir, root=project_root)
    tone = {"pass": "ok", "warn": "warn", "fail": "bad"}.get(report["overall"], "neutral")
    next_actions = _render_next_steps(project_dir, dashboard, state)
    return f"""
    <section class="card doctor-summary {tone}">
      <h2>健康检查</h2>
      <div class="doctor-title">当前结论：{_escape({'pass': '通过', 'warn': '有提醒', 'fail': '需要修复'}.get(report['overall'], report['overall']))}</div>
      <p>这里会区分两类情况：真正需要修复的结构问题，以及“只是流程还没走完”的提醒。如果你看到“等待你的确认”，通常不是系统坏了。</p>
      <div class="action-row">
        {_button('重新做一次健康检查', 'doctor', state, project_dir, {'tab': 'doctor'}, button_class='primary')}
        {_button('生成审计报告', 'audit', state, project_dir, {'tab': 'doctor'})}
      </div>
    </section>
    <section class="two-col">
      <section class="card">
        <h2>检查结果</h2>
        {_render_doctor_checks(report)}
      </section>
      {next_actions}
    </section>
    """



def _render_advanced_tab(project_dir: str, dashboard: dict, state: dict[str, str | None], project_root: str) -> str:
    report = doctor_report(project_dir, root=project_root)
    return f"""
    <section class="card info-card">
      <h2>高级视图</h2>
      <p>这里保留旧系统的任务记录、输出成果、最近进展和健康检查。普通工作请优先回到 AI 工作台。</p>
    </section>
    <section class="two-col">
      <section class="card"><h2>需要人工介入</h2>{_render_attention_table(project_dir, dashboard, {**state, 'tab': 'advanced'})}</section>
      <section class="card"><h2>健康检查</h2>{_render_doctor_checks(report)}</section>
    </section>
    {_render_runs_tab(project_dir, dashboard, {**state, 'tab': 'runs'})}
    {_render_outputs_tab(project_dir, dashboard, {**state, 'tab': 'outputs'})}
    {_render_history_tab(project_dir, dashboard, {**state, 'tab': 'history'})}
    """


def _render_selected_project(project_dir: str, dashboard: dict, state: dict[str, str | None], project_root: str) -> str:
    tab = state.get("tab") or "project"
    if tab == "project":
        content = render_project_home(project_dir, state)
    elif tab in {"paper", "experiments", "figures"}:
        content = render_workspace(project_dir, state, tab, dashboard)
    elif tab == "control":
        content = render_control(project_dir, state)
    elif tab == "library":
        content = render_library(project_dir, state)
    elif tab == "advanced":
        content = _render_advanced_tab(project_dir, dashboard, state, project_root)
    elif tab == "tasks":
        content = _render_tasks_tab(project_dir, dashboard, state)
    elif tab == "runs":
        content = _render_runs_tab(project_dir, dashboard, state)
    elif tab == "outputs":
        content = _render_outputs_tab(project_dir, dashboard, state)
    elif tab == "history":
        content = _render_history_tab(project_dir, dashboard, state)
    elif tab == "doctor":
        content = _render_doctor_tab(project_dir, dashboard, state, project_root)
    else:
        content = render_project_home(project_dir, state)
    return _render_topbar(project_dir, dashboard, state) + content

def _render_page(project_root: str, state: dict[str, str | None], flash: str | None = None, flash_level: str = "ok") -> str:
    projects = list_projects(project_root)
    selected_project = state.get("project")
    dashboard = None
    dashboard_error = None
    if selected_project:
        try:
            dashboard = project_dashboard(selected_project)
        except Exception as exc:  # pragma: no cover - keep UI available even if one project breaks
            dashboard_error = humanize_exception(exc)

    main_content = _render_home_main(projects, state, project_root) if dashboard is None else _render_selected_project(selected_project or "", dashboard, state, project_root)
    command_center_html = _render_command_center(project_root, projects, state)
    flash_html = _render_flash(flash, flash_level)
    if dashboard_error:
        flash_html += _render_flash(dashboard_error, "error")

    return f"""
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{APP_NAME} {APP_VERSION}</title>
      <style>
        {PAGE_CSS}
      </style>
    </head>
    <body>
      <div class="app">
        {_render_sidebar(projects, state, project_root)}
        <main class="main">
          {flash_html}
          {main_content}
        </main>
      </div>
      {command_center_html}
      <script>
      (function() {{
        const FOCUS_KEY = 'research-os-focus-ui';
        const PRO_KEY = 'research-os-pro-ui';
        const LEFT_DRAWER_KEY = 'research-os-left-drawer';
        const RIGHT_DRAWER_KEY = 'research-os-right-drawer';
        const commandDialog = document.getElementById('global-command-dialog');
        const commandSearch = document.getElementById('global-command-search');
        const commandList = document.getElementById('global-command-list');
        const autosaveTimers = new WeakMap();
        const autosaveStatus = new WeakMap();

        const setCopiedState = (button) => {{
          const original = button.dataset.originalLabel || button.textContent;
          button.dataset.originalLabel = original;
          button.textContent = button.dataset.copiedLabel || '已复制';
          window.setTimeout(() => {{ button.textContent = original; }}, 1400);
        }};
        const fallbackCopy = (text) => {{
          const node = document.createElement('textarea');
          node.value = text;
          document.body.appendChild(node);
          node.select();
          try {{ document.execCommand('copy'); }} catch (_err) {{}}
          document.body.removeChild(node);
        }};
        const copyText = async (text, button) => {{
          try {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
              await navigator.clipboard.writeText(text);
            }} else {{
              fallbackCopy(text);
            }}
            setCopiedState(button);
          }} catch (_err) {{
            fallbackCopy(text);
            setCopiedState(button);
          }}
        }};
        const setStatus = (node, state, text) => {{
          if (!node) return;
          node.classList.remove('saving', 'saved', 'error');
          if (state) node.classList.add(state);
          node.textContent = text;
          autosaveStatus.set(node, state || '');
        }};
        const autoGrow = (field) => {{
          if (!field || field.tagName !== 'TEXTAREA') return;
          const min = Number(field.dataset.minHeight || 0) || field.scrollHeight || 96;
          field.style.height = 'auto';
          field.style.height = Math.max(field.scrollHeight, min) + 'px';
        }};
        const setDrawer = (drawer, enabled) => {{
          const key = drawer === 'left' ? LEFT_DRAWER_KEY : RIGHT_DRAWER_KEY;
          window.localStorage.setItem(key, enabled ? '1' : '0');
          apply();
        }};
        const filterCommands = () => {{
          if (!commandList || !commandSearch) return;
          const query = (commandSearch.value || '').trim().toLowerCase();
          commandList.querySelectorAll('.command-item').forEach((item) => {{
            const haystack = item.dataset.commandSearch || item.textContent.toLowerCase();
            item.hidden = Boolean(query) && !haystack.includes(query);
          }});
          commandList.querySelectorAll('.command-group').forEach((group) => {{
            const visible = Array.from(group.querySelectorAll('.command-item')).some((item) => !item.hidden);
            group.hidden = !visible;
          }});
        }};
        const openCommand = () => {{
          if (!commandDialog) return;
          commandDialog.hidden = false;
          filterCommands();
          window.setTimeout(() => {{ if (commandSearch) commandSearch.focus(); }}, 0);
        }};
        const closeCommand = () => {{
          if (!commandDialog) return;
          commandDialog.hidden = true;
          if (commandSearch) {{
            commandSearch.value = '';
            filterCommands();
          }}
        }};
        const apply = () => {{
          const focusEnabled = window.localStorage.getItem(FOCUS_KEY) === '1';
          const proEnabled = window.localStorage.getItem(PRO_KEY) === '1';
          const leftOpen = window.localStorage.getItem(LEFT_DRAWER_KEY) === '1';
          const rightOpen = window.localStorage.getItem(RIGHT_DRAWER_KEY) === '1';
          document.body.classList.toggle('focus-ui', focusEnabled);
          document.body.classList.toggle('pro-ui', proEnabled);
          document.body.classList.toggle('show-left-drawer', leftOpen);
          document.body.classList.toggle('show-right-drawer', rightOpen);
          document.querySelectorAll('.focus-toggle').forEach((node) => {{
            node.textContent = focusEnabled ? (node.dataset.labelOn || '普通模式') : (node.dataset.labelOff || '专注模式');
            node.setAttribute('aria-pressed', focusEnabled ? 'true' : 'false');
          }});
          document.querySelectorAll('.pro-toggle').forEach((node) => {{
            node.textContent = proEnabled ? (node.dataset.labelOn || '简洁模式') : (node.dataset.labelOff || '专业模式');
            node.setAttribute('aria-pressed', proEnabled ? 'true' : 'false');
          }});
          document.querySelectorAll('.drawer-toggle').forEach((node) => {{
            const drawer = node.dataset.drawer;
            const active = drawer === 'left' ? leftOpen : rightOpen;
            node.setAttribute('aria-pressed', active ? 'true' : 'false');
            node.classList.toggle('accent', active);
          }});
        }};
        const scheduleAutosave = (form) => {{
          const statusId = form.dataset.autosaveStatus;
          const statusNode = statusId ? document.getElementById(statusId) : null;
          const previous = autosaveTimers.get(form);
          if (previous) window.clearTimeout(previous);
          setStatus(statusNode, 'saving', '正在自动保存…');
          const timer = window.setTimeout(async () => {{
            try {{
              const formData = new FormData(form);
              formData.set('action', 'save_step');
              await fetch('/action', {{ method: 'POST', body: formData, credentials: 'same-origin' }});
              setStatus(statusNode, 'saved', '已自动保存');
              window.setTimeout(() => {{
                if ((autosaveStatus.get(statusNode) || '') === 'saved') setStatus(statusNode, '', '自动保存已开启');
              }}, 1800);
            }} catch (_err) {{
              setStatus(statusNode, 'error', '自动保存失败，点“开始生成”前请手动检查');
            }}
          }}, 850);
          autosaveTimers.set(form, timer);
        }};
        document.querySelectorAll('textarea').forEach((field) => {{
          field.dataset.minHeight = String(field.offsetHeight || field.scrollHeight || 96);
          autoGrow(field);
          field.addEventListener('input', () => autoGrow(field));
        }});
        document.querySelectorAll('.autosave-form').forEach((form) => {{
          form.querySelectorAll('textarea, input[type="text"], select, input[type="radio"]').forEach((field) => {{
            const handler = () => scheduleAutosave(form);
            field.addEventListener(field.matches('input[type="text"], textarea') ? 'input' : 'change', handler);
          }});
        }});
        if (commandSearch) commandSearch.addEventListener('input', filterCommands);
        document.addEventListener('click', async (event) => {{
          const focusButton = event.target.closest('.focus-toggle');
          if (focusButton) {{
            const enabled = window.localStorage.getItem(FOCUS_KEY) === '1';
            window.localStorage.setItem(FOCUS_KEY, enabled ? '0' : '1');
            apply();
            return;
          }}
          const proButton = event.target.closest('.pro-toggle');
          if (proButton) {{
            const enabled = window.localStorage.getItem(PRO_KEY) === '1';
            window.localStorage.setItem(PRO_KEY, enabled ? '0' : '1');
            apply();
            return;
          }}
          const drawerButton = event.target.closest('.drawer-toggle');
          if (drawerButton) {{
            const drawer = drawerButton.dataset.drawer;
            const key = drawer === 'left' ? LEFT_DRAWER_KEY : RIGHT_DRAWER_KEY;
            const enabled = window.localStorage.getItem(key) === '1';
            setDrawer(drawer, !enabled);
            return;
          }}
          const drawerClose = event.target.closest('[data-drawer-close]');
          if (drawerClose) {{
            const drawer = drawerClose.dataset.drawerClose;
            if (drawer === 'left' || drawer === 'all') setDrawer('left', false);
            if (drawer === 'right' || drawer === 'all') setDrawer('right', false);
            return;
          }}
          const commandToggle = event.target.closest('.command-toggle');
          if (commandToggle) {{
            if (commandDialog && !commandDialog.hidden) closeCommand();
            else openCommand();
            return;
          }}
          if (event.target.closest('.command-close')) {{
            closeCommand();
            return;
          }}
          const commandAction = event.target.closest('[data-command-action]');
          if (commandAction) {{
            const action = commandAction.dataset.commandAction;
            if (action === 'toggle-focus') {{
              const enabled = window.localStorage.getItem(FOCUS_KEY) === '1';
              window.localStorage.setItem(FOCUS_KEY, enabled ? '0' : '1');
            }} else if (action === 'toggle-pro') {{
              const enabled = window.localStorage.getItem(PRO_KEY) === '1';
              window.localStorage.setItem(PRO_KEY, enabled ? '0' : '1');
            }}
            apply();
            closeCommand();
            return;
          }}
          const copyButton = event.target.closest('.copy-trigger');
          if (copyButton) {{
            const targetId = copyButton.dataset.copyTarget;
            const source = targetId ? document.getElementById(targetId) : null;
            const text = source ? (source.value || source.textContent || '') : (copyButton.dataset.copyText || '');
            await copyText(text, copyButton);
            return;
          }}
          if (commandDialog && !commandDialog.hidden && event.target === commandDialog) {{
            closeCommand();
            return;
          }}
          const anchor = event.target.closest('.command-item[href^="#"]');
          if (anchor) {{
            const href = anchor.getAttribute('href') || '';
            if (href === '#files-panel') setDrawer('right', true);
            if (href === '#step-add') setDrawer('left', true);
            closeCommand();
          }}
        }});
        document.addEventListener('keydown', (event) => {{
          const key = event.key.toLowerCase();
          if ((event.ctrlKey || event.metaKey) && key === 'k') {{
            event.preventDefault();
            if (commandDialog && !commandDialog.hidden) closeCommand();
            else openCommand();
            return;
          }}
          if (event.key === 'Escape') {{
            if (commandDialog && !commandDialog.hidden) {{
              closeCommand();
              return;
            }}
            if (document.body.classList.contains('show-left-drawer') || document.body.classList.contains('show-right-drawer')) {{
              setDrawer('left', false);
              setDrawer('right', false);
            }}
            return;
          }}
          if (event.key === '/' && commandDialog && !commandDialog.hidden && commandSearch) {{
            event.preventDefault();
            commandSearch.focus();
            commandSearch.select();
          }}
        }});
        apply();
      }})();
      </script>
    </body>
    </html>
    """

def _parse_post_request(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    content_type = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0") or 0)
    body = handler.rfile.read(length) if length else b""
    if "multipart/form-data" in content_type:
        parser_input = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        message = BytesParser(policy=email_policy).parsebytes(parser_input)
        data: dict[str, str] = {}
        uploads: dict[str, dict[str, Any]] = {}
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                uploads[name] = {"filename": filename, "content": payload}
            else:
                try:
                    data[name] = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                except Exception:
                    data[name] = payload.decode("utf-8", errors="ignore")
        return data, uploads
    raw = body.decode("utf-8") if body else ""
    parsed = parse_qs(raw, keep_blank_values=True)
    return ({key: values[-1] if values else "" for key, values in parsed.items()}, {})



def _next_step_flash(project_dir: str, headline: str, extra_lines: list[str] | None = None) -> str:
    dashboard = project_dashboard(project_dir)
    lines = [headline]
    if extra_lines:
        lines.extend(extra_lines)
    lines.append("")
    lines.append("建议下一步：")
    for item in dashboard["next_steps"][:3]:
        lines.append(f"- {item['title']}")
    return "\n".join(lines)



def _make_handler(project_root: str, initial_project: str | None):
    class ResearchOSUIHandler(BaseHTTPRequestHandler):
        server_version = "ResearchOSUI/0.6.5"

        def log_message(self, format: str, *args) -> None:  # pragma: no cover - keep terminal clean
            return

        def _state_from_request(self, source: dict[str, str] | None = None) -> dict[str, str | None]:
            if source is None:
                query = parse_qs(urlparse(self.path).query)
                data = {key: values[-1] if values else "" for key, values in query.items()}
            else:
                data = source
            if data.get("project_dir") and not data.get("project"):
                data = dict(data)
                data["project"] = data.get("project_dir", "")
            return _normalize_state(data, initial_project)

        def _render(self, state: dict[str, str | None], *, flash: str | None = None, flash_level: str = "ok") -> None:
            body = _render_page(project_root, state, flash=flash, flash_level=flash_level)
            blob = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/download", "/file"}:
                query = {key: values[-1] if values else "" for key, values in parse_qs(parsed.query).items()}
                self._serve_download(query)
                return
            if parsed.path not in {"/", ""}:
                self.send_error(404, "Not Found")
                return
            self._render(self._state_from_request())

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/action":
                self.send_error(404, "Not Found")
                return
            data, uploads = _parse_post_request(self)
            state = self._state_from_request(data)
            action = (data.get("action") or "").strip()
            try:
                flash, flash_level, next_state = self._handle_action(action, data, uploads, state)
            except Exception as exc:  # pragma: no cover - defensive UI layer
                flash, flash_level, next_state = humanize_exception(exc), "error", state
            self._render(next_state, flash=flash, flash_level=flash_level)

        def _serve_download(self, query: dict[str, str]) -> None:
            project_dir = (query.get("project") or "").strip()
            if not project_dir:
                self.send_error(400, "Missing project")
                return
            workspace = WorkspaceSnapshot.load(project_dir)
            normalize_studio(workspace.studio, workspace.project)
            target_path = None
            try:
                if query.get("asset"):
                    asset_id = query["asset"]
                    asset = next((item for item in workspace.studio.get("assets", []) if item.get("asset_id") == asset_id), None)
                    if asset:
                        target_path = resolve_within_root(workspace.root, asset["local_path"])
                elif query.get("package"):
                    package_id = query["package"]
                    package = next((item for item in workspace.studio.get("packages", []) if item.get("package_id") == package_id), None)
                    if package:
                        target_path = resolve_within_root(workspace.root, package["zip_path"])
            except Exception:
                target_path = None
            if target_path is None or not target_path.exists():
                self.send_error(404, "File not found")
                return
            filename = query.get("filename") or target_path.name
            blob = target_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(target_path))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Content-Disposition", f'attachment; filename="{make_download_filename(filename)}"')
            self.end_headers()
            self.wfile.write(blob)

        def _handle_action(
            self,
            action: str,
            data: dict[str, str],
            uploads: dict[str, dict[str, Any]],
            state: dict[str, str | None],
        ) -> tuple[str, str, dict[str, str | None]]:
            project_dir = (data.get("project_dir") or state.get("project") or "").strip() or None

            if action == "create_project":
                root = data.get("root") or project_root
                title = (data.get("title") or "我的研究项目").strip() or "我的研究项目"
                name = (data.get("name") or "").strip() or next_available_name(root, title)
                owner = (data.get("owner") or detect_default_owner()).strip() or detect_default_owner()
                venue = (data.get("venue") or "未设定").strip() or "未设定"
                brief = (data.get("brief") or "").strip() or None
                starter_ai = (data.get("starter_ai") or "recommended").strip() or "recommended"
                target = create_project_from_template(root, name, title, owner=owner, venue=venue, brief=brief)
                workspace = WorkspaceSnapshot.load(target)
                normalize_studio(workspace.studio, workspace.project)
                starter_ai = apply_starter_ai_profile(workspace.studio, starter_ai)
                active_step_id = workspace.studio.get("active_step_id") or next((item.get("step_id") for item in workspace.studio.get("steps", []) if item.get("module_id") == "paper"), None)
                if active_step_id:
                    write_active_context(workspace.root, workspace.studio, workspace.project, active_step_id)
                workspace.save_state("studio")
                starter_label = {
                    "recommended": "推荐开始（ChatGPT）",
                    "chatgpt": "ChatGPT 网页",
                    "gemini": "Gemini 网页",
                    "api": "API",
                    "mock": "演练模式",
                }.get(starter_ai, starter_ai)
                next_state = _normalize_state({**{k: v or "" for k, v in state.items()}, "project": str(target), "tab": "project", "run": "", "task": "", "artifact": "", "session": "", "note": ""}, initial_project)
                flash = f"已创建项目：{target}\n- 默认开始方式：{starter_label}\n- 普通用户建议：先补一下目标 / 输出要求 / Prompt，再点上面的“开始生成”。"
                return flash, "ok", next_state

            if action == "create_demo":
                root = data.get("root") or project_root
                base_name = (data.get("name") or "research-os-demo").strip() or "research-os-demo"
                name = next_available_name(root, base_name)
                brief = (data.get("brief") or "").strip() or None
                target = copy_demo_project(root, name, brief=brief)
                next_state = _normalize_state({**{k: v or "" for k, v in state.items()}, "project": str(target), "tab": "project", "run": "", "task": "", "artifact": "", "session": "", "note": ""}, initial_project)
                flash = f"已复制示例项目：{target}\n- 现在也会默认进入 A线 · 论文。\n- 你可以直接在当前步骤里试一次 mock，或把共享文件生成交接包。"
                return flash, "ok", next_state

            if not project_dir:
                return "请先选择或创建一个项目。", "warn", state

            next_state = dict(state)
            next_state["project"] = project_dir

            if action == "set_step":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                if not step_id:
                    return "没有收到步骤 ID。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = set_active_step(workspace.studio, step_id)
                write_active_context(workspace.root, workspace.studio, workspace.project, step_id)
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return "已切换到当前步骤。", "ok", next_state

            if action in {"save_step", "save_prompt_template", "apply_prompt_template", "submit_workspace", "save_and_advance"}:
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                if not step_id:
                    return "没有收到步骤 ID。", "warn", next_state
                step = _save_step_with_surface_choice(workspace, step_id, data)
                if action == "apply_prompt_template":
                    template_key = (data.get("template_key") or "").strip()
                    if not template_key:
                        return "请先选择一个 Prompt 模板。", "warn", next_state
                    template = apply_prompt_template(workspace.studio, step_id, template_key)
                    flash = f"已套用模板：{template.get('name') or template.get('template_id')}。"
                elif action == "save_prompt_template":
                    template = save_prompt_template(
                        workspace.studio,
                        step_id,
                        name=(data.get("template_name") or "").strip(),
                        scope=(data.get("template_scope") or "project").strip() or "project",
                        prompt=(data.get("prompt") or step.get("prompt") or "").strip(),
                    )
                    flash = f"已保存 Prompt 模板：{template.get('name') or template.get('template_id')}。"
                elif action == "submit_workspace":
                    surface_choice = (data.get("surface_choice") or "inline").strip().lower() or "inline"
                    if surface_choice == "inline":
                        try:
                            run_openai_attempt(workspace.root, workspace.project, workspace.studio, step_id)
                            flash = "已在当前页面生成一版结果。\n- 结果会直接落到下面的 AI 输出里。\n- 先审一下，再决定是否进入下一步。"
                        except RuntimeError as exc:
                            if "not set" in str(exc):
                                fallback = {
                                    **data,
                                    "provider_mode": "mock",
                                    "provider_profile_id": "mock-local",
                                    "provider_name": "mock",
                                    "model_hint": "mock",
                                }
                                step = _save_step_with_surface_choice(workspace, step_id, fallback, force='mock')
                                run_mock_attempt(workspace.root, workspace.project, workspace.studio, step_id)
                                flash = "没有检测到 API key，已先给你一版本地演练结果。\n- 现在就能在页面里继续看输出。\n- 想直连真实模型的话，再配置 OpenAI / 兼容 API key。"
                            else:
                                raise
                    else:
                        target_label = "ChatGPT 网页" if surface_choice == "chatgpt" else "Gemini 网页"
                        package = create_handoff_package(
                            workspace.root,
                            workspace.studio,
                            workspace.project,
                            step_id,
                            include="inputs_and_primary",
                            target_label=target_label,
                            target_step_label=step.get("title") or step_id,
                            mode="manual_web",
                            prompt_override="",
                            notes=(data.get("operator_notes") or "").strip(),
                        )
                        flash = f"已准备好 {target_label} 交接包：{package['package_id']}。\n- 现在点下面的“打开 ChatGPT / Gemini”继续。\n- 也可以先点“复制 Prompt”，再去网页里生成结果。"
                elif action == "save_and_advance":
                    next_step = complete_step_and_advance(workspace.studio, step_id)
                    step = next_step or step
                    if next_step:
                        flash = f"已保存当前步骤，并切到下一步：{next_step.get('title') or next_step.get('step_id')}。\n- 系统会把上一步主输出自动挂到右侧文件中心里。"
                    else:
                        flash = "已保存当前步骤，并标记为通过。当前已经是本线最后一步。"
                else:
                    flash = "已保存当前步骤。\n- 现在可以直接在中间继续提交，或者切到下一步。"
                write_active_context(workspace.root, workspace.studio, workspace.project, step.get("step_id") or step_id)
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step.get("step_id") or step_id
                return flash, "ok", next_state

            if action == "add_step":
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                module_id = (data.get("module_id") or state.get("tab") or "paper").strip() or "paper"
                after_step_id = (data.get("task") or state.get("task") or "").strip() or None
                step = add_step(
                    workspace.studio,
                    module_id,
                    title=(data.get("title") or "新的步骤").strip() or "新的步骤",
                    goal=(data.get("goal") or "").strip(),
                    prompt=(data.get("prompt") or data.get("goal") or "").strip(),
                    after_step_id=after_step_id,
                )
                write_active_context(workspace.root, workspace.studio, workspace.project, step["step_id"])
                workspace.save_state("studio")
                next_state["tab"] = module_id
                next_state["task"] = step["step_id"]
                return f"已在 {module_id} 模块新增步骤：{step['title']}。", "ok", next_state

            if action == "add_substep":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                title = (data.get("title") or "").strip()
                goal = (data.get("goal") or "").strip()
                prompt = (data.get("prompt") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                child = add_substep(workspace.studio, step_id, title=title or "新的子步骤", goal=goal, prompt=prompt)
                write_active_context(workspace.root, workspace.studio, workspace.project, child["step_id"])
                workspace.save_state("studio")
                next_state["tab"] = child.get("module_id") or child.get("line_id") or "paper"
                next_state["task"] = child["step_id"]
                return f"已新增子步骤：{child['title']}。", "ok", next_state

            if action in {"move_step_up", "move_step_down"}:
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = move_step(workspace.studio, step_id, "up" if action == "move_step_up" else "down")
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return "已调整步骤顺序。", "ok", next_state

            if action == "delete_step":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = delete_step(workspace.studio, step_id)
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = ""
                return f"已删除步骤：{step['title']}。相关文件仍保留在共享文件库里。", "ok", next_state

            if action == "reopen_step":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = reopen_step(workspace.studio, step_id)
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return "已重开当前步骤。", "ok", next_state

            if action in {"run_mock_step", "run_openai_step"}:
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                write_active_context(workspace.root, workspace.studio, workspace.project, step_id)
                if action == "run_openai_step":
                    run_openai_attempt(workspace.root, workspace.project, workspace.studio, step_id)
                    headline = f"已通过 OpenAI / 兼容 API 运行当前步骤：{find_step(workspace.studio, step_id)['title']}"
                else:
                    run_mock_attempt(workspace.root, workspace.project, workspace.studio, step_id)
                    headline = f"已通过 mock 运行当前步骤：{find_step(workspace.studio, step_id)['title']}"
                workspace.save_state("studio")
                step = find_step(workspace.studio, step_id)
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return headline + "\n- 这次运行会自动生成一个新的尝试版本。\n- 请先审阅输出，再决定是否固定为当前最佳版本。", "ok", next_state

            if action == "upload_asset":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                role = (data.get("role") or "input").strip() or "input"
                upload = uploads.get("upload_file")
                if not upload or not upload.get("filename"):
                    return "没有收到上传文件。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                asset = register_asset(
                    workspace.root,
                    workspace.studio,
                    step_id,
                    role,
                    upload["filename"],
                    upload["content"],
                    source="user_upload" if role in {"input", "reference"} else "external_upload",
                    description=(data.get("description") or "").strip(),
                )
                if role in {"output", "final"}:
                    link_uploaded_result_to_latest_handoff(workspace.studio, step_id, asset["asset_id"])
                write_active_context(workspace.root, workspace.studio, workspace.project, step_id)
                workspace.save_state("studio")
                step = find_step(workspace.studio, step_id)
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return f"已把文件导入共享文件库，并挂到当前步骤：{asset.get('filename') or asset.get('name')}。", "ok", next_state

            if action == "link_asset":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                asset_id = (data.get("asset_id") or "").strip()
                if not asset_id:
                    return "请先选择一个已有文件。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                link_existing_asset(workspace.studio, step_id, asset_id, role=(data.get("role") or "reference").strip() or "reference")
                workspace.save_state("studio")
                step = find_step(workspace.studio, step_id)
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return f"已把文件 {asset_id} 引用到当前步骤。", "ok", next_state

            if action == "unlink_step_asset":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                asset_id = (data.get("asset_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                unlink_step_asset(workspace.studio, step_id, asset_id)
                workspace.save_state("studio")
                step = find_step(workspace.studio, step_id)
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return f"已取消当前步骤对文件 {asset_id} 的引用。", "ok", next_state

            if action == "mark_asset_primary":
                asset_id = (data.get("asset_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                asset = mark_asset_primary(workspace.studio, asset_id)
                workspace.save_state("studio")
                next_state["tab"] = asset.get("module_id") or asset.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = asset.get("step_id") or state.get("task")
                return f"已把 {asset.get('filename') or asset.get('name')} 设为当前角色的主版本。", "ok", next_state

            if action == "select_attempt":
                attempt_id = (data.get("attempt_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                attempt = select_attempt(workspace.studio, attempt_id)
                workspace.save_state("studio")
                next_state["tab"] = attempt.get("module_id") or attempt.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = attempt.get("step_id")
                return f"已把 {attempt_id} 设为当前最佳版本。", "ok", next_state

            if action == "compare_attempt":
                attempt_id = (data.get("attempt_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                attempt = next(item for item in workspace.studio.get("attempts", []) if item.get("attempt_id") == attempt_id)
                set_compare_attempt(workspace.studio, attempt.get("step_id") or "", attempt_id)
                workspace.save_state("studio")
                next_state["tab"] = attempt.get("module_id") or attempt.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = attempt.get("step_id")
                return f"已选中对比版本：{attempt_id}。", "ok", next_state

            if action == "clear_compare_attempt":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = set_compare_attempt(workspace.studio, step_id, None)
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = step_id
                return "已清空版本对比。", "ok", next_state

            if action == "promote_attempt_outputs":
                attempt_id = (data.get("attempt_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                attempt = mark_attempt_outputs_primary(workspace.studio, attempt_id)
                workspace.save_state("studio")
                next_state["tab"] = attempt.get("module_id") or attempt.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = attempt.get("step_id")
                return f"已把 {attempt_id} 的输出固定为主文件，并同步设为优选版本。", "ok", next_state

            if action == "review_attempt":
                attempt_id = (data.get("attempt_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                attempt = review_attempt(
                    workspace.studio,
                    attempt_id,
                    decision=(data.get("decision") or "candidate").strip() or "candidate",
                    human_review=(data.get("human_review") or "").strip(),
                    score=(data.get("review_score") or "").strip(),
                    tags=(data.get("review_tags") or "").strip(),
                )
                workspace.save_state("studio")
                next_state["tab"] = attempt.get("module_id") or attempt.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = attempt.get("step_id")
                return f"已保存 {attempt_id} 的人工审阅结论。", "ok", next_state

            if action == "branch_from_attempt":
                attempt_id = (data.get("attempt_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = branch_step_from_attempt(workspace.studio, attempt_id)
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or state.get("tab") or "paper"
                next_state["task"] = step.get("step_id")
                return f"已把 {attempt_id} 的 prompt snapshot 回填到当前步骤，你现在可以继续分叉调试。", "ok", next_state

            if action == "prepare_package":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                package = create_handoff_package(
                    workspace.root,
                    workspace.studio,
                    workspace.project,
                    step_id,
                    include=(data.get("include") or "primary_outputs").strip() or "primary_outputs",
                    target_label=(data.get("target_label") or "网页 AI").strip() or "网页 AI",
                    target_step_label=(data.get("target_step_label") or "下一步").strip() or "下一步",
                    mode=(data.get("mode") or "manual_web").strip() or "manual_web",
                    prompt_override=(data.get("prompt_override") or "").strip(),
                    notes=(data.get("notes") or "").strip(),
                )
                workspace.save_state("studio")
                step = find_step(workspace.studio, step_id)
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return f"已生成交接包：{package['package_id']}。\n- 包和 zip 都已落到 library/handoff_packages/。", "ok", next_state

            if action == "save_control":
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                update_control_from_form(workspace.studio, data)
                workspace.save_state("studio")
                next_state["tab"] = "control"
                return "已保存总控信息。", "ok", next_state

            if action == "save_provider_profile":
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                profile = upsert_provider_profile(
                    workspace.studio,
                    profile_id=(data.get("profile_id") or "").strip() or None,
                    name=(data.get("name") or "").strip(),
                    provider=(data.get("provider") or "openai").strip(),
                    base_url=(data.get("base_url") or "").strip(),
                    default_model=(data.get("default_model") or "").strip(),
                    api_key_env=(data.get("api_key_env") or "").strip(),
                    notes=(data.get("notes") or "").strip(),
                )
                workspace.save_state("studio")
                next_state["tab"] = "control"
                return f"已保存 provider profile：{profile.get('name') or profile.get('profile_id')}。", "ok", next_state

            if action == "delete_provider_profile":
                profile_id = (data.get("profile_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                profile = delete_provider_profile(workspace.studio, profile_id)
                workspace.save_state("studio")
                next_state["tab"] = "control"
                return f"已删除 provider profile：{profile.get('name') or profile_id}。", "ok", next_state

            if action == "rename_asset":
                asset_id = (data.get("asset_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                from .studio import rename_asset
                asset = rename_asset(workspace.root, workspace.studio, asset_id, (data.get("new_name") or "").strip())
                workspace.save_state("studio")
                next_state["tab"] = "control"
                return f"已重命名文件：{asset.get('filename') or asset.get('name')}。", "ok", next_state

            if action == "move_asset":
                asset_id = (data.get("asset_id") or "").strip()
                bucket = (data.get("bucket") or "shared").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                asset = move_asset(workspace.root, workspace.studio, asset_id, bucket)
                workspace.save_state("studio")
                next_state["tab"] = "control"
                return f"已把文件移动到 library/{asset.get('library_bucket')}。", "ok", next_state

            if action == "delete_asset":
                asset_id = (data.get("asset_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                asset = delete_asset(workspace.root, workspace.studio, asset_id)
                workspace.save_state("studio")
                next_state["tab"] = "control"
                return f"已删除文件：{asset.get('filename') or asset.get('name') or asset_id}。", "ok", next_state

            if action == "mark_step_review":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = find_step(workspace.studio, step_id)
                step["status"] = "review"
                step["updated_at"] = now_iso()
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return "已把这一步标记为等待你审阅。", "ok", next_state

            if action == "mark_step_done":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                step = find_step(workspace.studio, step_id)
                step["status"] = "done"
                step["updated_at"] = now_iso()
                workspace.save_state("studio")
                next_state["tab"] = step.get("module_id") or step.get("line_id") or "paper"
                next_state["task"] = step_id
                return "已把这一步标记为完成。", "ok", next_state

            if action == "advance_step":
                step_id = (data.get("task") or data.get("step_id") or "").strip()
                workspace = WorkspaceSnapshot.load(project_dir)
                normalize_studio(workspace.studio, workspace.project)
                current = find_step(workspace.studio, step_id)
                next_step = complete_step_and_advance(workspace.studio, step_id)
                workspace.save_state("studio")
                next_state["tab"] = current.get("module_id") or current.get("line_id") or "paper"
                next_state["task"] = next_step.get("step_id") if next_step else step_id
                if next_step:
                    return f"已通过当前步骤，并切换到下一步：{next_step.get('title') or next_step.get('step_id')}。", "ok", next_state
                return "已通过当前步骤。当前已经是这个模块的最后一步。", "ok", next_state

            if action == "run_next":
                result = run_once(project_dir, provider_name="mock", auto_execute=True)
                session_id = result.get("session_id") or "未记录"
                flash = _next_step_flash(project_dir, "已完成一次推进。", [f"- 会话：{session_id}", "- 页面已刷新为最新项目状态。"])
                return flash, "ok", next_state

            if action == "run_loop":
                steps = int(data.get("steps", "3") or 3)
                result = run_workloop(project_dir, provider_name="mock", steps=steps, auto_execute=True)
                history = result.get("history", [])
                flash = _next_step_flash(project_dir, f"已连续推进 {len(history)} 步。", ["- 你现在更适合看“最近进展”和“任务记录”。"])
                return flash, "ok", next_state

            if action == "approve_next":
                workspace = WorkspaceSnapshot.load(project_dir)
                pending = pick_pending_approval(workspace)
                if pending is None:
                    return "当前没有待确认事项。", "ok", next_state
                if pending["kind"] == "gate":
                    workspace.update_gate(pending["id"], status="approved", approved_by="web-ui", approved_note="Approved from web UI")
                    sync_project_sqlite(project_dir)
                    flash = _next_step_flash(project_dir, f"已批准：{pending['title']}。", ["- 这通常意味着系统可以继续往前走了。"])
                    return flash, "ok", next_state
                approve_run(workspace, pending["id"], by="web-ui", note="Approved from web UI", queue_after=True)
                next_state["tab"] = "runs"
                next_state["run"] = pending["id"]
                flash = _next_step_flash(project_dir, f"已批准并继续：{pending['title']}。", ["- 页面已跳到任务记录，方便你继续看结果。"])
                return flash, "ok", next_state

            if action == "approve_gate":
                gate_id = (data.get("gate_id") or "").strip()
                if not gate_id:
                    return "没有收到 gate_id。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                workspace.update_gate(gate_id, status="approved", approved_by="web-ui", approved_note="Approved from web UI")
                sync_project_sqlite(project_dir)
                flash = _next_step_flash(project_dir, f"已批准人工确认：{gate_id}。", ["- 继续推进一步，通常就会看到新的阶段变化。"])
                return flash, "ok", next_state

            if action == "approve_run":
                run_id = (data.get("run_id") or "").strip()
                if not run_id:
                    return "没有收到 run_id。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                approve_run(workspace, run_id, by="web-ui", note="Approved from web UI", queue_after=True)
                next_state["tab"] = "runs"
                next_state["run"] = run_id
                flash = _next_step_flash(project_dir, f"已批准任务 {run_id}，并已自动继续排队。", ["- 你现在可以继续留在任务记录里看它的最新状态。"])
                return flash, "ok", next_state

            if action == "retry_run":
                run_id = (data.get("run_id") or "").strip()
                if not run_id:
                    return "没有收到 run_id。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                retry_run(workspace, run_id, by="web-ui", reset_attempts=False)
                next_state["tab"] = "runs"
                next_state["run"] = run_id
                flash = _next_step_flash(project_dir, f"已重新排队：{run_id}。", ["- 如果你使用本地执行器，可以再点一次“让本地执行器处理”。"])
                return flash, "ok", next_state

            if action == "cancel_run":
                run_id = (data.get("run_id") or "").strip()
                if not run_id:
                    return "没有收到 run_id。", "warn", next_state
                workspace = WorkspaceSnapshot.load(project_dir)
                cancel_run(workspace, run_id, by="web-ui", note="Cancelled from web UI")
                next_state["tab"] = "runs"
                next_state["run"] = run_id
                flash = _next_step_flash(project_dir, f"已取消任务：{run_id}。", ["- 如果这是一条误触任务，现在已经不会继续执行。"])
                return flash, "warn", next_state

            if action == "audit":
                out = build_audit_report(project_dir)
                next_state["tab"] = "doctor"
                flash = _next_step_flash(project_dir, f"已生成审计报告：{out}", ["- 这份报告会落在 reports/ 目录里。"])
                return flash, "ok", next_state

            if action == "doctor":
                report = doctor_report(project_dir, root=project_root)
                level = {"pass": "ok", "warn": "warn", "fail": "error"}[report["overall"]]
                lines = [f"健康检查结果：{ {'pass': '通过', 'warn': '有提醒', 'fail': '需要修复'}.get(report['overall'], report['overall']) }"]
                for item in report["checks"][:8]:
                    lines.append(f"- {item['title']}：{item.get('detail') or ''}")
                    if item.get("fix"):
                        lines.append(f"  建议：{item['fix']}")
                next_state["tab"] = "doctor"
                return "\n".join(lines), level, next_state

            if action == "run_worker":
                results = run_worker(project_dir, worker_id="web-ui-worker", max_runs=1, worker_labels=["local", "shell"])
                if not results:
                    next_state["tab"] = "runs"
                    return "当前没有可由本地执行器处理的任务。", "warn", next_state
                next_state["tab"] = "runs"
                flash = _next_step_flash(project_dir, f"本地执行器已处理 {len(results)} 个任务。", ["- 页面已更新为最新结果。"])
                return flash, "ok", next_state

            return f"暂不支持的动作：{action}", "warn", next_state


    return ResearchOSUIHandler



def serve_ui(
    project_dir: str | None = None,
    *,
    root: str | Path = "projects",
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> None:
    project_root = str(Path(root).resolve())
    initial = str(Path(project_dir).resolve()) if project_dir else None
    handler_cls = _make_handler(project_root, initial)
    httpd = ThreadingHTTPServer((host, port), handler_cls)
    query = urlencode({"project": initial}) if initial else ""
    url = f"http://{host}:{port}/?{query}" if query else f"http://{host}:{port}/"
    print(f"{APP_NAME} Web UI 已启动：{url}")
    print("按 Ctrl+C 停止。")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止 Web UI。")
    finally:
        httpd.server_close()
