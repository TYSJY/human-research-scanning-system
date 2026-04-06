# Breaking Changes in 0.5.0

## 1. 项目内主导航改名

旧的主导航语义：

- `studio`
- `library`
- `control`

新的主导航语义：

- `paper`
- `experiments`
- `figures`
- `control`

兼容层仍会把旧 `studio` 映射到 `paper`，把旧 `library` 映射到 `control`，但推荐后续都使用新 tab 名称。

## 2. 不再默认进入总览 / 驾驶舱

项目默认入口已经改成 **A线 · 论文**，而不是总控或 dashboard。

## 3. D线不再是生产步骤页

`control` 不再和 A/B/C 一样扮演“主生产页面”。
它现在主要处理：

- 文件库管理
- Provider / API 设置
- Prompt 模板管理
- 项目级元信息与风险项

## 4. 新建项目的 studio 模板已重置

`templates/project/state/studio.json` 现在是空对象，由运行时自动归一化为最新版结构。
如果你依赖旧模板里预写死的字段，请改为依赖 `normalize_studio()` 的结果。

## 5. Step 结构现在以 module_id 为主

旧状态里可能只有 `line_id`。
0.5.0 会兼容读取，但新版内部逻辑统一使用：

- `module_id`
- `parent_step_id`
- `order_index`
- `references`

## 6. 文件流转已切到共享 library

A/B/C 模块间协作不再以“上传到另一个模块”作为主路径，而是改成：

- 先把文件落到共享 `library/`
- 然后在目标步骤里引用文件

## 7. Prompt 模板系统上线

Prompt 现在不是单纯的 textarea 状态，而有了：

- 系统模板
- 模块模板
- 项目模板
- 全局模板
- 最近使用模板

如果你有外部脚本直接写 prompt，需要注意模板应用后会覆盖当前步骤 prompt。

