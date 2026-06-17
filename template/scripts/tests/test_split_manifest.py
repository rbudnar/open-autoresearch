#!/usr/bin/env python3
"""test_split_manifest.py — §6.3.1 two-mode split manifest + rule 11 identity.

Two surfaces, both required by the declarative-splits change
(docs/adr/0002-declarative-data-splits.md):

  1. ``bootstrap_verify.check_manifest`` accepts EITHER §6.3.1 mode (frozen or
     declarative) and FAILS CLOSED on a partial/mixed manifest. Mirrors the
     anyOf of ``schema/split_manifest.schema.json``.

  2. The §10.5 verifier's non-failing rule ``11_comparison_set_identity`` sets
     ``cross_dataset`` on the packet by comparing the baseline and candidate
     ``data_fingerprint`` split identities — WARN, not gate. Matching identities
     => ``cross_dataset: false``; divergent (or unrecorded) => ``true``, and the
     request is NOT rejected for it.

bootstrap_verify imports PyYAML, so this module is run in the PyYAML-installed
step (mirroring test_verifier_shard_load), not the stdlib-only step.

Run:
    python3 -m unittest template.scripts.tests.test_split_manifest -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR / "verifier"))

import bootstrap_verify as bv  # noqa: E402
import regenerate_state as rs  # noqa: E402
import verify_request as vr  # noqa: E402
from _ledger_common import load_schema, validate_against_schema  # noqa: E402

REPO_ROOT = SCRIPTS_DIR.parent.parent
SPLIT_SCHEMA = REPO_ROOT / "template" / "schema" / "split_manifest.schema.json"
VERIFIER = SCRIPTS_DIR / "verifier" / "verify_request.py"
RECORD_SCHEMA = REPO_ROOT / "template" / "schema" / "experiment_record.schema.json"


# A COMPLETE Guard-B dataset fingerprint (all of source/version/date_window/
# row_count/schema_hash). The lighter split identity is only comparable when the
# whole tuple is present — a partial one (e.g. {"version": "v1"}) must NOT clear
# the cross_dataset warning.
_COMPLETE_DATASET_FP = {
    "source": "gold.activities",
    "version": "v1",
    "date_window": "2026-01-01..2026-06-16",
    "row_count": 1000,
    "schema_hash": "sh",
}


def _frozen_manifest() -> dict:
    return {
        "protocol_version": "0.5",
        "mode": "frozen",
        "snapshot_id": "snap-2026-06-16",
        "val_set_version": 1,
        "train": {
            "path": "data/splits/train.parquet",
            "sha256": "a" * 64,
            "size_bytes": 100,
        },
        "val": {
            "path": "data/splits/val.parquet",
            "sha256": "b" * 64,
            "size_bytes": 50,
        },
        "test": {
            "path": "data/splits/test.parquet",
            "sha256": "c" * 64,
            "size_bytes": 50,
        },
        "frozen_at": "2026-06-16T00:00:00Z",
        "frozen_by": "ci-job-42",
    }


def _declarative_manifest() -> dict:
    return {
        "protocol_version": "0.5",
        "mode": "declarative",
        "val_set_version": 1,
        "split_rule": {
            "split_key": "member_id",
            "ratio": {"train": 0.8, "val": 0.1, "test": 0.1},
            "temporal_oos_window": {"start": "2026-05-01", "end": "2026-06-01"},
        },
        "seed": 42,
        "dataset_fingerprint": {
            "source": "gold.activities",
            "version": "v2026-06-16",
            "date_window": "2025-01-01..2026-06-16",
            "row_count": 1234567,
            "schema_hash": "d" * 64,
        },
    }


def _run_check_manifest(manifest: dict) -> list[tuple[bool, str]]:
    with tempfile.TemporaryDirectory(prefix="split-manifest-") as d:
        root = Path(d)
        splits = root / "data" / "splits"
        splits.mkdir(parents=True)
        (splits / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        return bv.check_manifest(root)


def _ok(results: list[tuple[bool, str]]) -> bool:
    return all(passed for passed, _ in results)


# --- bootstrap_verify.check_manifest (the anyOf) -----------------------------


class TestCheckManifestModes(unittest.TestCase):
    def test_frozen_valid_passes(self):
        results = _run_check_manifest(_frozen_manifest())
        self.assertTrue(_ok(results), [line for ok, line in results if not ok])

    def test_declarative_valid_passes(self):
        results = _run_check_manifest(_declarative_manifest())
        self.assertTrue(_ok(results), [line for ok, line in results if not ok])

    def test_missing_mode_fails_closed(self):
        m = _frozen_manifest()
        del m["mode"]
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(any("mode" in line for ok, line in results if not ok))

    def test_unknown_mode_fails_closed(self):
        m = _frozen_manifest()
        m["mode"] = "hybrid"
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))

    def test_partial_mixed_fails_closed(self):
        # Declares frozen but is missing the split blocks AND carries declarative
        # keys — must not pass one half of a mode.
        mixed = {
            "protocol_version": "0.5",
            "mode": "frozen",
            "snapshot_id": "snap",
            "val_set_version": 1,
            "split_rule": {"split_key": "member_id"},
            "seed": 42,
            "frozen_at": "2026-06-16T00:00:00Z",
            "frozen_by": "ci",
        }
        results = _run_check_manifest(mixed)
        self.assertFalse(_ok(results))

    def test_frozen_superset_with_declarative_keys_fails_closed(self):
        # A COMPLETE, valid frozen manifest that ALSO carries declarative-mode
        # keys must fail closed (mixed manifest), not pass on the frozen half.
        m = _frozen_manifest()
        m["split_rule"] = {"split_key": "member_id"}
        m["seed"] = 7
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(
            any("foreign-mode keys" in line for ok, line in results if not ok),
            [line for ok, line in results if not ok],
        )

    def test_missing_protocol_version_fails_closed(self):
        m = _frozen_manifest()
        del m["protocol_version"]
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(
            any("protocol_version" in line for ok, line in results if not ok)
        )

    def test_wrong_protocol_version_fails_closed(self):
        m = _declarative_manifest()
        m["protocol_version"] = "0.4"
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(
            any("protocol_version" in line for ok, line in results if not ok)
        )

    def test_declarative_seed_zero_passes(self):
        # seed: 0 is a legitimate seed; _is_populated(0) is True. Lock it so a
        # future "truthy" refactor can't silently reject a zero seed.
        m = _declarative_manifest()
        m["seed"] = 0
        results = _run_check_manifest(m)
        self.assertTrue(_ok(results), [line for ok, line in results if not ok])

    def test_frozen_wrong_type_path_fails_via_schema(self):
        # `_is_populated` accepts a numeric path/sha256; the schema requires a
        # string. The schema backstop must catch the type error.
        m = _frozen_manifest()
        m["train"]["path"] = 123
        m["train"]["sha256"] = 456
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(
            any("schema" in line for ok, line in results if not ok),
            [line for ok, line in results if not ok],
        )

    def test_declarative_wrong_type_seed_fails_via_schema(self):
        # seed must be an integer; a string seed passes _is_populated but the
        # schema rejects it.
        m = _declarative_manifest()
        m["seed"] = "not-an-int"
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(any("schema" in line for ok, line in results if not ok))

    def test_declarative_wrong_type_val_set_version_fails_via_schema(self):
        # val_set_version must be int or string; an object is rejected by schema.
        m = _declarative_manifest()
        m["val_set_version"] = {"oops": True}
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(any("schema" in line for ok, line in results if not ok))

    def test_frozen_missing_split_fails(self):
        m = _frozen_manifest()
        del m["test"]
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))

    def test_frozen_zero_size_fails(self):
        m = _frozen_manifest()
        m["val"]["size_bytes"] = 0
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))

    def test_declarative_missing_fingerprint_key_fails(self):
        m = _declarative_manifest()
        del m["dataset_fingerprint"]["schema_hash"]
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))

    def test_declarative_missing_split_key_fails(self):
        m = _declarative_manifest()
        del m["split_rule"]["split_key"]
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))

    def test_missing_manifest_file_fails(self):
        with tempfile.TemporaryDirectory(prefix="no-manifest-") as d:
            results = bv.check_manifest(Path(d))
            self.assertFalse(_ok(results))


# --- split_manifest.schema.json (stdlib anyOf validator) ---------------------


class TestSplitManifestSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema(SPLIT_SCHEMA)

    def test_frozen_validates(self):
        self.assertEqual(validate_against_schema(_frozen_manifest(), self.schema), [])

    def test_declarative_validates(self):
        self.assertEqual(
            validate_against_schema(_declarative_manifest(), self.schema), []
        )

    def test_mixed_fails_both_branches(self):
        mixed = {
            "protocol_version": "0.5",
            "mode": "frozen",
            "val_set_version": 1,
            "split_rule": {"split_key": "m"},
            "seed": 1,
        }
        errors = validate_against_schema(mixed, self.schema)
        self.assertTrue(any("allowed schemas" in e for e in errors), errors)

    def test_frozen_superset_with_declarative_keys_fails_both_branches(self):
        # A COMPLETE frozen manifest carrying declarative keys must fail closed:
        # additionalProperties:false rejects the foreign keys on the frozen
        # branch, and the declarative branch rejects the frozen-only shape.
        m = _frozen_manifest()
        m["split_rule"] = {"split_key": "member_id"}
        m["seed"] = 7
        errors = validate_against_schema(m, self.schema)
        self.assertTrue(any("allowed schemas" in e for e in errors), errors)

    def test_frozen_empty_split_blocks_fail(self):
        # Regression for the silently-skipped $ref: empty train/val/test blocks
        # must NOT validate (they did when the split shapes were behind $ref the
        # stdlib validator ignores).
        m = _frozen_manifest()
        m["train"] = {}
        m["val"] = {}
        m["test"] = {}
        errors = validate_against_schema(m, self.schema)
        self.assertTrue(any("allowed schemas" in e for e in errors), errors)


# --- verifier rule 11: comparison-set identity (warn, not gate) --------------


def _ledger_record(rid: str, data_fingerprint: "dict | None") -> dict:
    rec = {
        "protocol_version": "0.5",
        "id": rid,
        "timestamp": "2026-06-16T10:00:00Z",
        "branch": "loss_objective",
        "hypothesis": "h",
        "parent_ids": ["baseline"],
        "source_commit": "abc",
        "source_branch": "main",
        "resolvable_from_main": False,
        "status": "ok",
        "metrics": {"val_nll": 0.8},
    }
    if data_fingerprint is not None:
        rec["data_fingerprint"] = data_fingerprint
    return rec


class TestComparisonSetIdentity(unittest.TestCase):
    """rule 11 is WARN-not-gate: it sets cross_dataset on the packet but never
    rejects the request for a split mismatch."""

    def _run(self, baseline_fp, candidate_fp):
        """Build a minimal ledger + request, run the verifier --unsigned, and
        return (packet_dict, rule11_result, returncode)."""
        with tempfile.TemporaryDirectory(prefix="rule11-") as d:
            root = Path(d)
            ledger = root / "ledger"
            ledger.mkdir()
            baseline_id = "20260616-090000-aaa001"
            candidate_id = "20260616-100000-bbb002"
            (ledger / f"{baseline_id}.json").write_text(
                json.dumps(_ledger_record(baseline_id, baseline_fp)), encoding="utf-8"
            )
            (ledger / f"{candidate_id}.json").write_text(
                json.dumps(_ledger_record(candidate_id, candidate_fp)), encoding="utf-8"
            )
            request = {
                "protocol_version": "0.5",
                "request_id": "req-rule11",
                "references": {
                    "baseline_run": {"ledger_id": baseline_id, "content_sha256": "x"},
                    "candidate_runs": [
                        {"ledger_id": candidate_id, "content_sha256": "y"}
                    ],
                },
            }
            req_path = root / "request.json"
            req_path.write_text(json.dumps(request), encoding="utf-8")
            # Minimal config files the verifier loads.
            (root / "metrics.yaml").write_text(
                "protocol_version: '0.5'\n", encoding="utf-8"
            )
            (root / "enforcement.yaml").write_text(
                "protocol_version: '0.5'\nmechanism: none\n", encoding="utf-8"
            )
            out_dir = root / "out"
            out_dir.mkdir()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER),
                    "--request",
                    str(req_path),
                    "--ledger",
                    str(ledger),
                    "--metrics",
                    str(root / "metrics.yaml"),
                    "--enforcement",
                    str(root / "enforcement.yaml"),
                    "--out-dir",
                    str(out_dir),
                    "--verifier-identity",
                    "unittest-rule11",
                    "--unsigned",
                ],
                capture_output=True,
                text=True,
            )
            packets = list(out_dir.glob("*-promotion-packet.json"))
            self.assertTrue(packets, f"no packet written: {proc.stderr}")
            packet = json.loads(packets[0].read_text(encoding="utf-8"))
            rule11 = packet["criteria_check"]["11_comparison_set_identity"]
            return packet, rule11, proc.returncode

    def test_matching_membership_hash_not_cross_dataset(self):
        fp = {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])  # rule 11 never fails
        self.assertFalse(packet["cross_dataset"])

    def test_matching_lighter_fingerprint_not_cross_dataset(self):
        fp = {
            "dataset_fingerprint": dict(_COMPLETE_DATASET_FP),
            "split_spec_hash": "h",
            "seed": 7,
        }
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])
        self.assertFalse(packet["cross_dataset"])

    def test_incomplete_dataset_fingerprint_flags_cross_dataset(self):
        # An empty or partial Guard-B fingerprint (here: only `version`) with a
        # matching split_spec_hash/seed must NOT be treated as a comparable
        # identity — it can't establish the runs used the same dataset.
        for partial in ({}, {"version": "v1"}):
            fp = {
                "dataset_fingerprint": dict(partial),
                "split_spec_hash": "h",
                "seed": 7,
            }
            packet, rule11, _ = self._run(fp, dict(fp))
            self.assertTrue(rule11["pass"])
            self.assertTrue(
                packet["cross_dataset"],
                f"partial dataset_fingerprint {partial!r} must flag cross_dataset",
            )

    def test_divergent_identity_flags_cross_dataset_without_rejecting(self):
        base = {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}
        cand = {"membership_sha256": {"train": "T", "val": "V", "test": "S"}}
        packet, rule11, _ = self._run(base, cand)
        self.assertTrue(rule11["pass"], "rule 11 must not fail the request")
        self.assertTrue(packet["cross_dataset"])
        # The mismatch must NOT appear in rejection_reasons (warn, not gate).
        joined = " ".join(packet["rejection_reasons"]).lower()
        self.assertNotIn("comparison", joined)
        self.assertNotIn("cross_dataset", joined)

    def test_no_identity_recorded_flags_cross_dataset(self):
        packet, rule11, _ = self._run(None, None)
        self.assertTrue(rule11["pass"])
        self.assertTrue(packet["cross_dataset"])

    def test_partial_membership_flags_cross_dataset(self):
        # Only `train` recorded — an incomplete membership hash cannot confirm
        # identical holdout observations, so it must NOT be a comparable identity
        # even when baseline and candidate carry the same partial value.
        fp = {"membership_sha256": {"train": "t"}}
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])
        self.assertTrue(packet["cross_dataset"])

    def test_lone_seed_does_not_assert_same_set(self):
        # A shared `seed` with no dataset_fingerprint/split_spec_hash proves
        # nothing about the data — must flag cross_dataset, not match.
        fp = {"seed": 42}
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])
        self.assertTrue(packet["cross_dataset"])

    def test_val_set_version_int_vs_str_not_cross_dataset(self):
        # Same complete lighter identity, val_set_version logged as int vs str
        # for the same label — must normalize and NOT flag a false mismatch.
        base = {
            "dataset_fingerprint": dict(_COMPLETE_DATASET_FP),
            "split_spec_hash": "h",
            "seed": 7,
            "val_set_version": 1,
        }
        cand = {
            "dataset_fingerprint": dict(_COMPLETE_DATASET_FP),
            "split_spec_hash": "h",
            "seed": 7,
            "val_set_version": "1",
        }
        packet, rule11, _ = self._run(base, cand)
        self.assertTrue(rule11["pass"])
        self.assertFalse(packet["cross_dataset"])

    def test_tier_mismatch_flags_cross_dataset(self):
        # Baseline proves membership (strongest tier), candidate only the lighter
        # fingerprint tuple — different tiers are not comparable → cross_dataset.
        base = {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}
        cand = {
            "dataset_fingerprint": dict(_COMPLETE_DATASET_FP),
            "split_spec_hash": "h",
            "seed": 7,
        }
        packet, rule11, _ = self._run(base, cand)
        self.assertTrue(rule11["pass"])
        self.assertTrue(packet["cross_dataset"])


class TestRule11WarnNotGate(unittest.TestCase):
    """Prove rule 11 is WARN-not-gate at the STATUS layer: a flagged
    cross_dataset comparison still yields a non-rejected status when no other
    rule fails. The subprocess tests above prove cross_dataset never lands in
    rejection_reasons; these prove the same at compute_status, without needing a
    fully-valid end-to-end promotion request."""

    def _ctx(self, baseline_fp, candidate_fp):
        ledger = {
            "base": {"entry": _ledger_record("base", baseline_fp)},
            "cand": {"entry": _ledger_record("cand", candidate_fp)},
        }
        request = {
            "references": {
                "baseline_run": {"ledger_id": "base"},
                "candidate_runs": [{"ledger_id": "cand"}],
            }
        }
        return vr.VerifierContext(
            request=request,
            request_path=Path("req.json"),
            ledger=ledger,
            metrics={},
            enforcement={},
            unsigned=True,
        )

    def test_divergent_identity_does_not_gate_status(self):
        base = {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}
        cand = {"membership_sha256": {"train": "T", "val": "V", "test": "S"}}
        ctx = self._ctx(base, cand)
        ok, _ = vr.rule_11_comparison_set_identity(ctx)
        self.assertTrue(ok)  # rule 11 never fails the request
        self.assertTrue(ctx.cross_dataset)  # but flags the divergence
        # No rule failures → status is a promotion, not rejected. cross_dataset
        # is surfaced on the packet but never gates status.
        status = vr.compute_status(ctx, rule_failures=[], enforcement_label="full")
        self.assertNotEqual(status, "rejected")

    def test_matching_identity_clears_cross_dataset(self):
        fp = {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}
        ctx = self._ctx(fp, dict(fp))
        ok, _ = vr.rule_11_comparison_set_identity(ctx)
        self.assertTrue(ok)
        self.assertFalse(ctx.cross_dataset)

    def test_empty_candidates_flags_cross_dataset(self):
        fp = {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}
        ctx = self._ctx(fp, fp)
        ctx.request["references"]["candidate_runs"] = []
        ok, _ = vr.rule_11_comparison_set_identity(ctx)
        self.assertTrue(ok)
        self.assertTrue(ctx.cross_dataset)  # fail-safe, not a vacuous match

    def test_unrun_rule_defaults_to_conservative_cross_dataset(self):
        # If rule 11 never runs, the packet must not silently assert comparable.
        ctx = self._ctx(None, None)
        self.assertTrue(ctx.cross_dataset)

    def test_data_fingerprint_records_are_schema_valid(self):
        # The records rule 11 reads must themselves validate against the record
        # schema (the optional data_fingerprint object).
        schema = load_schema(RECORD_SCHEMA)
        rec = _ledger_record(
            "20260616-090000-aaa001",
            {
                "mode": "declarative",
                "dataset_fingerprint": {"source": "s", "version": "v"},
                "split_spec_hash": "h",
                "seed": 7,
                "membership_sha256": {"train": "t", "val": "v", "test": "s"},
            },
        )
        self.assertEqual(validate_against_schema(rec, schema), [])


class TestRegenerateValSetVersion(unittest.TestCase):
    """val_set_version source-of-truth: the split MANIFEST (§6.3.1) wins over
    campaign.json so a holdout refresh that bumps the manifest is reflected in
    derived exposure state; falls back to campaign.json when there is no manifest."""

    def _host(self, d: Path, manifest: "dict | None") -> Path:
        state_dir = d / "state"
        state_dir.mkdir()
        (state_dir / "campaign.json").write_text(
            json.dumps({"val_set_version": 1}), encoding="utf-8"
        )
        if manifest is not None:
            splits = d / "data" / "splits"
            splits.mkdir(parents=True)
            (splits / "MANIFEST.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
        return state_dir

    def test_manifest_value_preferred_over_campaign(self):
        with tempfile.TemporaryDirectory(prefix="regen-vsv-") as d:
            m = _declarative_manifest()
            m["val_set_version"] = 5
            state_dir = self._host(Path(d), m)
            self.assertEqual(rs.read_manifest_val_set_version(state_dir), 5)
            out = rs.build_val_exposure(
                [],
                {"val_set_version": 1},
                None,
                rs.read_manifest_val_set_version(state_dir),
            )
            self.assertEqual(out["val_set_version"], 5)

    def test_falls_back_to_campaign_without_manifest(self):
        with tempfile.TemporaryDirectory(prefix="regen-vsv-") as d:
            state_dir = self._host(Path(d), None)
            self.assertIsNone(rs.read_manifest_val_set_version(state_dir))
            out = rs.build_val_exposure(
                [],
                {"val_set_version": 1},
                None,
                rs.read_manifest_val_set_version(state_dir),
            )
            self.assertEqual(out["val_set_version"], 1)


if __name__ == "__main__":
    unittest.main()
