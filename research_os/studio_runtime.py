from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .common import now_iso
from .studio import (
    asset_text_preview,
    complete_attempt_text_output,
    create_attempt,
    find_provider_profile,
    find_step,
    step_context_text,
)


def run_mock_attempt(root: str | Path, project: dict[str, Any], studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    attempt = create_attempt(studio, step_id)
    text = _mock_markdown(root, project, studio, step_id, attempt["attempt_id"])
    asset = complete_attempt_text_output(root, studio, attempt["attempt_id"], text, filename_hint=f"{step_id}_{attempt['attempt_id']}.md", source="mock_provider")
    attempt["status"] = "review"
    attempt["summary"] = f"Mock provider generated a structured step draft for {step['title']}."
    step["status"] = "review"
    step["updated_at"] = now_iso()
    return {"attempt": attempt, "asset": asset, "preview": text[:600]}


def run_openai_attempt(root: str | Path, project: dict[str, Any], studio: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = find_step(studio, step_id)
    profile = find_provider_profile(studio, step.get("provider_profile_id")) or {}
    api_key_env = profile.get("api_key_env") or "OPENAI_API_KEY"
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} not set. 如果你要直接 API 运行，请先配置 key；否则用“生成交接包”模式。")
    attempt = create_attempt(studio, step_id)
    payload = _openai_payload(root, project, studio, step_id)
    model = step.get("provider_name") or profile.get("default_model") or step.get("model_hint") or "gpt-4.1-mini"
    body = {
        "model": model,
        "input": payload,
    }
    base_url = profile.get("base_url") or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI API error: {exc.code} {detail[:400]}") from exc
    text = _extract_openai_text(response)
    if not text.strip():
        raise RuntimeError("OpenAI API returned no text output for this step attempt.")
    asset = complete_attempt_text_output(root, studio, attempt["attempt_id"], text, filename_hint=f"{step_id}_{attempt['attempt_id']}.md", source="openai_api")
    attempt["status"] = "review"
    attempt["summary"] = text[:400]
    attempt["provider_response_id"] = response.get("id")
    attempt["provider"] = profile.get("name") or step.get("provider_name") or step.get("provider_mode") or "openai"
    attempt["model"] = model
    step["status"] = "review"
    step["updated_at"] = now_iso()
    return {"attempt": attempt, "asset": asset, "preview": text[:600], "provider_meta": {"response_id": response.get("id")}}


def _openai_payload(root: str | Path, project: dict[str, Any], studio: dict[str, Any], step_id: str) -> list[dict[str, Any]]:
    step = find_step(studio, step_id)
    context = step_context_text(studio, project, step_id, root)
    parts = [
        "你现在不是在做通用闲聊，而是在协助一个论文项目平台里的当前步骤。",
        context,
        "请直接给出当前步骤最有用的产出，不要泛泛而谈。",
        "如果当前输入里有文本文件，请结合这些文件继续工作；如果有二进制文件，你会只看到文件说明。",
        "输出尽量结构化，便于后续继续手工调试或交接给下一个 AI。",
    ]
    from .studio import assets_for_step

    for asset in assets_for_step(studio, step_id):
        if asset.get("role") in {"input", "reference"}:
            parts.append(f"\n[Input File] {asset['asset_id']} | {asset['name']} | {asset['mime_type']}")
            parts.append(asset_text_preview(root, asset, limit=10000))
    return [{"role": "user", "content": "\n\n".join(parts)}]


def _extract_openai_text(response: dict[str, Any]) -> str:
    output = response.get("output", []) or []
    chunks: list[str] = []
    for item in output:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"}:
                if "text" in content and isinstance(content["text"], str):
                    chunks.append(content["text"])
                elif isinstance(content.get("text"), dict):
                    chunks.append(content["text"].get("value", ""))
    if chunks:
        return "\n".join(chunk for chunk in chunks if chunk)
    if response.get("output_text"):
        return str(response.get("output_text"))
    return ""


def _mock_markdown(root: str | Path, project: dict[str, Any], studio: dict[str, Any], step_id: str, attempt_id: str) -> str:
    step = find_step(studio, step_id)
    from .studio import assets_for_step

    lines = [
        f"# {step['title']} · Mock Attempt {attempt_id}",
        "",
        "## 当前步骤目标",
        step.get("goal") or "",
        "",
        "## 当前提示词",
        step.get("prompt") or "",
        "",
        "## 推荐输出",
        step.get("output_expectation") or "",
        "",
        "## 可继续推进的草稿",
        f"- 我会先围绕“{step['title']}”给出第一版结构化结果。",
        f"- 项目总目标：{studio.get('brief') or project.get('current_goal') or ''}",
        f"- 建议使用：{step.get('provider_name') or step.get('model_hint') or '-'}",
        "- 推进后请先人工审阅，再决定是否修改 prompt、拆分步骤或继续下一步。",
        "",
        "## 输入文件摘要",
    ]
    assets = assets_for_step(studio, step_id)
    if not assets:
        lines.append("- 当前这一步还没有挂任何输入文件。")
    else:
        for asset in assets:
            if asset.get("role") in {"input", "reference"}:
                preview = asset_text_preview(root, asset, limit=1200)
                lines.extend([
                    f"### {asset['asset_id']} · {asset['name']}",
                    preview,
                    "",
                ])
    lines.extend([
        "## 下一步建议",
        "1. 如果这个方向还不够精确，就继续改 prompt 并重跑。",
        "2. 如果需要更细粒度调试，就在当前步骤下面再拆一个子步骤。",
        "3. 如果这个结果要交给另一个 AI，会更适合先生成交接包。",
    ])
    return "\n".join(lines) + "\n"
