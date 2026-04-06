# PRODUCTIZATION REFACTOR V0.4.8

## 本轮目标

把平台从“流程看板 + 通用控制台”继续重构成：

- 左侧：步骤树
- 中间：AI 工作区
- 右侧：文件接力区

并正式引入跨 AI / 跨会话 / 跨文件类型的核心对象：

- Step
- Attempt
- Asset
- Package
- Handoff

---

## 这轮解决的核心问题

上一轮虽然已经把项目入口收缩成论文 / 实验 / 图片 / 总控四条线，但还存在一个更关键的问题：

- 用户看不到“当前步骤里的 AI 输出”
- 用户不能方便地调 prompt、重跑、固定某版结果
- 用户没法顺畅处理 `.tex -> 下一 AI -> .zip -> 再交给下一 AI` 这种文件接力链
- 平台没有一个正式的“网页 AI 手工交接”模式

所以这轮不再以 dashboard 为主，而是改成以 **步骤工作台** 为主。

---

## 新平台模型

### 1. Step
当前工作单元，包含：
- 标题
- 目标
- prompt
- 输出要求
- provider mode
- provider name / model hint
- 人工备注
- 审阅备注
- 状态

### 2. Attempt
某一步的一次尝试：
- prompt 快照
- 输入文件引用
- 输出文件引用
- provider / model
- 状态
- 摘要

### 3. Asset
一个真实本地文件：
- input / reference / output / final
- line / step / attempt 归属
- 本地路径
- MIME type
- 主版本标记

### 4. Package
一份交接包：
- 选中的文件
- 交接 prompt
- manifest
- zip 导出路径
- 目标 AI / 目标步骤说明

### 5. Handoff
一次真实交接记录：
- 从哪个步骤来
- 给哪个 AI / 哪个目标步骤
- 当前状态
- 回收了哪些结果文件

---

## 主界面重构

### 工作台（默认）
- 左侧：步骤树
- 中间：当前步骤 AI 工作区
- 右侧：输入箱 / 输出箱 / 交接包

### 文件库
- 所有 Asset
- 所有 Package
- 所有 Handoff

### 总控
- 项目总目标
- 下一里程碑
- 投稿状态
- 开源状态
- 风险
- 主稿 / 主结果 / 主图状态
- 审阅收件箱

### 高级视图
保留旧系统里的：
- runs
- outputs
- history
- doctor
- attention

---

## 新增能力

### 步骤级文件箱
每个步骤都有：
- 输入箱
- 输出箱

支持：
- 上传本地文件
- 导入外部 AI 返回文件
- 从项目文件库引用已有文件到当前步骤
- 把输出设为主版本

### 尝试版本
每一步可以保存多次 Attempt：
- 运行 mock
- 运行 OpenAI API（文本文件优先）
- 选择某次 Attempt 为当前主版本

### 交接包
每一步都可导出 Handoff Package：
- `manifest.json`
- `prompt.md`
- `README.md`
- `files/`
- `.zip`

适合：
- 网页 GPT Pro
- 网页 Gemini
- 手工跨会话接力

---

## API 与网页模式如何共存

### 模式 1：平台内 mock
适合：
- 流程测试
- UI 调试
- 结构验证

### 模式 2：OpenAI API（文本文件优先）
适合：
- `.tex`
- `.md`
- `.py`
- `.json`
- 其他可直接读取为文本的文件

### 模式 3：网页 AI 手工交接
适合：
- `.zip`
- 图片批量产出
- 不适合直接 API 上传的大文件 / 二进制文件
- 你手动开的 GPT Pro / Gemini / Nano Banana 会话

这轮明确把“网页 AI 手工交接”做成了正式模式，而不是临时绕路。

---

## Breaking changes

- UI 默认 tab 从旧的总览切到 `studio`
- 项目状态新增 `state/studio.json`
- 项目布局新增 `paper/ / experiments/ / figures/ / control/` 子目录约束
- 普通用户主路径不再以 run / artifact / session 为中心

---

## 下一步最值得继续做的方向

1. Attempt 之间的 prompt diff / 输出 diff
2. 步骤级模板固定（把调好的 prompt 固定下来）
3. 交接包结果自动回收
4. 跨步骤回写关系（例如某实验结果写回论文哪一段 / 哪张表）
5. 真正的多 provider 文件桥接层（provider file refs）
