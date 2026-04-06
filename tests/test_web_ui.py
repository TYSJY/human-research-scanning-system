from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_os.bootstrap import create_project_from_template
from research_os.studio import apply_starter_ai_profile, complete_step_and_advance, mark_asset_primary, normalize_studio, register_asset
from research_os.studio_ui import render_control, render_project_home, render_workspace
from research_os.webapp import PAGE_CSS, _render_page
from research_os.workspace import WorkspaceSnapshot


class StudioUIV065Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project_dir = create_project_from_template(
            self.root,
            "demo_project",
            "Demo Project",
            owner="tester",
            venue="arxiv",
            brief="Write a strong model compression paper.",
        )
        self.workspace = WorkspaceSnapshot.load(self.project_dir)
        normalize_studio(self.workspace.studio, self.workspace.project)
        self.state = {
            "project": str(self.project_dir),
            "tab": "paper",
            "mode": "guided",
            "run": None,
            "task": None,
            "artifact": None,
            "session": None,
            "note": None,
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_light_theme_css_contains_goal_launchpad_and_singletrack_classes(self) -> None:
        self.assertIn("--bg: #f6f7fb", PAGE_CSS)
        self.assertIn(".mission-home-shell", PAGE_CSS)
        self.assertIn(".mission-home-rail", PAGE_CSS)
        self.assertIn(".mission-home-board", PAGE_CSS)
        self.assertIn(".mission-spotlight", PAGE_CSS)
        self.assertIn(".mission-work-head", PAGE_CSS)
        self.assertIn(".mission-workspace", PAGE_CSS)
        self.assertIn(".artifact-summary-bar", PAGE_CSS)
        self.assertIn(".mission-artifact-board", PAGE_CSS)
        self.assertIn(".artifact-canvas", PAGE_CSS)
        self.assertIn(".drawer-panel", PAGE_CSS)
        self.assertIn(".autosave-status", PAGE_CSS)
        self.assertIn(".route-list-grid {", PAGE_CSS)
        self.assertIn(".route-row-actions {", PAGE_CSS)

    def test_render_project_home_contains_goal_launchpad_cards(self) -> None:
        html = render_project_home(str(self.project_dir), {**self.state, "tab": "project"})
        self.assertIn("科研助手首页", html)
        self.assertIn("当前最该推进", html)
        self.assertIn("继续当前工作", html)
        self.assertIn("项目路线", html)
        self.assertIn("最近已采纳结果", html)
        self.assertIn("最近更新", html)
        self.assertIn("进入后会先得到什么", html)
        self.assertIn("自动带入下一步", html)
        self.assertIn("mission-home-board", html)
        self.assertIn("route-list-grid", html)
        self.assertNotIn("module-home-grid route-list-grid", html)

    def test_render_workspace_contains_singletrack_work_flow(self) -> None:
        html = render_workspace(str(self.project_dir), self.state, "paper")
        self.assertIn("当前一步", html)
        self.assertIn("项目首页", html)
        self.assertIn("开始生成", html)
        self.assertIn("采纳并下一步", html)
        self.assertIn("资料与产物", html)
        self.assertIn("资料 ·", html)
        self.assertIn("成品 ·", html)
        self.assertIn("drawer-toggle", html)
        self.assertIn("autosave-status", html)
        self.assertIn("当前产物", html)
        self.assertIn("换一种方式", html)
        self.assertIn("切换路线", html)
        self.assertIn("打开 ChatGPT", html)
        self.assertIn("打开 Gemini", html)
        self.assertNotIn("步骤推进", html)
        self.assertNotIn("现在只做这三件事", html)
        self.assertNotIn("第一次用就按这个顺序来", html)
        self.assertNotIn("workspace-hero-panel", html)

    def test_workspace_markup_contains_editorial_surface_elements(self) -> None:
        html = render_workspace(str(self.project_dir), self.state, "paper")
        self.assertIn("主输入", html)
        self.assertIn("mission-work-head", html)
        self.assertIn("参考资料", html)
        self.assertIn("当前产物", html)
        self.assertIn("file-chip-row", html)
        self.assertIn("mission-context-strip", html)
        self.assertIn("artifact-summary-bar", html)
        self.assertIn("artifact-canvas", html)
        self.assertIn("result-summary-card", html)
        self.assertIn("自动带到", html)

    def test_render_control_contains_anchor_navigation_and_ai_summary(self) -> None:
        html = render_control(str(self.project_dir), {**self.state, "tab": "control"})
        self.assertIn("#control-overview", html)
        self.assertIn("#control-library", html)
        self.assertIn("项目目标", html)
        self.assertIn("下一里程碑", html)
        self.assertIn("运行方式", html)
        self.assertIn("AI 接入", html)
        self.assertIn("项目活动流", html)
        self.assertIn("待处理队列", html)

    def test_render_selected_project_defaults_to_project_home(self) -> None:
        html = _render_page(str(self.root), {**self.state, "project": str(self.project_dir), "tab": None})
        self.assertIn("科研助手首页", html)
        self.assertIn("当前最该推进", html)
        self.assertIn("继续当前工作", html)
        self.assertIn("command-toggle", html)
        self.assertIn("focus-toggle", html)
        self.assertIn("pro-toggle", html)

    def test_render_selected_work_page_contains_autosave_form(self) -> None:
        html = _render_page(str(self.root), {**self.state, "project": str(self.project_dir), "tab": "paper"})
        self.assertIn("autosave-form", html)
        self.assertIn("当前一步", html)
        self.assertIn("项目首页", html)

    def test_render_home_page_contains_beginner_start_modes(self) -> None:
        html = _render_page(str(self.root), {**self.state, "project": None, "tab": None})
        self.assertIn("专业科研助手 · 快速开始", html)
        self.assertIn("推荐开始（ChatGPT）", html)
        self.assertIn("用 Gemini 网页", html)
        self.assertIn("已配 API 再选这里", html)
        self.assertIn("先建项目", html)
        self.assertIn("再进入专注工作页", html)
        self.assertIn("Ctrl / Cmd + K", html)
        self.assertIn("命令中心", html)

    def test_apply_starter_ai_profile_updates_step_entry_modes(self) -> None:
        choice = apply_starter_ai_profile(self.workspace.studio, "recommended")
        self.assertEqual(choice, "recommended")
        paper_step = next(item for item in self.workspace.studio["steps"] if item["module_id"] == "paper")
        figure_step = next(item for item in self.workspace.studio["steps"] if item["module_id"] == "figures")
        self.assertEqual(paper_step.get("provider_mode"), "manual_web")
        self.assertEqual(paper_step.get("web_target"), "chatgpt")
        self.assertEqual(figure_step.get("provider_mode"), "manual_web")
        self.assertEqual(figure_step.get("web_target"), "gemini")

    def test_complete_step_and_advance_seeds_next_step_with_previous_output(self) -> None:
        first_step = next(item for item in self.workspace.studio["steps"] if item["module_id"] == "paper")
        second_step = next(item for item in self.workspace.studio["steps"] if item["module_id"] == "paper" and item["step_id"] != first_step["step_id"])
        second_step["prompt"] = ""
        second_step["operator_notes"] = ""
        asset = register_asset(
            self.project_dir,
            self.workspace.studio,
            first_step["step_id"],
            "output",
            "draft.md",
            b"hello world",
            source="unit_test",
        )
        mark_asset_primary(self.workspace.studio, asset["asset_id"])
        nxt = complete_step_and_advance(self.workspace.studio, first_step["step_id"])
        self.assertEqual(nxt["step_id"], second_step["step_id"])
        self.assertIn(first_step["title"], nxt["prompt"])
        self.assertTrue(any(ref.get("asset_id") == asset["asset_id"] for ref in nxt.get("references", [])))


if __name__ == "__main__":
    unittest.main()
