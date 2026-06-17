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
REGEN_SCRIPT = SCRIPTS_DIR / "regenerate_state.py"
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

    def test_declarative_non_numeric_ratio_fails_via_schema(self):
        # split_rule.ratio uses schema-valued additionalProperties ({type:number});
        # a string ratio value must be rejected by the schema backstop.
        m = _declarative_manifest()
        m["split_rule"]["ratio"] = {"train": "not-a-number", "val": 0.1, "test": 0.1}
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(any("schema" in line for ok, line in results if not ok))

    def test_declarative_split_key_only_fails_closed(self):
        # split_key alone cannot materialize train/val/test — require a
        # partition clause (ratio / cutoff / temporal_oos_window).
        m = _declarative_manifest()
        m["split_rule"] = {"split_key": "member_id"}
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(
            any("partition clause" in line for ok, line in results if not ok),
            [line for ok, line in results if not ok],
        )

    def test_declarative_cutoff_only_passes(self):
        # A cutoff (without ratio/temporal) is a valid partition clause.
        m = _declarative_manifest()
        m["split_rule"] = {"split_key": "member_id", "cutoff": "2026-05-01"}
        results = _run_check_manifest(m)
        self.assertTrue(_ok(results), [line for ok, line in results if not ok])

    def test_object_date_window_empty_bounds_fails_via_schema(self):
        # An object date_window with blank start/end carries no auditable window.
        m = _declarative_manifest()
        m["dataset_fingerprint"]["date_window"] = {"start": "", "end": ""}
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(any("schema" in line for ok, line in results if not ok))

    def test_out_of_range_ratio_fails_via_schema(self):
        # ratio values are fractions in [0, 1]; negative / >1 must be rejected.
        for bad_ratio in ({"train": -1, "val": 2}, {"train": 1.5}, {"train": -0.1}):
            with self.subTest(ratio=bad_ratio):
                m = _declarative_manifest()
                m["split_rule"] = {"split_key": "member_id", "ratio": bad_ratio}
                results = _run_check_manifest(m)
                self.assertFalse(_ok(results))
                self.assertTrue(any("schema" in line for ok, line in results if not ok))

    def test_all_zero_ratio_fails_closed(self):
        # ratio values in-range but summing to zero partitions nothing.
        m = _declarative_manifest()
        m["split_rule"] = {
            "split_key": "member_id",
            "ratio": {"train": 0, "val": 0, "test": 0},
        }
        results = _run_check_manifest(m)
        self.assertFalse(_ok(results))
        self.assertTrue(
            any("ratio" in line for ok, line in results if not ok),
            [line for ok, line in results if not ok],
        )

    def test_blank_temporal_window_fails_via_schema(self):
        # temporal_oos_window {start:"", end:""} carries no auditable window.
        for bad in (
            {"start": "", "end": ""},
            {"start": "x"},
            {"start": "  ", "end": "y"},
        ):
            with self.subTest(window=bad):
                m = _declarative_manifest()
                m["split_rule"] = {"split_key": "member_id", "temporal_oos_window": bad}
                results = _run_check_manifest(m)
                self.assertFalse(_ok(results))
                self.assertTrue(any("schema" in line for ok, line in results if not ok))

    def test_temporal_window_only_passes(self):
        # A populated temporal_oos_window alone is a valid partition clause.
        m = _declarative_manifest()
        m["split_rule"] = {
            "split_key": "member_id",
            "temporal_oos_window": {"start": "2026-05-01", "end": "2026-06-01"},
        }
        results = _run_check_manifest(m)
        self.assertTrue(_ok(results), [line for ok, line in results if not ok])

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

    def test_schema_valued_additional_properties_enforced(self):
        # split_rule.ratio is `additionalProperties: {type: number}`; the stdlib
        # validator must validate each ratio value (it previously skipped
        # schema-valued additionalProperties).
        m = _declarative_manifest()
        m["split_rule"]["ratio"] = {"train": "not-a-number", "val": 0.1}
        errors = validate_against_schema(m, self.schema)
        self.assertTrue(errors, "non-numeric ratio value must be rejected")

    def test_split_key_only_rule_rejected(self):
        # split_rule with split_key but no ratio/cutoff/temporal_oos_window must
        # fail the schema (anyOf partition-clause requirement).
        m = _declarative_manifest()
        m["split_rule"] = {"split_key": "member_id"}
        errors = validate_against_schema(m, self.schema)
        self.assertTrue(errors, "split_key-only split_rule must be rejected")

    def test_object_date_window_empty_bounds_rejected(self):
        m = _declarative_manifest()
        m["dataset_fingerprint"]["date_window"] = {"start": "", "end": ""}
        errors = validate_against_schema(m, self.schema)
        self.assertTrue(errors, "blank-bounded object date_window must be rejected")


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

    def test_empty_or_wrong_typed_guard_b_flags_cross_dataset(self):
        # All Guard-B keys PRESENT but empty/wrong-typed (the record schema's free
        # dataset_fingerprint object permits this) must NOT clear cross_dataset —
        # they don't establish which dataset was used.
        fp = {
            "dataset_fingerprint": {
                "source": "",
                "version": "",
                "date_window": "",
                "row_count": "not-int",
                "schema_hash": "",
            },
            "split_spec_hash": "h",
            "seed": 7,
        }
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])
        self.assertTrue(packet["cross_dataset"])

    def test_object_date_window_empty_bounds_flags_cross_dataset(self):
        # date_window {start:"", end:""} is a non-empty dict but carries no
        # auditable window — must not clear cross_dataset.
        fp = {
            "dataset_fingerprint": {
                **_COMPLETE_DATASET_FP,
                "date_window": {"start": "", "end": ""},
            },
            "split_spec_hash": "h",
            "seed": 7,
        }
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])
        self.assertTrue(packet["cross_dataset"])

    def test_object_date_window_populated_not_cross_dataset(self):
        # A {start, end} object with both bounds populated is a valid identity.
        fp = {
            "dataset_fingerprint": {
                **_COMPLETE_DATASET_FP,
                "date_window": {"start": "2026-01-01", "end": "2026-06-16"},
            },
            "split_spec_hash": "h",
            "seed": 7,
        }
        packet, rule11, _ = self._run(fp, dict(fp))
        self.assertTrue(rule11["pass"])
        self.assertFalse(packet["cross_dataset"])

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

    def test_malformed_references_do_not_crash_rule_11(self):
        # A non-dict references / baseline_run / candidate item must yield a clean
        # cross_dataset flag, never an AttributeError traceback.
        for bad_request in [
            {"references": "not-an-object"},
            {
                "references": {
                    "baseline_run": "x",
                    "candidate_runs": [{"ledger_id": "c"}],
                }
            },
            {"references": {"baseline_run": {"ledger_id": "b"}, "candidate_runs": "x"}},
            {
                "references": {
                    "baseline_run": {"ledger_id": "b"},
                    "candidate_runs": ["x"],
                }
            },
            {},
        ]:
            with self.subTest(request=bad_request):
                ctx = vr.VerifierContext(
                    request=bad_request,
                    request_path=Path("req.json"),
                    ledger={},
                    metrics={},
                    enforcement={},
                    unsigned=True,
                )
                ok, _ = vr.rule_11_comparison_set_identity(ctx)
                self.assertTrue(ok)  # rule 11 never fails the request
                self.assertTrue(ctx.cross_dataset)  # cannot confirm → flag

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
        # REAL install layout: state under <host>/autoresearch/state, the split
        # manifest at the host root <host>/data/splits (PROTOCOL §4 + §6.3.1) — not
        # flattened, so the test exercises the host-root resolution.
        state_dir = d / "autoresearch" / "state"
        state_dir.mkdir(parents=True)
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
            m["val_set_version"] = 9
            state_dir = self._host(Path(d), m)
            self.assertEqual(rs.read_manifest_val_set_version(state_dir), 9)
            out = rs.build_val_exposure(
                [],
                {"val_set_version": 1},
                None,
                rs.read_manifest_val_set_version(state_dir),
            )
            self.assertEqual(out["val_set_version"], 9)

    def test_regenerate_writes_manifest_val_set_version(self):
        # End-to-end: a full regenerate() in the real host layout must write the
        # MANIFEST's val_set_version into val_exposure.json, not campaign's stale 1.
        with tempfile.TemporaryDirectory(prefix="regen-vsv-") as d:
            m = _declarative_manifest()
            m["val_set_version"] = 9
            state_dir = self._host(Path(d), m)
            (state_dir / "ledger").mkdir()
            rs.regenerate(state_dir)
            ve = json.loads(
                (state_dir / "val_exposure.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ve["val_set_version"], 9)

    def test_cli_relative_state_dir_resolves_host_manifest(self):
        # The DOCUMENTED invocation: `regenerate_state.py --state-dir state/` run
        # from <host>/autoresearch. The relative path must still resolve up to the
        # host-root manifest, not <host>/autoresearch/data/splits.
        with tempfile.TemporaryDirectory(prefix="regen-cli-") as d:
            m = _declarative_manifest()
            m["val_set_version"] = 9
            state_dir = self._host(Path(d), m)
            (state_dir / "ledger").mkdir()
            proc = subprocess.run(
                [sys.executable, str(REGEN_SCRIPT), "--state-dir", "state/"],
                cwd=str(Path(d) / "autoresearch"),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            ve = json.loads(
                (state_dir / "val_exposure.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ve["val_set_version"], 9)

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


def _full_lighter_fp() -> dict:
    return {
        "dataset_fingerprint": {
            "source": "gold.activities",
            "version": "v1",
            "date_window": "2026-01-01..2026-06-16",
            "row_count": 1000,
            "schema_hash": "sh",
        },
        "split_spec_hash": "spec",
        "seed": 7,
    }


def _full_membership_fp() -> dict:
    return {"membership_sha256": {"train": "t", "val": "v", "test": "s"}}


# Degenerate data_fingerprint values that must NOT yield a comparable identity
# (every one makes _split_identity return None → rule 11 flags cross_dataset).
def _degenerate_fingerprints() -> list:
    cases: list = [
        ("non-dict data_fingerprint", "not-a-dict"),
        ("empty data_fingerprint", {}),
    ]
    # Lighter-tier structural omissions / wrong scalar types.
    for label, mutate in [
        ("missing split_spec_hash", lambda f: f.pop("split_spec_hash")),
        ("missing seed", lambda f: f.pop("seed")),
        ("seed as string", lambda f: f.__setitem__("seed", "7")),
        ("seed as bool", lambda f: f.__setitem__("seed", True)),
        ("seed as float", lambda f: f.__setitem__("seed", 7.0)),
        ("split_spec_hash empty", lambda f: f.__setitem__("split_spec_hash", "")),
        ("split_spec_hash blank", lambda f: f.__setitem__("split_spec_hash", "   ")),
        ("split_spec_hash non-str", lambda f: f.__setitem__("split_spec_hash", 1)),
        (
            "dataset_fingerprint empty",
            lambda f: f.__setitem__("dataset_fingerprint", {}),
        ),
    ]:
        fp = _full_lighter_fp()
        mutate(fp)
        cases.append((label, fp))
    # Per-Guard-B-field degeneracy.
    for key in ("source", "version", "schema_hash"):
        for bad_label, bad in [("empty", ""), ("blank", "  "), ("non-str", 123)]:
            fp = _full_lighter_fp()
            fp["dataset_fingerprint"][key] = bad
            cases.append((f"dataset_fingerprint.{key} {bad_label}", fp))
        fp = _full_lighter_fp()
        del fp["dataset_fingerprint"][key]
        cases.append((f"dataset_fingerprint.{key} missing", fp))
    for bad_label, bad in [
        ("string", "10"),
        ("float", 1.5),
        ("negative", -1),
        ("zero", 0),
        ("bool", True),
        ("missing", None),
    ]:
        fp = _full_lighter_fp()
        if bad is None:
            del fp["dataset_fingerprint"]["row_count"]
        else:
            fp["dataset_fingerprint"]["row_count"] = bad
        cases.append((f"row_count {bad_label}", fp))
    for bad_label, bad in [
        ("empty string", ""),
        ("blank string", "  "),
        ("empty object", {}),
        ("missing end", {"start": "x"}),
        ("blank bounds", {"start": "", "end": ""}),
        ("whitespace bounds", {"start": "  ", "end": "  "}),
        ("non-str scalar", 123),
        ("missing", None),
    ]:
        fp = _full_lighter_fp()
        if bad is None:
            del fp["dataset_fingerprint"]["date_window"]
        else:
            fp["dataset_fingerprint"]["date_window"] = bad
        cases.append((f"date_window {bad_label}", fp))
    # Membership-tier degeneracy (with no lighter tuple, so it can't fall back).
    for bad_label, membership in [
        ("partial (train only)", {"train": "t"}),
        ("one empty", {"train": "t", "val": "v", "test": ""}),
        ("one blank", {"train": "t", "val": "v", "test": "  "}),
        ("non-str values", {"train": 1, "val": 2, "test": 3}),
        ("non-dict", "abc"),
    ]:
        cases.append((f"membership {bad_label}", {"membership_sha256": membership}))
    return cases


class TestSplitIdentityMatrix(unittest.TestCase):
    """Exhaustive degenerate-input matrix for the comparability gate: every field
    x {missing, empty, whitespace, wrong-type, negative, blank-object, partial}
    must yield NO comparable identity (so rule 11 flags cross_dataset), and the
    fully-valid forms must yield one."""

    def test_degenerate_identities_are_incomparable(self):
        for label, fp in _degenerate_fingerprints():
            with self.subTest(case=label):
                self.assertIsNone(
                    vr._split_identity({"data_fingerprint": fp}),
                    f"{label!r} must NOT be a comparable identity",
                )

    def test_valid_identities_are_comparable(self):
        valid = [
            ("full lighter (string date_window)", _full_lighter_fp()),
            (
                "full lighter (object date_window)",
                {
                    **_full_lighter_fp(),
                    "dataset_fingerprint": {
                        **_full_lighter_fp()["dataset_fingerprint"],
                        "date_window": {"start": "2026-01-01", "end": "2026-06-16"},
                    },
                },
            ),
            ("full membership", _full_membership_fp()),
            (
                "lighter + int val_set_version",
                {**_full_lighter_fp(), "val_set_version": 1},
            ),
            (
                "lighter + str val_set_version",
                {**_full_lighter_fp(), "val_set_version": "1"},
            ),
        ]
        for label, fp in valid:
            with self.subTest(case=label):
                self.assertIsNotNone(
                    vr._split_identity({"data_fingerprint": fp}),
                    f"{label!r} must be a comparable identity",
                )

    def test_val_set_version_int_str_canonicalize_equal(self):
        a = vr._split_identity(
            {"data_fingerprint": {**_full_lighter_fp(), "val_set_version": 1}}
        )
        b = vr._split_identity(
            {"data_fingerprint": {**_full_lighter_fp(), "val_set_version": "1"}}
        )
        self.assertEqual(a, b)

    def test_rule11_and_manifest_schema_agree_on_dataset_fingerprint(self):
        # Drift lock: the rule-11 identity schema and the manifest schema's
        # declarative dataset_fingerprint must accept/reject the same values, so
        # "complete Guard-B" means one thing across bootstrap and comparison.
        manifest_schema = load_schema(SPLIT_SCHEMA)
        manifest_df = manifest_schema["anyOf"][1]["properties"]["dataset_fingerprint"]
        probes = [_full_lighter_fp()["dataset_fingerprint"]]
        probes += [
            fp["dataset_fingerprint"]
            for _, fp in _degenerate_fingerprints()
            if isinstance(fp, dict) and isinstance(fp.get("dataset_fingerprint"), dict)
        ]
        probes.append(
            {
                "source": "s",
                "version": "v",
                "date_window": {"start": "a", "end": "b"},
                "row_count": 5,
                "schema_hash": "h",
            }
        )
        for df in probes:
            with self.subTest(df=df):
                rule11_ok = not validate_against_schema(
                    df, vr._DATASET_FINGERPRINT_IDENTITY_SCHEMA
                )
                manifest_ok = not validate_against_schema(df, manifest_df)
                self.assertEqual(
                    rule11_ok,
                    manifest_ok,
                    f"rule11({rule11_ok}) vs manifest({manifest_ok}) disagree on {df!r}",
                )


class TestManifestFieldMatrix(unittest.TestCase):
    """Every string field in BOTH manifest modes must reject empty / whitespace /
    wrong-typed values (the schema's `\\S` pattern + type checks), so a
    present-but-degenerate field fails closed at bootstrap."""

    def _set(self, manifest: dict, path: tuple, value) -> dict:
        node = manifest
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return manifest

    def _string_fields(self):
        # (factory, dotted-path) for every string field that must be non-empty.
        frozen = [
            ("snapshot_id",),
            ("frozen_at",),
            ("frozen_by",),
            ("train", "path"),
            ("train", "sha256"),
            ("val", "path"),
            ("val", "sha256"),
            ("test", "path"),
            ("test", "sha256"),
        ]
        declarative = [
            ("split_rule", "split_key"),
            ("dataset_fingerprint", "source"),
            ("dataset_fingerprint", "version"),
            ("dataset_fingerprint", "schema_hash"),
        ]
        for path in frozen:
            yield _frozen_manifest, path
        for path in declarative:
            yield _declarative_manifest, path

    def test_empty_or_wrong_typed_string_fields_fail_closed(self):
        for factory, path in self._string_fields():
            for bad_label, bad in [("empty", ""), ("blank", "   "), ("non-str", 123)]:
                with self.subTest(field=".".join(path), bad=bad_label):
                    m = self._set(factory(), path, bad)
                    results = _run_check_manifest(m)
                    self.assertFalse(
                        _ok(results),
                        f"{'.'.join(path)}={bad!r} must fail check_manifest",
                    )

    def test_bad_numeric_fields_fail_closed(self):
        # size_bytes must be a positive int; row_count a non-negative int.
        for factory, path, bad in [
            (_frozen_manifest, ("train", "size_bytes"), 0),
            (_frozen_manifest, ("train", "size_bytes"), -5),
            (_frozen_manifest, ("train", "size_bytes"), "100"),
            (_declarative_manifest, ("dataset_fingerprint", "row_count"), -1),
            (_declarative_manifest, ("dataset_fingerprint", "row_count"), "10"),
            (_declarative_manifest, ("dataset_fingerprint", "row_count"), 1.5),
            (_declarative_manifest, ("seed",), "x"),
        ]:
            with self.subTest(field=".".join(path), bad=bad):
                m = self._set(factory(), path, bad)
                results = _run_check_manifest(m)
                self.assertFalse(
                    _ok(results), f"{'.'.join(path)}={bad!r} must fail check_manifest"
                )


if __name__ == "__main__":
    unittest.main()
