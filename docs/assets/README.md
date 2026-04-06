# README visual assets

这些图片用于 GitHub 仓库首页、项目介绍页和仓库社交分享图。

## 文件列表

- `hero-banner.png`
- `showcase-view.png`
- `research-flow.png`
- `evidence-traceability.png`
- `github-growth-panel.png`

## 使用建议

- README 主路径优先使用 **真实 badges + 实时 Star History 图**
- 本目录里的图片负责承担产品说明、结构解释和视觉识别
- `.github/assets/social-preview.png` 用于 GitHub repository social preview

## 生成方式

```bash
python scripts/generate_readme_assets.py
```

脚本会同时更新：

- `docs/assets/`
- `.github/assets/social-preview.png`
