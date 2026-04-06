# Evidence Traceability

专业科研助手最重要的能力，不是“会生成”，而是“生成后还能解释为什么”。

## Traceability 原则

1. claim 需要 evidence refs
2. result 需要 provenance
3. deliverable 需要来源 run / note / artifact
4. audit 阶段不能凭感觉放行

## 在本仓库里的对应结构

- `state/evidence_registry.json`
- `state/claims.json`
- `state/results_registry.json`
- `state/artifact_registry.json`
- `runs/*/output_manifest.json`
- `reports/runtime_audit_report.md`

## 建议工作方式

- 先补 evidence，再升高 claim 强度
- 只把已经注册到 state 的结果写进摘要与正文
- 在导出对外材料前先跑一次 `ros showcase` 和 `ros audit`
