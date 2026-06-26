#!/usr/bin/env python3
"""test_verifier_shard_load.py — Protocol 0.5 verifier shard-load + golden hash.

Two guarantees, both required by the plan (MUST-FIX 6 + Scenario 2 tripwire):

  1. Hash basis is stable: every ledger-id-based ``content_sha256`` referenced by
     the level3 promotion request equals ``sha256(_canonical_record_bytes(record))``
     of the matching ``state/ledger/<id>.json`` shard — i.e. the four recomputed
     golden hashes in ``iter08-promotion-request.json`` are correct against the
     SHARED canonical serializer.

  2. The verifier reproduces the level3 decision from the SHARD layout: reading
     ``state/ledger/*.json`` (not the old jsonl), ``verify_request.py`` exits 1,
     writes a packet with ``status: rejected``, and the rejection reason mentions
     val exposure (the over-budget counter-example is preserved).

Run:
    python3 -m unittest template.scripts.tests.test_verifier_shard_load -v
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# scripts/ is the parent of tests/; verifier/ is a sibling of tests/.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import _ledger_common  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent.parent
L3 = REPO_ROOT / "examples" / "level3-counter-example"
LEDGER_DIR = L3 / "state" / "ledger"
REQUEST_JSON = L3 / "proposals" / "iter08-promotion-request.json"
# VERIFIER resolution stays script-relative (portable: ships with the scaffold).
VERIFIER = SCRIPTS_DIR / "verifier" / "verify_request.py"

# The examples/ counter-example fixtures live at the upstream repo root and are
# NOT vendored into a host install. Skip the whole module cleanly when absent so
# `unittest discover` over a host's autoresearch/scripts/tests passes instead of
# erroring on missing fixtures.
_L3_REASON = "examples/ fixtures are upstream-only; absent in a host install"


def _shard_hash(ledger_id: str) -> str:
    shard = LEDGER_DIR / f"{ledger_id}.json"
    entry = json.loads(shard.read_text(encoding="utf-8"))
    return hashlib.sha256(_ledger_common._canonical_record_bytes(entry)).hexdigest()


@unittest.skipUnless(L3.exists(), _L3_REASON)
class TestReferencedHashesMatchGolden(unittest.TestCase):
    """Every ledger-id reference hash == recomputed canonical-bytes hash."""

    def setUp(self):
        self.request = json.loads(REQUEST_JSON.read_text(encoding="utf-8"))
        self.refs = self.request["references"]

    def _check(self, ref: dict) -> None:
        ledger_id = ref["ledger_id"]
        claimed = ref["content_sha256"]
        recomputed = _shard_hash(ledger_id)
        self.assertEqual(
            claimed,
            recomputed,
            f"reference {ledger_id}: golden hash {claimed} != recomputed "
            f"{recomputed} (canonical-bytes hash basis drifted)",
        )

    def test_baseline_run_hash(self):
        self._check(self.refs["baseline_run"])

    def test_baseline_rerun_hash(self):
        self._check(self.refs["baseline_rerun"])

    def test_candidate_runs_hashes(self):
        for ref in self.refs["candidate_runs"]:
            self._check(ref)

    def test_ablation_runs_hashes(self):
        for ref in self.refs["ablation_runs"]:
            self._check(ref)

    def test_skeptic_review_path_hash_matches_migrated_artifact(self):
        # The path-based skeptic_review hash is NOT a ledger record; it must not
        # carry a ledger_id and must match the migrated path-content hash.
        skeptic = self.refs["skeptic_review"]
        self.assertNotIn("ledger_id", skeptic)
        self.assertEqual(
            skeptic["content_sha256"],
            "1cf55f6754cc171c139ef50f3dd5a03026a9ab4c65d60524766632651596d0e9",
        )

    def test_protocol_version_stamped_0_5(self):
        self.assertEqual(self.request["protocol_version"], "0.5")


@unittest.skipUnless(L3.exists(), _L3_REASON)
class TestVerifierReproducesLevel3Decision(unittest.TestCase):
    """The verifier reproduces the rejected decision from the shard layout."""

    def test_reject_from_shards(self):
        with tempfile.TemporaryDirectory(prefix="l3-verify-") as out_dir:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER),
                    "--request",
                    str(REQUEST_JSON),
                    "--ledger",
                    str(LEDGER_DIR),
                    "--metrics",
                    str(L3 / "config" / "metrics.yaml"),
                    "--enforcement",
                    str(L3 / "config" / "enforcement.yaml"),
                    "--out-dir",
                    out_dir,
                    "--verifier-identity",
                    "unittest-shard-load",
                    "--unsigned",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                1,
                f"verifier should exit 1 (rejected). stdout={proc.stdout!r} "
                f"stderr={proc.stderr!r}",
            )
            packet_path = Path(out_dir) / "20260518-220000-bbb008-promotion-packet.json"
            self.assertTrue(packet_path.exists(), "packet json not written")
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertEqual(packet["status"], "rejected")
            reasons = " ".join(packet["rejection_reasons"]).lower()
            self.assertIn(
                "val exposure",
                reasons,
                f"rejection reason should mention val exposure: {reasons!r}",
            )
            # The references re-hash rule MUST pass — proving the recomputed
            # golden hashes match the verifier's shared canonical-bytes hashing.
            self.assertTrue(
                packet["criteria_check"]["2_references_rehash"]["pass"],
                "rule_2 references_rehash should PASS with recomputed hashes; "
                f"note={packet['criteria_check']['2_references_rehash']['note']!r}",
            )


@unittest.skipUnless(L3.exists(), _L3_REASON)
class TestExposureAntiSpoof(unittest.TestCase):
    """rule_6 rejects a request that UNDER-reports val exposure vs the ledger.

    An agent could claim a low queries count to slip under the budget. The
    verifier computes the ledger-derived exposure (sum of resolve_val_queries
    over the shards = 52 for level3) and rejects any claim below it.
    """

    def test_understated_exposure_rejected(self):
        request = json.loads(REQUEST_JSON.read_text(encoding="utf-8"))
        # Claim 0 queries while the ledger records 52 — a spoof to dodge budget.
        request["claims"]["val_set_exposure_at_request"][
            "queries_against_val_this_campaign"
        ] = 0
        with tempfile.TemporaryDirectory(prefix="l3-spoof-") as tmp:
            spoof_request = Path(tmp) / "spoof-request.json"
            spoof_request.write_text(json.dumps(request), encoding="utf-8")
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER),
                    "--request",
                    str(spoof_request),
                    "--ledger",
                    str(LEDGER_DIR),
                    "--metrics",
                    str(L3 / "config" / "metrics.yaml"),
                    "--enforcement",
                    str(L3 / "config" / "enforcement.yaml"),
                    "--out-dir",
                    str(out_dir),
                    "--verifier-identity",
                    "unittest-spoof",
                    "--unsigned",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                1,
                f"spoofed request should be rejected. stdout={proc.stdout!r} "
                f"stderr={proc.stderr!r}",
            )
            packets = list(out_dir.glob("*-promotion-packet.json"))
            self.assertTrue(packets, "packet json not written")
            packet = json.loads(packets[0].read_text(encoding="utf-8"))
            self.assertEqual(packet["status"], "rejected")
            rule6 = packet["criteria_check"]["6_val_exposure_not_exhausted"]
            self.assertFalse(rule6["pass"])
            self.assertIn("under-reports", (rule6["note"] or "").lower())


class TestSkepticVerdictParsing(unittest.TestCase):
    """rule_8 verdict extraction is stdlib-only and robust to quoting (no PyYAML).

    The original substring match only caught double-quoted verdicts; a consumer
    writing a valid unquoted YAML scalar (``verdict: no_objection``) would be
    silently rejected. _skeptic_verdict must accept quoted AND unquoted forms.
    """

    @classmethod
    def setUpClass(cls):
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_request", VERIFIER)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["verify_request"] = mod  # dataclasses introspects sys.modules
        spec.loader.exec_module(mod)
        cls.skeptic_verdict = staticmethod(mod._skeptic_verdict)
        cls.valid = mod.VALID_SKEPTIC_VERDICTS

    def _fm(self, line):
        return f"---\n{line}\nreviewer: skeptic\n---\n\nbody text\n"

    def test_double_quoted(self):
        self.assertEqual(
            self.skeptic_verdict(self._fm('verdict: "no_objection"')), "no_objection"
        )

    def test_single_quoted(self):
        self.assertEqual(
            self.skeptic_verdict(self._fm("verdict: 'no_objection'")), "no_objection"
        )

    def test_unquoted_scalar(self):
        # The case AE's test exercises and the old substring match missed.
        self.assertEqual(
            self.skeptic_verdict(self._fm("verdict: no_objection")), "no_objection"
        )

    def test_override_verdict(self):
        v = self.skeptic_verdict(self._fm("verdict: objected_but_overridden_by_human"))
        self.assertIn(v, self.valid)

    def test_missing_verdict_returns_none(self):
        self.assertIsNone(self.skeptic_verdict(self._fm("reviewer: skeptic")))

    def test_no_frontmatter_returns_none(self):
        self.assertIsNone(self.skeptic_verdict("no frontmatter here\n"))


if __name__ == "__main__":
    unittest.main()
