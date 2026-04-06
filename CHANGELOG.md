## 0.6.6

- 把 README 从“准备公开”状态收口到“正式公开”状态：接入真实 CI / stars / release badges 与 live Star History 图
- 新增 `CITATION.cff`，让 GitHub 自动显示 *Cite this repository*
- 新增正式发布链路：`release.yml`、`dependabot.yml`、`CODEOWNERS`、issue template config
- 新增 `docs/maintainers/public_release_checklist.md` 与 `release_process.md`，把仓库设置项和发布流程写清楚
- 安装说明改成面向真实用户的路径：`pip install .` / `pip install git+...`，把 `-e .` 退回贡献者场景

## 0.6.5

- 项目首页继续做减法：保留一个主入口，把路线、最近结果、最近更新退到折叠区
- 工作页继续收成单轨工作页，进一步削减可见按钮和并列入口
- 更明确地强调自动保存、默认页内 AI、采纳后自动带入下一步
- 结果区把“采纳并下一步”前置，“定为主输出”等操作退到次级层
- 右侧抽屉进一步改成“支撑当前一步”的资料与成品区
- Windows 启动脚本支持在没有本地项目时自动创建演示项目并启动 UI
