# GitHub README media guide

这个仓库现在自带一套可以直接用于 GitHub 首页展示的视觉资产，不需要等 UI 完整重构后再补图。

## 已内置的图片资产

### README 展示图
- `docs/assets/hero-banner.png`
- `docs/assets/showcase-view.png`
- `docs/assets/research-flow.png`
- `docs/assets/evidence-traceability.png`
- `docs/assets/github-growth-panel.png`

### 社交分享图
- `.github/assets/social-preview.png`

## 这些图片分别用来做什么

- `hero-banner.png`：README 首屏主图
- `showcase-view.png`：展示工作区 + 成果物的整体视图
- `research-flow.png`：解释研究流程闭环
- `evidence-traceability.png`：解释“结论如何回到证据”
- `github-growth-panel.png`：在仓库还没上线前，先占住 badge / star trend / social preview 的视觉位置
- `social-preview.png`：推到 GitHub 后可直接在仓库设置中作为 social preview 图使用

## README 中使用本地图

GitHub 支持在 Markdown 中通过相对路径引用仓库内图片，所以推荐直接这样写：

```md
<p align="center">
  <img src="docs/assets/hero-banner.png" alt="Research OS hero banner" width="100%">
</p>
```

## 仓库公开后打开 live badge

把下面的 `<OWNER>/<REPO>` 替换成你真实的 GitHub 仓库名。

### GitHub stars badge

```md
[![GitHub stars](https://img.shields.io/github/stars/<OWNER>/<REPO>?style=for-the-badge&logo=github)](https://github.com/<OWNER>/<REPO>/stargazers)
```

### GitHub release badge

```md
[![GitHub release](https://img.shields.io/github/v/release/<OWNER>/<REPO>?style=for-the-badge)](https://github.com/<OWNER>/<REPO>/releases)
```

### Live star history chart

```md
[![Star History Chart](https://api.star-history.com/svg?repos=<OWNER>/<REPO>&type=Date)](https://www.star-history.com/#<OWNER>/<REPO>&Date)
```

## 推荐的主页结构

1. Hero banner
2. 一句话定位
3. Visual tour
4. 核心能力
5. Quickstart
6. 官方样例与成果物示例
7. 开发/测试/贡献

## 重新生成图片

如果你修改了 README 展示内容或者想换一套视觉样式，可以执行：

```bash
python scripts/generate_readme_assets.py
```
