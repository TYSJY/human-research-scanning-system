from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .common import load_json, lookup_path, now_iso, resource_path
from .planner import build_plan, load_reasoning_profiles
from .scheduler import build_scheduler_snapshot
from .workspace import WorkspaceSnapshot


def _base_action(agent: str, profile: str, stage: str, summary: str) -> dict[str, Any]:
    return {
        "agent": agent,
        "profile": profile,
        "summary": summary,
        "recommendations": [],
        "stage_decision": {
            "current_stage": stage,
            "proposed_stage": stage,
            "advance_ready": False,
            "rationale": summary,
        },
        "task_updates": [],
        "state_updates": [],
        "note_updates": [],
        "tool_calls": [],
        "requested_gates": [],
        "warnings": [],
    }


class MockProvider:
    name = "mock"

    def run(self, agent_name: str, workspace: WorkspaceSnapshot, profile: str, user_context: dict[str, Any] | None = None) -> dict[str, Any]:
        plan = build_plan(workspace, persist=False)
        stage = plan["current_stage"]

        if agent_name == "controller":
            action = _base_action("controller", profile, stage, "Controller routed from task graph, runtime backlog, and stage exit constraints.")
            action["recommendations"] = plan["recommendations"]
            action["requested_gates"] = plan["requested_gates"]
            action["stage_decision"]["advance_ready"] = plan["advance_ready"]
            action["stage_decision"]["proposed_stage"] = plan["proposed_stage"]
            action["stage_decision"]["rationale"] = f"handoff_reason={plan['handoff_reason']}"
            if plan["advance_ready"] and plan.get("proposed_stage") and plan["proposed_stage"] != stage:
                action["tool_calls"].append({"tool": "transition_stage", "arguments": {"stage": plan["proposed_stage"]}})
            return {
                "action_plan": action,
                "provider_meta": {"provider": "mock", "mode": "structured", "generated_at": now_iso()},
            }

        if agent_name == "scan":
            action = _base_action("scan", profile, stage, "Scan agent populated evidence, baselines, and novelty notes.")
            existing_evidence = len(workspace.evidence_registry.get("items", []))
            while existing_evidence < 3:
                idx = existing_evidence + 1
                action["tool_calls"].append(
                    {
                        "tool": "register_evidence",
                        "arguments": {
                            "evidence_id": f"E{idx}",
                            "title": f"关键证据条目 {idx}",
                            "kind": "literature" if idx == 1 else "analysis",
                            "notes": "由 mock provider 生成的占位证据。真实系统应由 scan agent 基于外部检索替换。",
                            "source_refs": [],
                        },
                    }
                )
                existing_evidence += 1
            existing_baselines = len(workspace.baseline_registry.get("items", []))
            baseline_names = ["weight-only", "kv-only", "pipeline-combo"]
            while existing_baselines < 3:
                idx = existing_baselines + 1
                action["tool_calls"].append(
                    {
                        "tool": "register_baseline",
                        "arguments": {
                            "baseline_id": f"B{idx}",
                            "name": baseline_names[idx - 1],
                            "kind": "baseline",
                            "notes": "由 mock provider 生成的最小 baseline 地图。",
                        },
                    }
                )
                existing_baselines += 1
            action["note_updates"].append(
                {
                    "path": "notes/novelty_audit.md",
                    "mode": "replace_if_placeholder",
                    "content": "# Novelty Audit\n\n## 红线\n- 不能把简单 pipeline 改名为 unified budgeter。\n- 不能在没有失败边界时宣称全局最优。\n\n## Reviewer Priors\n- 最接近 baseline 是否已经覆盖相同思想？\n- 效益是否仅在单一模型或上下文长度成立？\n- 是否存在高风险命令、手工步骤或外部 runner 依赖？\n",
                }
            )
            action["note_updates"].append(
                {
                    "path": "notes/reviewer_priors.md",
                    "mode": "replace_if_placeholder",
                    "content": "# Reviewer Priors\n\n- 先找最接近工作，再决定 claim 强度。\n- 没有 baseline 差异图，不要升级 claim。\n- 没有 evaluator green，不要提前写强结论。\n",
                }
            )
            action["requested_gates"] = plan["requested_gates"]
            return {
                "action_plan": action,
                "provider_meta": {"provider": "mock", "mode": "structured", "generated_at": now_iso()},
            }

        if agent_name == "design":
            action = _base_action("design", profile, stage, "Design agent defined claims, acceptance checks, and MVP boundaries.")
            if len(workspace.claims.get("claims", [])) == 0:
                action["state_updates"].append(
                    {
                        "state_key": "claims",
                        "operation": "replace_root",
                        "payload": {
                            "claims": [
                                {
                                    "claim_id": "C1",
                                    "text": "统一资源预算驱动的联合压缩，在固定精度损失阈值下，比 pipeline-combo baseline 更稳定地降低峰值显存和 decode 时延。",
                                    "status": "draft",
                                    "evidence_refs": [item.get("evidence_id") for item in workspace.evidence_registry.get("items", [])[:3]],
                                    "risk_refs": ["R1"],
                                    "success_metric": "peak_vram 和 decode_latency 同时改善",
                                    "acceptance_checks": [
                                        {"check_id": "AC1", "metric": "peak_vram_delta_pct", "operator": "<=", "threshold": -10},
                                        {"check_id": "AC2", "metric": "decode_latency_delta_pct", "operator": "<=", "threshold": -8},
                                        {"check_id": "AC3", "metric": "accuracy_delta_pct", "operator": ">=", "threshold": -1.0},
                                    ],
                                }
                            ],
                            "edges": [],
                        },
                    }
                )
            if not workspace.mvp.get("mvp_name"):
                action["state_updates"].append(
                    {
                        "state_key": "mvp",
                        "operation": "merge_root",
                        "payload": {
                            "mvp_name": "joint-budget-mvp",
                            "question": "统一预算器是否优于 pipeline-combo baseline？",
                            "model": workspace.project.get("constraints", {}).get("default_model", "sample-model"),
                            "dataset": workspace.project.get("constraints", {}).get("default_dataset", "sample-dataset"),
                            "success_criteria": [
                                "peak_vram improves",
                                "decode_latency improves",
                                "accuracy drop stays under threshold",
                            ],
                            "fallback_if_fail": ["降级 claim", "缩为两元联合压缩"],
                        },
                    }
                )
            action["note_updates"].append(
                {
                    "path": "notes/claim_evidence_map.md",
                    "mode": "replace_if_placeholder",
                    "content": "# Claim → Evidence Map\n\n## C1\n- Need: 最接近 baseline、主表效率结果、失败边界。\n- Acceptance checks: peak_vram / decode_latency / accuracy 三个指标均有明确阈值。\n- Risk: 收益可能只在特定上下文长度成立。\n",
                }
            )
            action["requested_gates"] = plan["requested_gates"]
            return {
                "action_plan": action,
                "provider_meta": {"provider": "mock", "mode": "structured", "generated_at": now_iso()},
            }

        if agent_name == "execution":
            action = _base_action("execution", profile, stage, "Execution agent created or resumed a runnable MVP experiment.")
            runs = workspace.run_registry.get("runs", [])
            scheduler = build_scheduler_snapshot(workspace, worker_labels=[])
            if not runs:
                run_id = f"{time.strftime('%Y%m%d')}_joint-budget-mvp"
                action["tool_calls"].append(
                    {
                        "tool": "create_run",
                        "arguments": {
                            "run_id": run_id,
                            "task_id": "execute.runtime.mvp",
                            "queue_group": "joint-budget-mvp",
                            "reasoning_profile": profile,
                            "worker_requirements": {"labels": ["local", "shell"]},
                            "selector": {"group": "joint-budget-mvp", "min_score_to_promote": 75, "stop_after_preferred": True},
                            "manifest": {
                                "run_id": run_id,
                                "question": workspace.mvp.get("question", "replace-me"),
                                "model": workspace.mvp.get("model", "replace-me"),
                                "dataset": workspace.mvp.get("dataset", "replace-me"),
                                "baselines": ["weight-only", "kv-only", "pipeline-combo"],
                                "metrics": [
                                    "accuracy",
                                    "peak_vram_gb",
                                    "decode_latency_ms",
                                    "peak_vram_delta_pct",
                                    "decode_latency_delta_pct",
                                    "accuracy_delta_pct",
                                ],
                                "hardware": workspace.project.get("constraints", {}).get("hardware", "replace-me"),
                                "status": "planned",
                            },
                            "request": {
                                "executor": "shell",
                                "command": [
                                    "python",
                                    "-c",
                                    "import json, pathlib; pathlib.Path('metrics.json').write_text(json.dumps({'metrics': {'accuracy': 0.948, 'peak_vram_gb': 10.4, 'decode_latency_ms': 42.1, 'peak_vram_delta_pct': -18.7, 'decode_latency_delta_pct': -14.2, 'accuracy_delta_pct': -0.6}}, ensure_ascii=False, indent=2), encoding='utf-8')",
                                ],
                                "timeout_sec": 60,
                                "metrics_output": "metrics.json",
                                "resource_budget": {"estimated_gpu_hours": 0.05, "estimated_tokens": 0},
                                "expected_artifacts": [
                                    {"path": "stdout.log", "kind": "log", "required": True, "promote_to_artifact_registry": False},
                                    {"path": "stderr.log", "kind": "log", "required": True, "promote_to_artifact_registry": False},
                                    {"path": "metrics.json", "kind": "metrics", "required": True, "promote_to_artifact_registry": True}
                                ],
                                "register_results": [
                                    {"result_id": "R001", "claim_id": "C1", "metric": "peak_vram_delta_pct", "value_path": "metrics.peak_vram_delta_pct", "notes": "vs pipeline-combo"},
                                    {"result_id": "R002", "claim_id": "C1", "metric": "decode_latency_delta_pct", "value_path": "metrics.decode_latency_delta_pct", "notes": "vs pipeline-combo"},
                                    {"result_id": "R003", "claim_id": "C1", "metric": "accuracy_delta_pct", "value_path": "metrics.accuracy_delta_pct", "notes": "vs pipeline-combo"},
                                ],
                            },
                        },
                    }
                )
                action["tool_calls"].append({"tool": "queue_run", "arguments": {"run_id": run_id, "priority": "high"}})
            else:
                planned = [run for run in runs if run.get("status") == "planned"]
                if planned:
                    action["tool_calls"].append({"tool": "queue_run", "arguments": {"run_id": planned[0]["run_id"], "priority": planned[0].get("priority", "high")}})
                elif scheduler.get("dispatchable"):
                    action["recommendations"].append(f"已有可调度 run：{scheduler['dispatchable'][0]['run_id']}，启动匹配标签 worker 即可继续执行。")
                elif scheduler.get("waiting"):
                    first_waiting = scheduler["waiting"][0]
                    action["warnings"].append(f"Runtime waiting: {first_waiting['run_id']} -> {','.join(first_waiting.get('reasons', []))}")
            action["note_updates"].append(
                {
                    "path": "notes/results_synthesis.md",
                    "mode": "replace_if_placeholder",
                    "content": "# Results Synthesis\n\n- 等第一批真实 metrics 回来后，再写效率/精度 trade-off。\n- 只有 evaluator green、selector 选出 preferred run 且 acceptance checks 覆盖后，才能提升 claim 级别。\n- 若 scheduler 显示 waiting/blocked，先修运行闭环再写结论。\n",
                }
            )
            return {
                "action_plan": action,
                "provider_meta": {"provider": "mock", "mode": "structured", "generated_at": now_iso()},
            }

        if agent_name == "writing":
            action = _base_action("writing", profile, stage, "Writing agent grounded notes in registered and evaluated results.")
            if workspace.metrics_summary()["result_count"] < 1:
                action["warnings"].append("No registered results yet; keep paper notes conservative.")
            else:
                action["note_updates"].append(
                    {
                        "path": "notes/title_abstract.md",
                        "mode": "replace_if_placeholder",
                        "content": "# Title + Abstract\n\nTitle: 保守标题，避免过早宣称全局最优。\n\nAbstract draft:\n- 问题：边端推理的参数、prefill、decode 预算存在错配。\n- 方法：统一资源预算驱动的联合压缩。\n- 证据：仅引用 results_registry 中已注册且 evaluator 通过的结果。\n- 边界：明确模型、数据和阈值条件。\n",
                    }
                )
                action["note_updates"].append(
                    {
                        "path": "notes/outline.md",
                        "mode": "replace_if_placeholder",
                        "content": "# Outline\n\n1. Problem and budget mismatch\n2. Unified budgeter design\n3. MVP setup and runtime policy\n4. Main results from results_registry\n5. Failure boundaries and limitations\n",
                    }
                )
            return {
                "action_plan": action,
                "provider_meta": {"provider": "mock", "mode": "structured", "generated_at": now_iso()},
            }

        if agent_name == "audit":
            action = _base_action("audit", profile, stage, "Audit agent checked artifacts, provenance, and release discipline.")
            if len(workspace.artifact_registry.get("items", [])) == 0:
                action["tool_calls"].extend(
                    [
                        {"tool": "register_artifact", "arguments": {"name": "configs", "status": "partial", "owner": workspace.project.get("owner"), "notes": "补齐训练/推理配置"}},
                        {"tool": "register_artifact", "arguments": {"name": "scripts", "status": "partial", "owner": workspace.project.get("owner"), "notes": "补齐运行脚本"}},
                        {"tool": "register_artifact", "arguments": {"name": "tables", "status": "partial", "owner": workspace.project.get("owner"), "notes": "检查主表与正文一致性"}},
                    ]
                )
            action["note_updates"].append(
                {
                    "path": "notes/release_checklist.md",
                    "mode": "replace_if_placeholder",
                    "content": "# Release Checklist\n\n- [ ] configs 可直接运行\n- [ ] 结果表与正文一致\n- [ ] 失败案例和限制已写入\n- [ ] artifact/output manifest 完整\n",
                }
            )
            action["requested_gates"] = plan["requested_gates"]
            return {
                "action_plan": action,
                "provider_meta": {"provider": "mock", "mode": "structured", "generated_at": now_iso()},
            }

        raise ValueError(f"Unknown mock agent: {agent_name}")


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path).resolve() if config_path else resource_path("configs", "provider_profiles.example.json")
        self.config = load_json(self.config_path, {})
        self.reasoning_profiles = load_reasoning_profiles().get("profiles", {})
        self.schema = load_json(resource_path("control_plane", "schemas", "action_plan.schema.json"), {})
        self.api_base = os.environ.get("OPENAI_API_BASE", self.config.get("api_base", "https://api.openai.com/v1"))

    def run(self, agent_name: str, workspace: WorkspaceSnapshot, profile: str, user_context: dict[str, Any] | None = None) -> dict[str, Any]:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set. Use --provider mock or export your key first.")

        user_context = user_context or {}
        profile_cfg = self.resolve_profile_config(profile)
        model_id = profile_cfg.get("model")
        if not model_id:
            raise RuntimeError(f"Profile {profile!r} missing model in {self.config_path}")
        mode = profile_cfg.get("mode", "structured")
        if mode == "tool_loop":
            result = self._run_tool_loop(api_key, model_id, agent_name, workspace, profile, profile_cfg, user_context)
        else:
            result = self._run_structured(api_key, model_id, agent_name, workspace, profile, profile_cfg, user_context)
        result.setdefault("provider_meta", {})
        result["provider_meta"].setdefault("session_id", user_context.get("session_id"))
        result["provider_meta"].setdefault("agent", agent_name)
        result["provider_meta"].setdefault("profile", profile)
        result["provider_meta"].setdefault("model", model_id)
        result["provider_meta"].setdefault("profile_config", {k: v for k, v in profile_cfg.items() if k != "api_key"})
        return result

    def resolve_profile_config(self, profile: str) -> dict[str, Any]:
        base = dict(lookup_path(self.reasoning_profiles, profile, {}))
        cfg = dict(self.config.get("profiles", {}).get(profile, {}))
        merged = dict(base.get("provider_defaults", {}))
        merged.update(cfg)
        merged.setdefault("mode", "structured")
        return merged

    def _run_structured(
        self,
        api_key: str,
        model_id: str,
        agent_name: str,
        workspace: WorkspaceSnapshot,
        profile: str,
        profile_cfg: dict[str, Any],
        user_context: dict[str, Any],
    ) -> dict[str, Any]:
        body = self._base_body(model_id, workspace, agent_name, profile, profile_cfg, user_context)
        body["text"] = {"format": {"type": "json_schema", "name": "research_os_action_plan", "schema": self.schema, "strict": True}}
        response = self._create_response(api_key, body)
        if body.get("background"):
            response = self._poll_background_response(api_key, response["id"])
        text = self._extract_text(response)
        action_plan = json.loads(text)
        return {
            "action_plan": action_plan,
            "provider_meta": {
                "provider": "openai",
                "response_id": response.get("id"),
                "mode": "structured",
                "status": response.get("status"),
                "generated_at": now_iso(),
            },
        }

    def _run_tool_loop(
        self,
        api_key: str,
        model_id: str,
        agent_name: str,
        workspace: WorkspaceSnapshot,
        profile: str,
        profile_cfg: dict[str, Any],
        user_context: dict[str, Any],
    ) -> dict[str, Any]:
        system_prompt = self._system_prompt(agent_name)
        tools = self._tool_loop_definitions()
        input_items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "workspace_summary": self._workspace_summary(workspace),
                        "plan": build_plan(workspace, persist=False),
                        "user_context": user_context,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            }
        ]
        previous_response_id = self._resolve_previous_response_id(workspace, agent_name, profile, profile_cfg)
        latest_response: dict[str, Any] | None = None
        max_rounds = int(profile_cfg.get("max_tool_rounds", 6) or 6)
        for _ in range(max_rounds):
            body = {
                "model": model_id,
                "instructions": system_prompt,
                "input": input_items,
                "tools": tools,
                "parallel_tool_calls": bool(profile_cfg.get("parallel_tool_calls", False)),
                "max_tool_calls": int(profile_cfg.get("max_tool_calls", 8)),
                "metadata": {
                    "project_slug": workspace.project.get("project_slug", "unknown"),
                    "agent": agent_name,
                    "profile": profile,
                    "session_id": user_context.get("session_id"),
                },
            }
            if previous_response_id:
                body["previous_response_id"] = previous_response_id
            if profile_cfg.get("reasoning_effort"):
                body["reasoning"] = {"effort": profile_cfg["reasoning_effort"]}
            if profile_cfg.get("max_output_tokens"):
                body["max_output_tokens"] = int(profile_cfg["max_output_tokens"])
            if profile_cfg.get("background"):
                body["background"] = True
            response = self._create_response(api_key, body)
            latest_response = response
            if body.get("background"):
                response = self._poll_background_response(api_key, response["id"])
                latest_response = response
            function_calls = [item for item in response.get("output", []) if item.get("type") == "function_call"]
            if not function_calls:
                text = self._extract_text(response)
                action_plan = json.loads(text)
                return {
                    "action_plan": action_plan,
                    "provider_meta": {
                        "provider": "openai",
                        "response_id": response.get("id"),
                        "mode": "tool_loop",
                        "status": response.get("status"),
                        "generated_at": now_iso(),
                    },
                }

            input_items.extend(response.get("output", []))
            previous_response_id = response.get("id")
            for call in function_calls:
                name = call["name"]
                arguments = json.loads(call.get("arguments", "{}") or "{}")
                if name == "submit_action_plan":
                    return {
                        "action_plan": arguments,
                        "provider_meta": {
                            "provider": "openai",
                            "response_id": response.get("id"),
                            "mode": "tool_loop",
                            "status": response.get("status"),
                            "generated_at": now_iso(),
                        },
                    }
                tool_output = self._execute_read_tool(workspace, name, arguments)
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": json.dumps(tool_output, ensure_ascii=False),
                    }
                )
        raise RuntimeError(f"Tool loop exceeded max rounds for agent {agent_name}. Last response: {latest_response}")

    def _resolve_previous_response_id(self, workspace: WorkspaceSnapshot, agent_name: str, profile: str, profile_cfg: dict[str, Any]) -> str | None:
        if not profile_cfg.get("use_previous_response_id"):
            return None
        continuation_key = f"{agent_name}:{profile}"
        continuations = workspace.runtime.get("continuations", {})
        return lookup_path(continuations, f"{continuation_key}.response_id")

    def _base_body(
        self,
        model_id: str,
        workspace: WorkspaceSnapshot,
        agent_name: str,
        profile: str,
        profile_cfg: dict[str, Any],
        user_context: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "workspace_summary": self._workspace_summary(workspace),
            "plan": build_plan(workspace, persist=False),
            "claims": workspace.claims,
            "mvp": workspace.mvp,
            "results_registry": workspace.results_registry,
            "artifact_registry": workspace.artifact_registry,
            "evaluation_registry": {
                "evaluations": workspace.evaluations_for_target("run", user_context.get("focus_run_id", "")) if user_context.get("focus_run_id") else workspace.evaluation_registry.get("evaluations", [])[-10:],
            },
            "user_context": user_context,
        }
        body: dict[str, Any] = {
            "model": model_id,
            "instructions": self._system_prompt(agent_name),
            "input": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "parallel_tool_calls": bool(profile_cfg.get("parallel_tool_calls", False)),
            "max_tool_calls": int(profile_cfg.get("max_tool_calls", 4)),
            "metadata": {
                "project_slug": workspace.project.get("project_slug", "unknown"),
                "agent": agent_name,
                "profile": profile,
                "session_id": user_context.get("session_id"),
            },
        }
        if profile_cfg.get("reasoning_effort"):
            body["reasoning"] = {"effort": profile_cfg["reasoning_effort"]}
        if profile_cfg.get("max_output_tokens"):
            body["max_output_tokens"] = int(profile_cfg["max_output_tokens"])
        if profile_cfg.get("background"):
            body["background"] = True
        previous_response_id = self._resolve_previous_response_id(workspace, agent_name, profile, profile_cfg)
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        return body

    def _system_prompt(self, agent_name: str) -> str:
        prompt_path = resource_path("control_plane", "prompts", f"{agent_name}_agent.md")
        return prompt_path.read_text(encoding="utf-8")

    def _workspace_summary(self, workspace: WorkspaceSnapshot) -> dict[str, Any]:
        plan = build_plan(workspace, persist=False)
        scheduler = build_scheduler_snapshot(workspace, worker_labels=[])
        return {
            "project": workspace.project,
            "stage_state": workspace.stage_state,
            "metrics": workspace.metrics_summary(),
            "top_open_tasks": plan.get("open_tasks", [])[:5],
            "run_registry": workspace.run_registry.get("runs", [])[:10],
            "scheduler_summary": scheduler.get("summary", {}),
            "dispatchable": scheduler.get("dispatchable", [])[:5],
            "waiting": scheduler.get("waiting", [])[:5],
            "pending_gates": [gate for gate in workspace.stage_state.get("gates", []) if gate.get("status") in {"requested", "pending"}],
        }

    def _tool_loop_definitions(self) -> list[dict[str, Any]]:
        submit_schema = self.schema["properties"]
        required = self.schema["required"]
        return [
            {
                "type": "function",
                "name": "get_workspace_summary",
                "description": "Return a compact workspace summary and metrics.",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "get_plan",
                "description": "Return the latest planner output, including blocking items and handoff reason.",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "get_open_tasks",
                "description": "Return the current top open tasks from task_graph.",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "type": "function",
                "name": "get_registry",
                "description": "Return one registry or state by key.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["state_key"],
                    "properties": {"state_key": {"type": "string"}},
                },
            },
            {
                "type": "function",
                "name": "get_run",
                "description": "Return one run manifest, request, metrics, output_manifest, and evaluations.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["run_id"],
                    "properties": {"run_id": {"type": "string"}},
                },
            },
            {
                "type": "function",
                "name": "get_scheduler_snapshot",
                "description": "Return the scheduler snapshot, including dispatchable, waiting, and selector group state.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "worker_labels": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                },
            },
            {
                "type": "function",
                "name": "get_recent_events",
                "description": "Return the latest event log entries.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                },
            },
            {
                "type": "function",
                "name": "get_recent_traces",
                "description": "Return the latest orchestration traces.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                },
            },
            {
                "type": "function",
                "name": "get_note",
                "description": "Read one note file by relative path.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
            },
            {
                "type": "function",
                "name": "submit_action_plan",
                "description": "Submit the final action plan. Call this when you have enough information to act.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": required,
                    "properties": submit_schema,
                },
            },
        ]

    def _execute_read_tool(self, workspace: WorkspaceSnapshot, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from .common import load_jsonl  # local import to avoid widening module surface

        if name == "get_workspace_summary":
            return self._workspace_summary(workspace)
        if name == "get_plan":
            return build_plan(workspace, persist=False)
        if name == "get_open_tasks":
            return {"open_tasks": build_plan(workspace, persist=False).get("open_tasks", [])}
        if name == "get_registry":
            state_key = arguments["state_key"]
            if state_key not in workspace.states:
                return {"error": f"unknown state_key: {state_key}"}
            return {"state_key": state_key, "payload": workspace.states[state_key]}
        if name == "get_run":
            run_id = arguments["run_id"]
            return {
                "run_id": run_id,
                "run_registry_entry": workspace.get_run(run_id),
                "manifest": workspace.load_run_manifest(run_id),
                "request": workspace.load_run_request(run_id),
                "metrics": workspace.load_run_metrics(run_id),
                "output_manifest": workspace.load_run_output_manifest(run_id),
                "evaluations": workspace.evaluations_for_target("run", run_id),
            }
        if name == "get_scheduler_snapshot":
            worker_labels = arguments.get("worker_labels", []) or []
            return build_scheduler_snapshot(workspace, worker_labels=worker_labels)
        if name == "get_recent_events":
            limit = int(arguments.get("limit", 20) or 20)
            return {"events": load_jsonl(workspace.logs_dir / "event_log.jsonl")[-limit:]}
        if name == "get_recent_traces":
            limit = int(arguments.get("limit", 20) or 20)
            return {"traces": load_jsonl(workspace.logs_dir / "trace.jsonl")[-limit:]}
        if name == "get_note":
            path = arguments["path"]
            return {"path": path, "content": workspace.read_note(path)}
        if name == "submit_action_plan":
            return {"accepted": True}
        raise ValueError(f"Unknown read tool: {name}")

    def _create_response(self, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.api_base}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Responses API HTTP {exc.code}: {payload}") from exc

    def _poll_background_response(self, api_key: str, response_id: str, timeout_sec: int = 300) -> dict[str, Any]:
        deadline = time.time() + timeout_sec
        last = {}
        while time.time() < deadline:
            last = self._get_response(api_key, response_id)
            status = last.get("status")
            if status in {"completed", "failed", "incomplete"}:
                return last
            time.sleep(2)
        raise TimeoutError(f"Timed out while waiting for background response {response_id}. Last payload: {last}")

    def _get_response(self, api_key: str, response_id: str) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.api_base}/responses/{response_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Responses API GET HTTP {exc.code}: {payload}") from exc

    def _extract_text(self, response: dict[str, Any]) -> str:
        if response.get("output_text"):
            return response["output_text"]
        texts: list[str] = []
        for item in response.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        texts.append(content["text"])
        if texts:
            return "\n".join(texts)
        raise RuntimeError(f"No text output found in response: {response}")
