#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "harness_metrics.py"
SPEC = importlib.util.spec_from_file_location("harness_metrics", SCRIPT)
harness_metrics = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = harness_metrics
SPEC.loader.exec_module(harness_metrics)


class HarnessMetricsTests(unittest.TestCase):
    def test_collect_metrics_has_required_shape(self) -> None:
        metrics = harness_metrics.collect_metrics()
        self.assertEqual(metrics["kind"], "open-autoresearch-harness-metrics")
        values = metrics["metrics"]
        self.assertIn("alwaysOnInstruction", values)
        self.assertIn("requiredFiles", values)
        self.assertIn("brokenInternalLinks", values)

    def test_markdown_scan_includes_linked_worktree_root(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        scanned = {path.relative_to(repo).as_posix() for path in harness_metrics.markdown_files_for_scan(repo)}
        self.assertIn("AGENTS.md", scanned)

    def test_baseline_shape_is_valid(self) -> None:
        failures = harness_metrics.validate_baseline(
            Path(__file__).resolve().parents[2] / "docs" / "harness-metrics-baseline.json"
        )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
