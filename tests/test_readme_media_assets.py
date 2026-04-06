from __future__ import annotations

import unittest

from research_os.common import repo_root


class ReadmeMediaAssetsTests(unittest.TestCase):
    def test_readme_media_assets_exist(self) -> None:
        base = repo_root()
        required = [
            base / 'docs' / 'assets' / 'hero-banner.png',
            base / 'docs' / 'assets' / 'showcase-view.png',
            base / 'docs' / 'assets' / 'research-flow.png',
            base / 'docs' / 'assets' / 'evidence-traceability.png',
            base / 'docs' / 'assets' / 'github-growth-panel.png',
            base / '.github' / 'assets' / 'social-preview.png',
            base / 'docs' / 'maintainers' / 'github_readme_media.md',
            base / 'scripts' / 'generate_readme_assets.py',
        ]
        for path in required:
            self.assertTrue(path.exists(), f'missing media asset: {path}')

    def test_readme_references_visual_assets(self) -> None:
        readme = (repo_root() / 'README.md').read_text(encoding='utf-8')
        for rel in [
            'docs/assets/hero-banner.png',
            'docs/assets/showcase-view.png',
            'docs/assets/research-flow.png',
            'docs/assets/evidence-traceability.png',
            'docs/assets/github-growth-panel.png',
            'docs/maintainers/github_readme_media.md',
        ]:
            self.assertIn(rel, readme)


if __name__ == '__main__':
    unittest.main()
