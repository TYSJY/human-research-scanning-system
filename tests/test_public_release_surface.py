from __future__ import annotations

import tomllib
import unittest

from research_os.common import repo_root


REPO_SLUG = "TYSJY/human-research-scanning-system"
REPO_URL = f"https://github.com/{REPO_SLUG}"


class PublicReleaseSurfaceTests(unittest.TestCase):
    def test_citation_file_exists(self) -> None:
        citation = repo_root() / "CITATION.cff"
        self.assertTrue(citation.exists())
        text = citation.read_text(encoding="utf-8")
        self.assertIn('title: "Research OS"', text)
        self.assertIn('version: "0.6.6"', text)
        self.assertIn(REPO_URL, text)

    def test_readme_uses_live_repo_signals(self) -> None:
        readme = (repo_root() / "README.md").read_text(encoding="utf-8")
        required = [
            f"https://github.com/{REPO_SLUG}/actions/workflows/ci.yml/badge.svg?branch=main",
            f"https://img.shields.io/github/stars/{REPO_SLUG}",
            f"https://img.shields.io/github/v/release/{REPO_SLUG}",
            f"https://api.star-history.com/svg?repos={REPO_SLUG}&type=Date",
            "python -m pip install .",
            f'python -m pip install "git+{REPO_URL}.git"',
            "docs/maintainers/public_release_checklist.md",
        ]
        for snippet in required:
            self.assertIn(snippet, readme)
        self.assertNotIn("仓库公开后再切", readme)
        self.assertNotIn("replace <OWNER>/<REPO>", readme)

    def test_release_and_maintenance_files_exist(self) -> None:
        base = repo_root()
        required = [
            base / ".github" / "workflows" / "release.yml",
            base / ".github" / "dependabot.yml",
            base / ".github" / "ISSUE_TEMPLATE" / "config.yml",
            base / "CODEOWNERS",
            base / "docs" / "maintainers" / "public_release_checklist.md",
            base / "docs" / "maintainers" / "release_process.md",
        ]
        for path in required:
            self.assertTrue(path.exists(), f"missing required public-release surface file: {path}")

    def test_pyproject_has_public_urls(self) -> None:
        data = tomllib.loads((repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]
        self.assertEqual(project["version"], "0.6.6")
        urls = project["urls"]
        self.assertEqual(urls["Homepage"], REPO_URL)
        self.assertEqual(urls["Repository"], REPO_URL)
        self.assertEqual(urls["Issues"], f"{REPO_URL}/issues")


if __name__ == "__main__":
    unittest.main()
