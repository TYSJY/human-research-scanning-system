# Migration to 0.5.1

0.5.1 不是重新改产品方向，而是在 0.5.0 的模块化工作台上继续做生产强化。

## 这次迁移的核心

如果你已经从旧版迁到 0.5.0，那么 0.5.1 主要增加的是：

- 步骤尝试版本对比（Prompt diff / 输出 diff）
- 尝试版本人工审阅字段（decision / score / tags / human_review）
- 一键把某次尝试输出固定为主文件
- 一键“通过并进入下一步”
- D线主版本快照
- D线文件库筛选 / 预览 / 引用关系查看
- Windows 启动脚本
- 状态文件原子写入

## 状态层新增字段

### Step

新增：

- `compare_attempt_id`

用于在当前步骤里保存“当前最佳版本”要对比的目标尝试。

### Attempt

新增：

- `review_decision`
- `review_score`
- `review_tags`

用于把人工审阅结论直接落在尝试版本对象上。

## 兼容性

这次仍然通过 `normalize_studio()` 自动补齐新增字段。

也就是说：

- 旧的 `studio.json` 不需要手工重写
- 旧项目直接打开时会自动补齐默认值

默认补齐规则：

- `compare_attempt_id = null`
- `review_decision = "candidate"`
- `review_score = null`
- `review_tags = []`

## Windows

新增：

- `install_windows.bat`
- `start_windows.bat`
- `start_windows.ps1`

在 Windows 上不再必须先自己摸清 `ros` 脚本路径，直接调用这些脚本即可。

## 建议升级动作

1. 备份现有项目目录
2. 安装 0.5.1 代码
3. 直接打开已有项目
4. 进入 A/B/C 任一步骤，确认：
   - 历史尝试版本能正常显示
   - 当前最佳版本能正常选择
   - D线文件库能正常列出历史文件

## 不需要手工做的事

这次不需要你手动迁移：

- `library/` 目录结构
- provider profiles
- 旧模板列表
- 旧交接包目录

这些都保持兼容。
