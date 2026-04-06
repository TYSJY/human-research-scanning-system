# Public release checklist

这份清单面向已经公开、准备长期维护的 GitHub 仓库，而不是仅仅“准备公开”的仓库。

## 1. Repository About

当前公开页还显示 **No description, website, or topics provided**，这是正式公开版本最先该补的一块。

建议在 GitHub 仓库主页右上角的 **About** 里设置：

### Description

`Professional AI research assistant for literature review, study design, scholarly writing, and reproducible research operations.`

### Suggested topics

- `research-assistant`
- `ai-research`
- `literature-review`
- `study-design`
- `academic-writing`
- `reproducible-research`
- `local-first`
- `python`

> 可选建议：当前仓库 slug 是 `human-research-scanning-system`，而产品名是 `Research OS`。如果你想减少品牌认知摩擦，可以考虑后续把仓库 slug 调整为更接近产品名的形式。

## 2. Social preview

上传：`.github/assets/social-preview.png`

路径：GitHub → **Settings** → **Social preview** → **Upload image**

## 3. Security & analysis

建议至少打开：

- Dependabot alerts
- Secret scanning
- Push protection
- Code scanning
- Private vulnerability reporting

## 4. Releases

这个仓库现在已经有 `.github/workflows/release.yml`。

发布流程：

```bash
git tag v0.6.6
git push origin v0.6.6
```

推送 tag 后，GitHub Actions 会构建 `sdist` / `wheel` 并附加到 GitHub Release。

## 5. Citation

根目录已经带上 `CITATION.cff`。确认默认分支上存在它以后，GitHub 右侧会出现 **Cite this repository**。

## 6. README checks

确认 README 首页满足：

- 首屏有一句话定位
- 有真实 badges
- 有截图/流程图
- 有最短安装路径
- 有示例成果物入口
- 有 live Star History 图
- 没有“仓库公开后再切”这类内部占位文案
