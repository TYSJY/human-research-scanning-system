# Maintainers

面向仓库维护者的说明。

## 先看这些文件

- `open_source_audit.md`：上一轮开源整理与修复摘要
- `public_release_checklist.md`：已经公开后还需要在 GitHub 上手动补齐的设置项
- `release_process.md`：版本号、tag、GitHub Release 的发布流程
- `github_readme_media.md`：README badges、Star History、social preview 的用法

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
4. 发布正式版本时，按 `release_process.md` 打 tag，不要只改 README 文案。
