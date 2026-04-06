# Maintainers

面向仓库维护者的说明。

## 维护约定

1. 修改 `configs/`、`control_plane/`、`templates/` 或官方 demo 后，运行：
   ```bash
   python scripts/sync_bundled_resources.py
   python scripts/sync_bundled_resources.py --check
   ```
2. 提交前至少运行：
   ```bash
   pytest -q
   python -m compileall research_os tests
   ```
3. 让仓库根目录保持克制；阶段性交付文档与历史预览放进 `docs/archive/`。
