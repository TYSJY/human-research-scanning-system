from __future__ import annotations

import unittest

from research_os.common import repo_root


class RepositoryHygieneTests(unittest.TestCase):
    def test_root_has_no_legacy_iteration_files(self) -> None:
        base = repo_root()
        patterns = [
            "BREAKING_CHANGES*.md",
            "DELIVERY_SUMMARY*.md",
            "MIGRATION*.md",
            "PRODUCTIZATION_REFACTOR*.md",
            "ARCHITECTURE_REVIEW_*.md",
            "CHANGE_SUMMARY_*.md",
            "REFACTOR_CHECKLIST_*.md",
            "ROADMAP_*.md",
        ]
        matches: list[str] = []
        for pattern in patterns:
            matches.extend(sorted(path.name for path in base.glob(pattern)))
        self.assertEqual(matches, [], f"Legacy iteration files should live under docs/archive/: {matches}")

    def test_root_has_no_html_preview_files(self) -> None:
        base = repo_root()
        previews = sorted(path.name for path in base.glob("*.html"))
        self.assertEqual(previews, [], f"Root should not contain static preview pages: {previews}")

    def test_repo_contains_examples_and_maintainer_docs(self) -> None:
        base = repo_root()
        self.assertTrue((base / "examples" / "README.md").exists())
        self.assertTrue((base / "docs" / "README.md").exists())
        self.assertTrue((base / "docs" / "maintainers" / "open_source_audit.md").exists())
        self.assertTrue((base / "research_os" / "_resources").exists())

    def test_stale_preview_workspace_and_snapshot_demo_are_removed(self) -> None:
        base = repo_root()
        self.assertFalse((base / "_preview_projects").exists())
        self.assertFalse((base / "projects" / "v58_snapshot_demo").exists())


if __name__ == "__main__":
    unittest.main()
