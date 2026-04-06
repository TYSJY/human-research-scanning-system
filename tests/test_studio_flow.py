from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_os.bootstrap import create_project_from_template
from research_os.studio import (
    apply_prompt_template,
    attempt_comparison,
    complete_step_and_advance,
    complete_attempt_text_output,
    create_attempt,
    find_step,
    mark_attempt_outputs_primary,
    normalize_studio,
    review_attempt,
    select_attempt,
    set_compare_attempt,
)
from research_os.workspace import WorkspaceSnapshot


class StudioV051Tests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_apply_builtin_template_renders_variables(self) -> None:
        step_id = "paper_idea"
        apply_prompt_template(self.workspace.studio, step_id, "builtin:builtin:system:structured")
        step = find_step(self.workspace.studio, step_id)
        self.assertIn("Write a strong model compression paper.", step["prompt"])
        self.assertIn(step["title"], step["prompt"])
        self.assertNotIn("{{project_brief}}", step["prompt"])
        self.assertNotIn("{{step_title}}", step["prompt"])

    def test_attempt_comparison_and_advance(self) -> None:
        step_id = "paper_idea"
        first = create_attempt(self.workspace.studio, step_id)
        complete_attempt_text_output(self.project_dir, self.workspace.studio, first["attempt_id"], "line one\nline two", filename_hint="first.md")
        second = create_attempt(self.workspace.studio, step_id)
        complete_attempt_text_output(self.project_dir, self.workspace.studio, second["attempt_id"], "line one\nbetter line", filename_hint="second.md")

        select_attempt(self.workspace.studio, first["attempt_id"])
        set_compare_attempt(self.workspace.studio, step_id, second["attempt_id"])
        payload = attempt_comparison(self.workspace.studio, self.project_dir, step_id)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn("better line", payload["output_diff"])

        next_step = complete_step_and_advance(self.workspace.studio, step_id)
        self.assertIsNotNone(next_step)
        self.assertEqual(find_step(self.workspace.studio, step_id)["status"], "done")
        assert next_step is not None
        self.assertEqual(self.workspace.studio["active_step_id"], next_step["step_id"])

    def test_promote_attempt_outputs_marks_primary(self) -> None:
        step_id = "paper_idea"
        attempt = create_attempt(self.workspace.studio, step_id)
        asset = complete_attempt_text_output(self.project_dir, self.workspace.studio, attempt["attempt_id"], "primary output", filename_hint="primary.md")
        mark_attempt_outputs_primary(self.workspace.studio, attempt["attempt_id"])
        stored_asset = next(item for item in self.workspace.studio["assets"] if item["asset_id"] == asset["asset_id"])
        self.assertTrue(stored_asset["is_primary"])
        self.assertEqual(find_step(self.workspace.studio, step_id)["selected_attempt_id"], attempt["attempt_id"])

    def test_review_attempt_records_human_feedback(self) -> None:
        step_id = "paper_idea"
        attempt = create_attempt(self.workspace.studio, step_id)
        complete_attempt_text_output(self.project_dir, self.workspace.studio, attempt["attempt_id"], "candidate output", filename_hint="candidate.md")
        reviewed = review_attempt(
            self.workspace.studio,
            attempt["attempt_id"],
            decision="preferred",
            human_review="结构更稳，风险更低。",
            score="88",
            tags="stable,low-risk",
        )
        self.assertEqual(reviewed["review_decision"], "preferred")
        self.assertEqual(reviewed["review_score"], 88)
        self.assertEqual(reviewed["review_tags"], ["stable", "low-risk"])
        self.assertEqual(find_step(self.workspace.studio, step_id)["selected_attempt_id"], attempt["attempt_id"])


if __name__ == "__main__":
    unittest.main()
