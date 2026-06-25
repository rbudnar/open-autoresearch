#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "weekly_quality_report.py"
SPEC = importlib.util.spec_from_file_location("weekly_quality_report", SCRIPT)
weekly_quality_report = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = weekly_quality_report
SPEC.loader.exec_module(weekly_quality_report)


class WeeklyQualityReportTests(unittest.TestCase):
    def test_clean_checks_report_no_problems(self) -> None:
        report = weekly_quality_report.build_report(
            [
                {
                    "id": "quality-gate",
                    "name": "Quality gate",
                    "command": "python scripts/quality_gate.py",
                    "exitCode": 0,
                    "durationMs": 10,
                    "passed": True,
                    "stdoutTail": "ok",
                    "stderrTail": "",
                }
            ],
            "2026-06-25",
            repository="rbudnar/open-autoresearch",
            run_url="https://github.com/rbudnar/open-autoresearch/actions/runs/1",
            commit="abc123",
        )

        self.assertFalse(report["summary"]["hasProblems"])
        self.assertIn("Status: No problems detected", weekly_quality_report.render_markdown(report))

    def test_failed_check_is_reported_without_throwing(self) -> None:
        report = weekly_quality_report.build_report(
            [
                {
                    "id": "full-scaffold-tests",
                    "name": "Full scaffold tests",
                    "command": "python -m unittest discover",
                    "exitCode": 1,
                    "durationMs": 1200,
                    "passed": False,
                    "stdoutTail": "FAILED",
                    "stderrTail": "",
                }
            ],
            "2026-06-25",
        )

        markdown = weekly_quality_report.render_markdown(report)
        self.assertTrue(report["summary"]["hasProblems"])
        self.assertEqual(report["summary"]["failedCheckCount"], 1)
        self.assertIn("FAILED", markdown)

    def test_default_output_dir_uses_harness_only_in_github_actions(self) -> None:
        self.assertEqual(weekly_quality_report.default_output_dir({"GITHUB_ACTIONS": "true"}), ".harness")
        self.assertTrue(Path(weekly_quality_report.default_output_dir({})).is_absolute())

    def test_write_report_creates_json_and_markdown(self) -> None:
        report = weekly_quality_report.build_report([], "2026-06-25")
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            json_path, md_path = weekly_quality_report.write_report(report, repo, ".harness")
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("Weekly Quality Report", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
