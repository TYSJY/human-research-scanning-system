# Contributing

欢迎把这个项目一起打磨成真正的专业科研助手。

## 建议的贡献方向

- literature review workflows
- evidence traceability UX
- study design guardrails
- scholarly writing quality checks
- reproducibility / audit tooling

## 本地开发

```bash
python -m pip install -e .
pytest -q
```

如果你修改了 `configs/`、`control_plane/`、`templates/` 或官方 demo，请同步资源包：

```bash
python scripts/sync_bundled_resources.py
python scripts/sync_bundled_resources.py --check
```
