# Research OS 0.6.5 交付说明

这次继续按“**看着更简单，但默认更强**”的方向优化了一版。

## 这版重点做了什么

### 1. 项目首页继续收成“真正的发射台”
- 继续保留一个最强主入口：**继续当前工作**
- 把 **项目路线 / 最近已采纳结果 / 最近更新** 统一退到折叠区
- 首屏更明确强调：
  - 当前里程碑
  - 最近采纳
  - 自动带入下一步
  - 一句话主路径

### 2. 工作页继续收成“单轨工作页”
- 头部不再展开整排路线切换，改成更轻的 **切换路线** 折叠入口
- 中间继续突出：
  - 当前目标
  - 本步交付
  - 主输入
  - 当前产物
- 把默认说明改成更直接的话术：
  - 自动保存
  - 采纳后自动带到下一步

### 3. 把强功能继续后置
- **采纳并下一步** 保持前置
- **定为主输出** 退到 `更多操作`
- **ChatGPT / Gemini** 切换退到 `换一种方式`
- **模板 / provider / 备注** 退到 `更多控制`

### 4. 右侧抽屉继续减负
- `参考资料 / 产物文件` 改成更直接的 **资料 / 成品**
- 文案更强调“只支撑当前一步”，不再像系统后台
- 上传/引用按钮更明确改成：
  - 上传到当前一步
  - 引用到当前一步

### 5. Windows 启动更顺
- 更新了 `start_windows.bat` 和 `start_windows.ps1`
- 如果本地还没有项目，启动脚本会自动创建一个演示项目并直接打开 UI

## 主要修改文件
- `research_os/studio_ui.py`
- `research_os/webapp.py`
- `research_os/ux.py`
- `research_os/workspace.py`
- `research_os/__init__.py`
- `pyproject.toml`
- `README.md`
- `QUICKSTART.md`
- `CHANGELOG.md`
- `start_windows.bat`
- `start_windows.ps1`
- `install_windows.bat`
- `tests/test_ui_v052.py`

## 我实际验证过
- `python scripts/ros.py --version` → `Research OS 0.6.5`
- `python -m compileall -q research_os` → 通过
- `python -m pytest -q` → `14 passed`

## 这版你最该先看什么
1. **项目首页**：首屏是不是终于更像发射台，而不是仪表盘
2. **工作页头部**：路线切换有没有更轻，不再抢主任务
3. **主输入 + 当前产物**：是不是比上一版更像一条主路径
4. **右侧抽屉**：资料 / 成品 的理解成本是否更低
5. **Windows 启动**：空项目时能不能更顺地直接起来
