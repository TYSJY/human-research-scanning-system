# DELIVERY SUMMARY · V5.1

这次不是继续扩“大总控台”，而是在 0.5.0 的论文工作台基础上继续做生产强化。

## 本轮已完成的重点

### 1. 当前步骤 / 尝试版本工作区强化

- 新增尝试版本 **Prompt diff / 输出 diff** 对比区
- 新增尝试版本 **人工审阅结论 / 评分 / 标签 / 备注**
- 新增 **把本次输出设为主文件**
- 新增 **用此版本回填 Prompt**
- 新增 **通过并进入下一步**

### 2. Prompt 模板强化

- 模板支持变量化渲染，例如：
  - `{{project_brief}}`
  - `{{step_title}}`
  - `{{step_goal}}`
  - `{{input_assets}}`
- 内置模板已升级为变量模板

### 3. D线 / 文件库管理强化

- 新增 **主版本快照**
- 共享文件库支持：
  - 搜索
  - 分区筛选
  - 模块筛选
  - 类型筛选
  - 主版本 / 待整理筛选
  - 文本预览
  - 图片预览
  - 引用关系查看

### 4. 工程稳定性强化

- JSON / 文本状态文件改成 **原子写入**
- 修复了新建项目时 `project.workflow_brief` 与 `studio.brief` 可能不同步的问题
- 增加基础测试

### 5. Windows 体验强化

新增：

- `install_windows.bat`
- `start_windows.bat`
- `start_windows.ps1`

## 已跑的检查

- `python -m py_compile research_os/studio.py research_os/studio_ui.py research_os/webapp.py research_os/common.py`
- `python -m unittest discover -s tests -v`
- `python -m research_os.cli --version`
- UI render smoke test

## 本轮新增文档

- `MIGRATION_0_5_1.md`
- `BREAKING_CHANGES_0_5_1.md`
- `DELIVERY_SUMMARY_V5_1.md`
