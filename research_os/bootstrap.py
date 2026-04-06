from __future__ import annotations

import os
import shutil
from pathlib import Path

from .common import now_iso, resource_path, slugify, write_text
from .sqlite_sync import sync_project_sqlite
from .workspace import CURRENT_VERSION, WorkspaceSnapshot
from .studio import normalize_studio



def template_project_dir() -> Path:
    return resource_path("templates", "project")



def bundled_demo_project_dir() -> Path:
    return resource_path("projects", "sample_joint_tri_runtime_v4_2")



def _detect_owner(default: str = "you") -> str:
    for key in ["RESEARCH_OS_OWNER", "USER", "USERNAME"]:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return default



def _write_start_here(target: Path, title: str, *, mode: str) -> None:
    project_path = str(target)
    body = f"""# Start Here

这是 **{title}** 的工作区。

## 这版的主入口

这次主界面不再是通用 dashboard，而是一个项目里的四个独立工作区：

- A线 · 论文：默认入口，从 idea 开始推进
- B线 · 实验：只做实验工作流
- C线 · 图片：只做图片工作流
- D线 · 总控 / 设置：只做项目总控、文件库、provider 与模板管理

每个生产模块内部都统一成三栏：

- 左栏：当前模块的步骤树
- 中栏：当前步骤、prompt、AI 输出与尝试版本
- 右栏：文件引用、文件产出、交接包

V5.1 额外强化了：

- 尝试版本对比（Prompt diff / 输出 diff）
- 人工审阅结论 / 评分 / 标签
- 一键通过并进入下一步
- D线主版本快照与更强的文件库筛选

## 最短使用路径

1. 打开浏览器
   ```bash
   ros ui "{project_path}"
   ```
   Windows 也可以直接双击：`start_windows.bat`
2. 默认会进入 **A线 · 论文**
3. 在左侧步骤树里选中当前步骤
4. 先改 prompt / 目标 / 输出要求，再运行
5. 如果需要把文件交给另一个 AI，就生成交接包
6. 外部 AI 回来后的结果，重新上传到当前步骤输出箱

## 目录结构

- `paper/`：论文工作目录
- `experiments/`：实验工作目录
- `figures/`：图片工作目录
- `control/`：当前步骤上下文与总控辅助文件
- `library/`：项目级共享文件库
  - `library/paper/`
  - `library/experiments/`
  - `library/figures/`
  - `library/shared/`
  - `library/handoff_packages/`

## 提醒

模块之间不再靠“下载再上传”来衔接，而是都引用 `library/` 里的共享文件。

这套系统支持两种工作方式：

- 平台内直接运行（mock / API）
- 先导出交接包，再去网页 AI 手工上传与回收结果
"""
    write_text(target / "START_HERE.md", body)


def create_project_from_template(root: str | Path, name: str, title: str, owner: str = "replace-me", venue: str = "replace-me", brief: str | None = None) -> Path:
    target = Path(root).resolve() / name
    if target.exists():
        raise FileExistsError(f"Target already exists: {target}")
    shutil.copytree(template_project_dir(), target)
    workspace = WorkspaceSnapshot.load(target)
    workspace.project.update(
        {
            "project_slug": name,
            "title": title,
            "owner": owner or _detect_owner(),
            "target_venue": venue,
            "version": CURRENT_VERSION,
            "current_goal": brief or "围绕一篇论文完成论文、实验、图片与投稿总控四条线。",
            "workflow_brief": brief or "围绕一篇论文完成论文、实验、图片与投稿总控四条线。",
        }
    )
    workspace.studio["brief"] = workspace.project["workflow_brief"]
    workspace.studio.setdefault("control", {})["program_goal"] = workspace.project["workflow_brief"]
    normalize_studio(workspace.studio, workspace.project)
    workspace.runtime["last_run_at"] = now_iso()
    workspace.save_all()
    _write_start_here(target, title, mode="blank")
    sync_project_sqlite(target)
    return target



def copy_demo_project(
    root: str | Path,
    name: str,
    *,
    title: str | None = None,
    owner: str | None = None,
    venue: str | None = None,
    brief: str | None = None,
) -> Path:
    source = bundled_demo_project_dir()
    if not source.exists():
        raise FileNotFoundError(f"Bundled demo project not found: {source}")
    target = Path(root).resolve() / name
    if target.exists():
        raise FileExistsError(f"Target already exists: {target}")

    shutil.copytree(source, target)
    workspace = WorkspaceSnapshot.load(target)
    workspace.project["project_slug"] = slugify(name)
    workspace.project["title"] = title or workspace.project.get("title") or name
    workspace.project["owner"] = owner or workspace.project.get("owner") or _detect_owner()
    if venue is not None:
        workspace.project["target_venue"] = venue
    workspace.project["version"] = CURRENT_VERSION
    workspace.project["current_goal"] = brief or "先通过演示项目理解步骤树、AI 工作区与文件接力如何协作，再迁移到真实项目。"
    workspace.project["workflow_brief"] = workspace.project["current_goal"]
    workspace.studio["brief"] = workspace.project["workflow_brief"]
    workspace.studio.setdefault("control", {})["program_goal"] = workspace.project["workflow_brief"]
    normalize_studio(workspace.studio, workspace.project)
    workspace.runtime["last_run_at"] = now_iso()
    workspace.save_all()
    _write_start_here(target, workspace.project["title"], mode="demo")
    sync_project_sqlite(target)
    return target
