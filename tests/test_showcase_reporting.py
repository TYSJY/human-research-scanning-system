from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_os.bootstrap import copy_demo_project
from research_os.reporting import build_showcase_package


class ShowcaseReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project_dir = copy_demo_project(self.root, "demo")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_showcase_package_exports_expected_files(self) -> None:
        outputs = build_showcase_package(self.project_dir)
        self.assertEqual(set(outputs.keys()), {"research_brief", "evidence_matrix", "deliverable_index"})
        for path in outputs.values():
            self.assertTrue(path.exists())

        brief = outputs["research_brief"].read_text(encoding="utf-8")
        self.assertIn("# Research Brief", brief)
        self.assertIn("## Claims and traceability", brief)
        self.assertIn("Evidence refs", brief)

        evidence_csv = outputs["evidence_matrix"].read_text(encoding="utf-8")
        self.assertIn("evidence_id,title,kind,notes,source_refs", evidence_csv)

        deliverable_index = outputs["deliverable_index"].read_text(encoding="utf-8")
        self.assertIn("# Deliverable Index", deliverable_index)
        self.assertIn("## Runs", deliverable_index)


if __name__ == "__main__":
    unittest.main()
