#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "quality_gate.py"
SPEC = importlib.util.spec_from_file_location("quality_gate", SCRIPT)
quality_gate = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = quality_gate
SPEC.loader.exec_module(quality_gate)


class QualityGateTests(unittest.TestCase):
    def test_github_pr_diff_range_uses_merge_base_syntax(self) -> None:
        event = {
            "pull_request": {
                "base": {"sha": "base-sha"},
                "head": {"sha": "head-sha"},
            }
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            json.dump(event, handle)
            event_path = handle.name
        previous = os.environ.get("GITHUB_EVENT_PATH")
        os.environ["GITHUB_EVENT_PATH"] = event_path
        try:
            self.assertEqual(quality_gate.github_pr_diff_range(), ["base-sha...head-sha"])
        finally:
            if previous is None:
                os.environ.pop("GITHUB_EVENT_PATH", None)
            else:
                os.environ["GITHUB_EVENT_PATH"] = previous
            Path(event_path).unlink(missing_ok=True)

    def test_expected_verifier_rejection_requires_reference_rehash_pass(self) -> None:
        packet = {
            "status": "rejected",
            "not_deployable": True,
            "rejection_reasons": ["val exposure 52 >= budget 50"],
            "criteria_check": {
                "2_references_rehash": {"pass": False, "note": "stale hash"},
                "6_val_exposure_not_exhausted": {"pass": False, "note": "val exposure"},
            },
        }

        with self.assertRaises(SystemExit) as cm:
            quality_gate.assert_expected_verifier_rejection(packet)

        self.assertIn("reference rehash criterion should pass", str(cm.exception))

    def test_expected_verifier_rejection_rejects_extra_failed_criteria(self) -> None:
        packet = {
            "status": "rejected",
            "not_deployable": True,
            "rejection_reasons": ["val exposure 52 >= budget 50"],
            "criteria_check": {
                "2_references_rehash": {"pass": True, "note": None},
                "6_val_exposure_not_exhausted": {"pass": False, "note": "val exposure"},
                "8_skeptic_verdict_clean": {"pass": False, "note": "unclean"},
            },
        }

        with self.assertRaises(SystemExit) as cm:
            quality_gate.assert_expected_verifier_rejection(packet)

        self.assertIn("unexpected verifier failed criteria", str(cm.exception))

    def test_expected_verifier_rejection_accepts_only_val_exposure_failure(self) -> None:
        packet = {
            "status": "rejected",
            "not_deployable": True,
            "rejection_reasons": ["val exposure 52 >= budget 50"],
            "criteria_check": {
                "2_references_rehash": {"pass": True, "note": None},
                "6_val_exposure_not_exhausted": {"pass": False, "note": "val exposure"},
                "8_skeptic_verdict_clean": {"pass": True, "note": None},
            },
        }

        quality_gate.assert_expected_verifier_rejection(packet)


if __name__ == "__main__":
    unittest.main()
