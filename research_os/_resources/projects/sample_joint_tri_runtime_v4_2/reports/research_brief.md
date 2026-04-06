# Research Brief

- Generated at: 2026-04-06T06:51:33
- Project: Research OS 官方演示项目：边端 LLM 三元联合压缩
- Stage: audit
- Target venue: ICLR / MLSys
- Owner: sample-owner

## Project goal
通过一个完整示例理解专业科研助手如何围绕 evidence、claim、run、result 和 deliverable 推进研究。

## Current research question / MVP
- MVP name: joint-budget-mvp
- Question: 统一预算器是否优于 pipeline-combo baseline？
- Model: Qwen2.5-7B-Instruct
- Dataset: LongBench-mini

## Evidence snapshot
- E1: 近邻工作并未统一建模三种预算 · literature · 作为 claim C1 的背景证据
- E2: pipeline 组合常出现预算错配 · analysis · 说明 unified budget 的动机
- E3: 边端推理的主要瓶颈来自参数、prefill、decode 三端不同步 · system · 说明问题定义

## Claims and traceability
### C1 · 草稿
统一资源预算驱动的联合压缩，比简单分离式组合更稳地降低峰值显存与端到端时延。

- Success metric: 固定精度损失阈值下，峰值显存与端到端时延同时改善
- Evidence refs: E1 (近邻工作并未统一建模三种预算), E2 (pipeline 组合常出现预算错配), E3 (边端推理的主要瓶颈来自参数、prefill、decode 三端不同步)
- Acceptance checks:
  - peak_vram_delta_pct <= -10
  - decode_latency_delta_pct <= -8
  - accuracy_delta_pct >= -1.0
- Registered results:
  - peak_vram_delta_pct: -18.7 (pass)
  - decode_latency_delta_pct: -14.2 (pass)
  - accuracy_delta_pct: -0.6 (pass)

## Deliverables
- configs · ready · Included in sample package.
- scripts · ready · Included in sample package.
- tables · ready · Main table matches results registry.

## Recommended next actions
- no open tasks
