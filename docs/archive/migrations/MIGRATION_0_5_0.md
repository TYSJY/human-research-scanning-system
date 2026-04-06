# Migration to 0.5.0

## 目标

把项目从“通用 dashboard / studio + library + control 分页”迁移到“项目内四个独立工作区 + 共享文件库”的结构。

## 主入口变化

旧入口偏向：

- studio
- library
- control
- 大总览 / dashboard

新入口统一为：

- `paper`：A线 · 论文
- `experiments`：B线 · 实验
- `figures`：C线 · 图片
- `control`：D线 · 总控 / 设置

新建项目后默认进入 `paper`。

## 状态层迁移

`studio` 状态现在会在加载时自动做规范化：

- 增加 `modules`
- 增加 `active_module_id`
- 增加 `active_step_by_module`
- 统一补齐 `Step / Attempt / Asset / Package / Handoff`
- 把旧 `line_id` 兼容到 `module_id`
- 自动补齐 prompt 模板和 provider profile
- 自动创建共享文件库目录

## 文件结构变化

每个项目现在都会确保存在：

```text
library/
  paper/
  experiments/
  figures/
  shared/
  handoff_packages/
```

A/B/C 模块之间不再需要下载/上传来接力，直接引用 `library/` 里的文件。

## UI 迁移重点

### A/B/C

统一成三栏：

- 左栏：步骤树
- 中栏：当前步骤、prompt、AI 输出、尝试版本
- 右栏：文件引用、文件产出、交接包

### D

改成项目总控页，集中处理：

- 项目总进度
- 文件库管理
- Provider / API 地址管理
- Prompt 模板管理
- 主版本 / 投稿状态 / 风险阻塞项

## 模板文件变化

`templates/project/state/studio.json` 已改为空对象，创建项目时会由最新 `normalize_studio()` 自动灌入 0.5.0 默认结构。

## 建议检查项

迁移已有项目后，建议至少检查：

1. 默认打开页是否是 A线 · 论文
2. A/B/C/D 是否已变成独立切换页面
3. `library/` 目录是否已自动创建
4. 当前步骤里是否能看到 prompt、AI 输出和尝试版本
5. D线里是否能看到共享文件库和 provider/template 管理

