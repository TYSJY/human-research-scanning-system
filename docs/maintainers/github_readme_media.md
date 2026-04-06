# GitHub README media guide

这个仓库已经是公开仓库，所以 README 应该直接接入 **真实仓库信号**，而不是继续停留在“上线前占位”状态。

## 当前仓库

- Repository: `TYSJY/human-research-scanning-system`
- Product name: `Research OS`
- README 主图：`docs/assets/hero-banner.png`
- Social preview：`.github/assets/social-preview.png`

## README 现在应该怎么展示

推荐顺序：

1. Hero banner
2. 一句话定位
3. 实时 badges（CI / stars / release / license）
4. Visual tour
5. Install / Quickstart
6. Live GitHub signals（Star History 图）
7. 样例与文档入口

## 这个仓库可以直接用的 snippet

### CI badge

```md
[![CI](https://github.com/TYSJY/human-research-scanning-system/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/TYSJY/human-research-scanning-system/actions/workflows/ci.yml)
```

### Stars badge

```md
[![GitHub stars](https://img.shields.io/github/stars/TYSJY/human-research-scanning-system?style=for-the-badge&logo=github)](https://github.com/TYSJY/human-research-scanning-system/stargazers)
```

### Release badge

```md
[![GitHub release](https://img.shields.io/github/v/release/TYSJY/human-research-scanning-system?style=for-the-badge)](https://github.com/TYSJY/human-research-scanning-system/releases)
```

### Star History chart

```md
[![Star History Chart](https://api.star-history.com/svg?repos=TYSJY/human-research-scanning-system&type=Date)](https://www.star-history.com/#TYSJY/human-research-scanning-system&Date)
```

## 如果以后 fork 或重命名仓库

只要把上面 snippet 里的 `TYSJY/human-research-scanning-system` 替换成新的 `<OWNER>/<REPO>` 即可。

## Social preview

仓库已经自带一张适合 GitHub 的社交分享图：

- `.github/assets/social-preview.png`

上传方式：GitHub repository → **Settings** → **Social preview** → Upload image。

## 重新生成图片

```bash
python scripts/generate_readme_assets.py
```
