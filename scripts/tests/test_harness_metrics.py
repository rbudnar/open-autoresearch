#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "harness_metrics.py"
SPEC = importlib.util.spec_from_file_location("harness_metrics", SCRIPT)
harness_metrics = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = harness_metrics
SPEC.loader.exec_module(harness_metrics)

CHECK_SCRIPT = Path(__file__).resolve().parents[1] / "check_repo_harness.py"
CHECK_SPEC = importlib.util.spec_from_file_location("check_repo_harness", CHECK_SCRIPT)
check_repo_harness = importlib.util.module_from_spec(CHECK_SPEC)
assert CHECK_SPEC and CHECK_SPEC.loader
sys.modules[CHECK_SPEC.name] = check_repo_harness
CHECK_SPEC.loader.exec_module(check_repo_harness)


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

    def test_markdown_scan_uses_tracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (repo / "tracked.md").write_text("[ok](tracked.md)\n", encoding="utf-8")
            (repo / "ignored.md").write_text("[bad](missing.md)\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.md"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            scanned = {path.relative_to(repo).as_posix() for path in harness_metrics.markdown_files_for_scan(repo)}

        self.assertEqual(scanned, {"tracked.md"})

    def test_required_files_match_harness_surfaces(self) -> None:
        self.assertEqual(harness_metrics.REQUIRED_FILES, check_repo_harness.REQUIRED_SURFACES)

    def test_all_script_regression_tests_are_required_surfaces(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", "scripts/tests"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        test_files = {
            rel
            for rel in tracked.stdout.split("\0")
            if rel and Path(rel).name.startswith("test_") and Path(rel).suffix == ".py"
        }

        self.assertLessEqual(test_files, set(check_repo_harness.REQUIRED_SURFACES))

    def test_baseline_shape_is_valid(self) -> None:
        failures = harness_metrics.validate_baseline(
            Path(__file__).resolve().parents[2] / "docs" / "harness-metrics-baseline.json"
        )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
