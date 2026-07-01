#!/usr/bin/env python3
"""test_ledger.py — stdlib unittest suite for the Protocol 0.5 ledger tools.

Run:
    python3 -m unittest discover -s template/scripts/tests -v
"""

from __future__ import annotations

import datetime as dt
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the scripts dir importable.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import _ledger_common  # noqa: E402
import log_experiment  # noqa: E402
import migrate_ledger_v04_to_v05 as migrate_mod  # noqa: E402
import regenerate_state  # noqa: E402
import validate_ledger  # noqa: E402

SCHEMA_PATH = SCRIPTS_DIR.parent / "schema" / "experiment_record.schema.json"


def make_record(rid, parents=None, branch="b", status="ok", val=0, metrics=None):
    return {
        "protocol_version": "0.5",
        "id": rid,
        "timestamp": "2026-05-18T10:00:00Z",
        "branch": branch,
        "hypothesis": "h",
        "parent_ids": list(parents or []),
        "source_commit": "aaa",
        "source_branch": branch,
        "resolvable_from_main": False,
        "status": status,
        "metrics": metrics if metrics is not None else {},
        "val_queries_incurred_by_this_run": val,
    }


def make_legacy_record(rid, parents=None, branch="b", status="ok", val=0, metrics=None):
    """A pre-provenance-redesign record carrying only the deprecated git_sha_*
    fields (no source_commit triple). Used to prove back-compat: legacy shards
    must still validate after git_sha_* is demoted to optional. Also stands in
    for the v0.4-era shape in migration/reconciliation tests."""
    return {
        "protocol_version": "0.5",
        "id": rid,
        "timestamp": "2026-05-18T10:00:00Z",
        "branch": branch,
        "hypothesis": "h",
        "parent_ids": list(parents or []),
        "git_sha_before": "aaa",
        "git_sha_after": "bbb",
        "status": status,
        "metrics": metrics if metrics is not None else {},
        "val_queries_incurred_by_this_run": val,
    }


def write_shard(ledger_dir: Path, record: dict) -> Path:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    p = ledger_dir / f"{record['id']}.json"
    p.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return p


class TempStateMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ledger-test-"))
        self.state = self.tmp / "state"
        self.ledger = self.state / "ledger"
        self.ledger.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# --- _ledger_common ----------------------------------------------------------


class TestCanonicalBytes(unittest.TestCase):
    def test_insertion_order_not_sorted(self):
        entry = {"b": 1, "a": 2}
        out = _ledger_common._canonical_record_bytes(entry)
        self.assertEqual(out, b'{"b":1,"a":2}')

    def test_no_trailing_newline(self):
        out = _ledger_common._canonical_record_bytes({"x": 1})
        self.assertFalse(out.endswith(b"\n"))

    def test_ensure_ascii_false_raw_utf8(self):
        out = _ledger_common._canonical_record_bytes({"s": "§17.6"})
        self.assertIn("§".encode("utf-8"), out)
        self.assertNotIn(b"\\u00a7", out)

    def test_compact_separators(self):
        out = _ledger_common._canonical_record_bytes({"a": 1, "b": 2})
        self.assertEqual(out, b'{"a":1,"b":2}')


class TestResolveValQueries(unittest.TestCase):
    def test_prefers_direct_field(self):
        self.assertEqual(
            _ledger_common.resolve_val_queries(
                {
                    "val_queries_incurred_by_this_run": 7,
                    "metrics": {"validation_set_queries": 99},
                }
            ),
            7,
        )

    def test_falls_back_to_metrics(self):
        self.assertEqual(
            _ledger_common.resolve_val_queries(
                {"metrics": {"validation_set_queries": 4}}
            ),
            4,
        )

    def test_default_zero(self):
        self.assertEqual(_ledger_common.resolve_val_queries({"metrics": {}}), 0)
        self.assertEqual(_ledger_common.resolve_val_queries({}), 0)

    def test_bool_is_not_a_count(self):
        self.assertEqual(
            _ledger_common.resolve_val_queries(
                {"val_queries_incurred_by_this_run": True}
            ),
            0,
        )


class TestSanitizeSlug(unittest.TestCase):
    def test_lowercase_and_map(self):
        self.assertEqual(_ledger_common.sanitize_slug("Ordinal Loss!"), "ordinal-loss")

    def test_collapse_and_strip(self):
        self.assertEqual(_ledger_common.sanitize_slug("--a___b--"), "a-b")

    def test_cap_40(self):
        self.assertLessEqual(len(_ledger_common.sanitize_slug("x" * 100)), 40)

    def test_empty(self):
        self.assertEqual(_ledger_common.sanitize_slug("!!!"), "")
        self.assertEqual(_ledger_common.sanitize_slug(""), "")


# --- log_experiment ----------------------------------------------------------


class TestLogExperiment(TempStateMixin):
    def _args(self, **over):
        ns = log_experiment.argparse.Namespace(
            state_dir=self.state,
            branch="loss_objective",
            hypothesis="ordinal loss helps",
            status="promising",
            parent=[],
            slug="My Slug!",
            metrics_json="",
            val_queries=3,
            node_title="",
            node_lesson=[],
            lifecycle_status="",
            promotion_status="",
            frontier_eligible=None,
            blocked_by=[],
            pruned_reason="",
            merged_into="",
            node_type="",
            branch_insight_json=[],
            schema=SCHEMA_PATH,
            protocol_version_file=self.tmp / "PV",
            repo_dir=self.tmp,
            source_commit="",
            source_branch="",
            git_sha_before="",
            git_sha_after="",
            split_mode="",
            dataset_fingerprint="",
            split_spec_hash="",
            split_seed=None,
            split_val_set_version="",
            membership_hash="",
            regenerate=False,
        )
        for k, v in over.items():
            setattr(ns, k, v)
        return ns

    def test_autofill_fields(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(self._args(), now)
        self.assertEqual(rec["protocol_version"], "0.5")
        self.assertEqual(rec["timestamp"], "2026-05-18T10:00:00Z")
        self.assertTrue(rec["id"].startswith("20260518-100000-"))
        self.assertTrue(rec["id"].endswith("-my-slug"))
        # Provenance triple auto-filled. repo_dir is a tmp non-repo, so the git
        # helpers fail closed: source_commit/source_branch -> "unknown",
        # resolvable_from_main -> False (deterministic, no remote dependency).
        self.assertTrue(rec["source_commit"])
        self.assertTrue(rec["source_branch"])
        self.assertIsInstance(rec["resolvable_from_main"], bool)
        self.assertFalse(rec["resolvable_from_main"])
        # New records never emit the deprecated fields.
        self.assertNotIn("git_sha_before", rec)
        self.assertNotIn("git_sha_after", rec)

    def test_deprecated_git_sha_flag_populates_source_commit(self):
        # Back-compat: host scripts still passing --git-sha-after must keep
        # working — the value flows into source_commit, never re-emitted as
        # git_sha_*. New record stays schema-valid.
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(
            self._args(git_sha_after="deadbeef"), now
        )
        self.assertEqual(rec["source_commit"], "deadbeef")
        self.assertNotIn("git_sha_after", rec)
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        self.assertEqual(_ledger_common.validate_against_schema(rec, schema), [])

    def test_tree_fields_are_omitted_by_default(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(self._args(), now)
        self.assertNotIn("lifecycle_status", rec)
        self.assertNotIn("promotion_status", rec)
        self.assertNotIn("frontier_eligible", rec)
        self.assertNotIn("node_type", rec)
        self.assertNotIn("branch_insights", rec)

    def test_tree_fields_stamp_when_flags_given(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(
            self._args(
                lifecycle_status="blocked",
                promotion_status="none",
                frontier_eligible=False,
                blocked_by=["human:needs-data-approval"],
                node_type="candidate",
            ),
            now,
        )
        self.assertEqual(rec["lifecycle_status"], "blocked")
        self.assertEqual(rec["promotion_status"], "none")
        self.assertFalse(rec["frontier_eligible"])
        self.assertEqual(rec["blocked_by"], ["human:needs-data-approval"])
        self.assertEqual(rec["node_type"], "candidate")
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        self.assertEqual(_ledger_common.validate_against_schema(rec, schema), [])

    def test_branch_insight_stamps_and_resolves_self_reference(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        insight = {
            "raw_observation": "Stage C improved NLL but latency increased.",
            "distilled_insight": "The branch is useful only under the latency cap.",
            "source_record_ids": ["self"],
            "updates_parent_ids": ["baseline"],
            "validated_constraint": "Future variants must keep latency under 20ms.",
            "confidence": "medium",
            "review_status": "draft",
        }
        rec = log_experiment.build_record(
            self._args(branch_insight_json=[json.dumps(insight)]),
            now,
        )
        self.assertEqual(len(rec["branch_insights"]), 1)
        stamped = rec["branch_insights"][0]
        self.assertEqual(stamped["source_record_ids"], [rec["id"]])
        self.assertEqual(stamped["updates_parent_ids"], ["baseline"])
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        self.assertEqual(_ledger_common.validate_against_schema(rec, schema), [])
        self.assertEqual(
            _ledger_common.validate_branch_insights(rec, {rec["id"]}),
            [],
        )

    def test_branch_insight_does_not_resolve_self_updated_parent(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, 0, tzinfo=dt.timezone.utc)
        insight = {
            "raw_observation": "A leaf tried to update itself.",
            "distilled_insight": "The update target must remain an ancestor.",
            "source_record_ids": ["self"],
            "updates_parent_ids": ["self"],
            "validated_constraint": "Self-targeted updates are not parent constraints.",
            "confidence": "medium",
        }
        rec = log_experiment.build_record(
            self._args(branch_insight_json=[json.dumps(insight)]),
            now,
        )
        stamped = rec["branch_insights"][0]
        self.assertEqual(stamped["source_record_ids"], [rec["id"]])
        self.assertEqual(stamped["updates_parent_ids"], ["self"])
        errors = _ledger_common.validate_branch_insights(rec, {rec["id"]})
        self.assertTrue(any("updates_parent_ids" in error for error in errors), errors)

    def test_writer_rejects_tree_cross_field_errors(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = log_experiment.main(
                [
                    "--state-dir",
                    str(self.state),
                    "--branch",
                    "blocked-branch",
                    "--hypothesis",
                    "needs approval",
                    "--status",
                    "promising",
                    "--lifecycle-status",
                    "blocked",
                    "--protocol-version-file",
                    str(self.tmp / "PV"),
                    "--repo-dir",
                    str(self.tmp),
                ]
            )
        self.assertEqual(rc, 2)
        self.assertEqual(list(self.ledger.glob("*.json")), [])

    def test_data_fingerprint_omitted_by_default(self):
        # With no split-identity flags, build_record emits no data_fingerprint
        # key — back-compat: existing call sites are unchanged.
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(self._args(), now)
        self.assertNotIn("data_fingerprint", rec)

    def test_data_fingerprint_stamped_when_flags_given(self):
        # Optional split-identity flags stamp data_fingerprint; the record stays
        # schema-valid (the field is optional, not via anyOf).
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(
            self._args(
                split_mode="declarative",
                dataset_fingerprint=json.dumps(
                    {
                        "source": "gold.activities",
                        "version": "v1",
                        "date_window": "w",
                        "row_count": 100,
                        "schema_hash": "h",
                    }
                ),
                split_spec_hash="deadbeef",
                split_seed=42,
                split_val_set_version="1",
                membership_hash=json.dumps({"train": "a", "val": "b", "test": "c"}),
            ),
            now,
        )
        fp = rec["data_fingerprint"]
        self.assertEqual(fp["mode"], "declarative")
        self.assertEqual(fp["seed"], 42)
        self.assertEqual(fp["split_spec_hash"], "deadbeef")
        self.assertEqual(fp["membership_sha256"], {"train": "a", "val": "b", "test": "c"})
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        self.assertEqual(_ledger_common.validate_against_schema(rec, schema), [])

    def test_legacy_git_sha_record_still_validates(self):
        # A pre-redesign record (git_sha_* only, no triple) must remain
        # schema-valid after git_sha_* is demoted to optional (back-compat).
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        legacy = make_legacy_record("20260518-100000-aaa001", parents=["baseline"])
        self.assertEqual(_ledger_common.validate_against_schema(legacy, schema), [])

    def test_record_without_any_provenance_is_rejected(self):
        # anyOf contract: a record carrying neither source_commit nor the legacy
        # git_sha_* pair must fail validation — every record carries provenance.
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        rec = make_record("20260518-100000-aaa001", parents=["baseline"])
        del rec["source_commit"]
        del rec["source_branch"]
        del rec["resolvable_from_main"]
        errors = _ledger_common.validate_against_schema(rec, schema)
        self.assertTrue(
            any("allowed schemas" in e for e in errors),
            f"expected an anyOf provenance error, got: {errors}",
        )

    def test_partial_triple_is_rejected(self):
        # The new-shape anyOf branch requires the FULL triple, so a record with
        # source_commit but missing the visible reachability bit is invalid —
        # direct writers can't drop source_branch/resolvable_from_main.
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        rec = make_record("20260518-100000-aaa001", parents=["baseline"])
        del rec["resolvable_from_main"]
        errors = _ledger_common.validate_against_schema(rec, schema)
        self.assertTrue(
            any("allowed schemas" in e for e in errors),
            f"expected a partial-triple anyOf error, got: {errors}",
        )

    def test_refuses_overwrite(self):
        (self.tmp / "PV").write_text("0.5\n", encoding="utf-8")
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        rec = log_experiment.build_record(self._args(), now)
        p = log_experiment.write_record(self.state, rec)
        contents_before = p.read_text(encoding="utf-8")
        with self.assertRaises(SystemExit):
            log_experiment.write_record(self.state, rec)
        self.assertEqual(p.read_text(encoding="utf-8"), contents_before)

    def test_schema_rejection_missing_required(self):
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        bad = make_record("20260518-100000-abc123")
        del bad["status"]
        errors = _ledger_common.validate_against_schema(bad, schema)
        self.assertTrue(any("status" in e for e in errors))

    def test_schema_rejection_wrong_type(self):
        schema = _ledger_common.load_schema(SCHEMA_PATH)
        bad = make_record("20260518-100000-abc123")
        bad["parent_ids"] = "not-a-list"
        errors = _ledger_common.validate_against_schema(bad, schema)
        self.assertTrue(any("parent_ids" in e for e in errors))

    def test_same_second_different_hex_no_collision(self):
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        ids = {log_experiment.make_id(now, "slug") for _ in range(200)}
        # 6 hex chars -> collisions astronomically unlikely across 200 draws.
        self.assertEqual(len(ids), 200)
        for i in ids:
            self.assertTrue(i.startswith("20260518-100000-"))


# --- regenerate_state --------------------------------------------------------


class TestRegenerate(TempStateMixin):
    def test_tree_reconstruction_from_parent_ids(self):
        write_shard(
            self.ledger,
            make_record("20260518-090000-aaa000", parents=[], branch="baseline"),
        )
        write_shard(
            self.ledger,
            make_record("20260518-100000-aaa001", parents=["20260518-090000-aaa000"]),
        )
        write_shard(
            self.ledger,
            make_record("20260518-110000-aaa002", parents=["20260518-090000-aaa000"]),
        )
        regenerate_state.regenerate(self.state)
        tree = json.loads((self.state / "research_tree.json").read_text())
        self.assertEqual(tree["roots"], ["20260518-090000-aaa000"])
        self.assertEqual(tree["nodes"]["20260518-090000-aaa000"]["node_type"], "baseline")
        self.assertEqual(
            tree["children"]["20260518-090000-aaa000"],
            ["20260518-100000-aaa001", "20260518-110000-aaa002"],
        )
        self.assertEqual(len(tree["nodes"]), 3)

    def test_baseline_sentinel_is_root(self):
        write_shard(
            self.ledger, make_record("20260518-090000-aaa000", parents=["baseline"])
        )
        regenerate_state.regenerate(self.state)
        tree = json.loads((self.state / "research_tree.json").read_text())
        self.assertEqual(tree["roots"], ["20260518-090000-aaa000"])
        self.assertEqual(tree["nodes"]["20260518-090000-aaa000"]["node_type"], "candidate")

    def test_val_counter_sum(self):
        write_shard(self.ledger, make_record("20260518-090000-aaa000", val=5))
        write_shard(
            self.ledger,
            make_record(
                "20260518-100000-aaa001", val=3, parents=["20260518-090000-aaa000"]
            ),
        )
        # one record uses metrics fallback
        write_shard(
            self.ledger,
            make_record(
                "20260518-110000-aaa002",
                parents=["20260518-090000-aaa000"],
                metrics={"validation_set_queries": 4},
            ),
        )
        # overwrite to drop the direct field for the fallback record
        rec = make_record(
            "20260518-110000-aaa002",
            parents=["20260518-090000-aaa000"],
            metrics={"validation_set_queries": 4},
        )
        del rec["val_queries_incurred_by_this_run"]
        write_shard(self.ledger, rec)
        regenerate_state.regenerate(self.state)
        ve = json.loads((self.state / "val_exposure.json").read_text())
        self.assertEqual(ve["queries"], 12)
        # derived counter ONLY: no hand prose
        self.assertNotIn("notes", ve)
        self.assertNotIn("last_incremented_by_iteration", ve)

    def test_val_exposure_budget_and_refresh_due(self):
        # When a sibling config/metrics.yaml carries val_set_exposure_budget,
        # regenerate emits exposure_budget + holdout_refresh_due (queries>=budget).
        (self.state.parent / "config").mkdir(parents=True, exist_ok=True)
        (self.state.parent / "config" / "metrics.yaml").write_text(
            "val_set_exposure_budget: 7\n", encoding="utf-8"
        )
        write_shard(self.ledger, make_record("20260518-090000-aaa000", val=5))
        write_shard(
            self.ledger,
            make_record(
                "20260518-100000-aaa001", val=3, parents=["20260518-090000-aaa000"]
            ),
        )
        regenerate_state.regenerate(self.state)
        ve = json.loads((self.state / "val_exposure.json").read_text())
        self.assertEqual(ve["queries"], 8)
        self.assertEqual(ve["exposure_budget"], 7)
        self.assertTrue(ve["holdout_refresh_due"])  # 8 >= 7

    def test_val_exposure_refresh_not_due_under_budget(self):
        (self.state.parent / "config").mkdir(parents=True, exist_ok=True)
        (self.state.parent / "config" / "metrics.yaml").write_text(
            "val_set_exposure_budget: 100\n", encoding="utf-8"
        )
        write_shard(self.ledger, make_record("20260518-090000-aaa000", val=5))
        regenerate_state.regenerate(self.state)
        ve = json.loads((self.state / "val_exposure.json").read_text())
        self.assertEqual(ve["exposure_budget"], 100)
        self.assertFalse(ve["holdout_refresh_due"])  # 5 < 100

    def test_val_exposure_no_budget_omits_fields(self):
        # No metrics.yaml -> exposure_budget / holdout_refresh_due are omitted.
        write_shard(self.ledger, make_record("20260518-090000-aaa000", val=5))
        regenerate_state.regenerate(self.state)
        ve = json.loads((self.state / "val_exposure.json").read_text())
        self.assertNotIn("exposure_budget", ve)
        self.assertNotIn("holdout_refresh_due", ve)

    def test_idempotence(self):
        write_shard(self.ledger, make_record("20260518-090000-aaa000", val=5))
        write_shard(
            self.ledger,
            make_record(
                "20260518-100000-aaa001", val=3, parents=["20260518-090000-aaa000"]
            ),
        )
        regenerate_state.regenerate(self.state)
        snap1 = {p.name: p.read_bytes() for p in self.state.glob("*") if p.is_file()}
        regenerate_state.regenerate(self.state)
        snap2 = {p.name: p.read_bytes() for p in self.state.glob("*") if p.is_file()}
        self.assertEqual(snap1, snap2)

    def test_atomic_write_no_tmp_left(self):
        write_shard(self.ledger, make_record("20260518-090000-aaa000", val=1))
        regenerate_state.regenerate(self.state)
        leftover = list(self.state.glob(".tmp-*"))
        self.assertEqual(leftover, [])

    def test_curated_node_fields_used(self):
        rec = make_record("20260518-090000-aaa000")
        rec["node_title"] = "Curated Title"
        rec["node_lessons"] = ["curated lesson"]
        write_shard(self.ledger, rec)
        regenerate_state.regenerate(self.state)
        tree = json.loads((self.state / "research_tree.json").read_text())
        node = tree["nodes"]["20260518-090000-aaa000"]
        self.assertEqual(node["title"], "Curated Title")
        self.assertEqual(node["lessons"], ["curated lesson"])

    def test_operational_tree_views(self):
        baseline = make_record(
            "20260518-090000-aaa000", parents=["baseline"], branch="baseline"
        )
        active = make_record(
            "20260518-100000-aaa001",
            parents=["20260518-090000-aaa000"],
            branch="frontier",
        )
        active["lifecycle_status"] = "proposed"
        active["node_type"] = "candidate"
        pruned = make_record(
            "20260518-110000-aaa002",
            parents=["20260518-090000-aaa000"],
            branch="bad-idea",
        )
        pruned["lifecycle_status"] = "pruned"
        pruned["pruned_reason"] = "guardrail regression"
        blocked = make_record(
            "20260518-120000-aaa003",
            parents=["20260518-090000-aaa000"],
            branch="needs-human",
        )
        blocked["lifecycle_status"] = "blocked"
        blocked["blocked_by"] = ["human:approve-data-refresh"]
        winner = make_record(
            "20260518-130000-aaa004",
            parents=["20260518-100000-aaa001"],
            branch="winner",
            status="branch_winner",
        )
        winner["promotion_status"] = "branch_winner"
        winner["maturity_level"] = 3
        merged = make_record(
            "20260518-140000-aaa005",
            parents=["20260518-100000-aaa001"],
            branch="subsumed",
        )
        merged["lifecycle_status"] = "merged"
        merged["promotion_status"] = "branch_winner"
        merged["maturity_level"] = 3
        merged["merged_into"] = "20260518-130000-aaa004"
        promoted = make_record(
            "20260518-150000-aaa006",
            parents=["20260518-130000-aaa004"],
            branch="already-promoted",
            status="promoted",
        )
        promoted["promotion_status"] = "promoted"
        promoted["maturity_level"] = 3
        for rec in (baseline, active, pruned, blocked, winner, merged, promoted):
            write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertTrue(ok, lines)

        regenerate_state.regenerate(self.state)
        tree = json.loads((self.state / "research_tree.json").read_text())
        views = tree["views"]
        self.assertEqual(
            views["lineage_order"][0],
            "20260518-090000-aaa000",
        )
        self.assertEqual(views["frontier"], ["20260518-100000-aaa001"])
        self.assertEqual(
            views["blocked"],
            [
                {
                    "id": "20260518-120000-aaa003",
                    "blocked_by": ["human:approve-data-refresh"],
                }
            ],
        )
        self.assertEqual(
            views["pruned"],
            [{"id": "20260518-110000-aaa002", "reason": "guardrail regression"}],
        )
        self.assertEqual(
            views["merged"],
            [
                {
                    "id": "20260518-140000-aaa005",
                    "merged_into": "20260518-130000-aaa004",
                }
            ],
        )
        self.assertEqual(
            views["promotion_candidates_by_maturity"]["level3_plus"],
            ["20260518-130000-aaa004"],
        )
        self.assertEqual(
            tree["nodes"]["20260518-100000-aaa001"]["lifecycle_status"], "proposed"
        )
        self.assertTrue(
            tree["nodes"]["20260518-100000-aaa001"]["frontier_eligible"]
        )

    def test_branch_insight_views(self):
        baseline = make_record(
            "20260518-090000-aaa000", parents=["baseline"], branch="baseline"
        )
        candidate = make_record(
            "20260518-100000-aaa001",
            parents=["20260518-090000-aaa000"],
            branch="architecture",
        )
        candidate["branch_insights"] = [
            {
                "raw_observation": "Factorial grid isolates attention_pool as the main effect.",
                "distilled_insight": "Prioritize attention_pool lesion and defer ordinal_hybrid.",
                "source_record_ids": [
                    "20260518-090000-aaa000",
                    "20260518-100000-aaa001",
                ],
                "updates_parent_ids": ["20260518-090000-aaa000"],
                "validated_constraint": "Future follow-ups should test attention_pool alone first.",
                "invalidated_ideas": [
                    "promote attention_pool+ordinal_hybrid without attribution"
                ],
                "confidence": "high",
                "review_status": "reviewed",
                "review_record_ids": ["20260518-100000-aaa001"],
                "retirement_signal": "Revisit after a factorial with new data split.",
            },
            {
                "raw_observation": "Malformed hand-written insight is tolerated by the derived reader.",
                "distilled_insight": "Derived views should not leak unknown enum values.",
                "source_record_ids": ["20260518-100000-aaa001"],
                "updates_parent_ids": ["baseline"],
                "validated_constraint": "Malformed enum values degrade to defaults.",
                "confidence": "surprisingly_sure",
                "review_status": "maybe",
            },
        ]
        write_shard(self.ledger, baseline)
        write_shard(self.ledger, candidate)

        regenerate_state.regenerate(self.state)
        tree = json.loads((self.state / "research_tree.json").read_text())
        insights = tree["views"]["branch_insights"]
        self.assertEqual(
            insights["by_source_record"]["20260518-090000-aaa000"][0]["record_id"],
            "20260518-100000-aaa001",
        )
        self.assertEqual(
            insights["by_updated_parent"]["20260518-090000-aaa000"][0]["record_id"],
            "20260518-100000-aaa001",
        )
        self.assertEqual(
            insights["constraints"][0]["validated_constraint"],
            "Future follow-ups should test attention_pool alone first.",
        )
        self.assertEqual(
            insights["invalidated_ideas"][0]["idea"],
            "promote attention_pool+ordinal_hybrid without attribution",
        )
        self.assertEqual(
            insights["by_record"]["20260518-100000-aaa001"][1]["confidence"],
            "low",
        )
        self.assertEqual(
            insights["by_record"]["20260518-100000-aaa001"][1]["review_status"],
            "draft",
        )

    def test_jsonl_lines_are_canonical(self):
        rec = make_record("20260518-090000-aaa000")
        write_shard(self.ledger, rec)
        regenerate_state.regenerate(self.state)
        lines = (self.state / "experiment_ledger.jsonl").read_bytes().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            lines[0], _ledger_common._canonical_record_bytes(json.loads(lines[0]))
        )


# --- validate_ledger ---------------------------------------------------------


class TestValidateLedger(TempStateMixin):
    def test_valid_set_passes(self):
        write_shard(
            self.ledger, make_record("20260518-090000-aaa000", parents=["baseline"])
        )
        write_shard(
            self.ledger,
            make_record("20260518-100000-aaa001", parents=["20260518-090000-aaa000"]),
        )
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertTrue(ok, lines)

    def test_duplicate_id(self):
        # Two files, same id -> filenames differ so both exist on disk.
        r1 = make_record("20260518-090000-aaa000")
        (self.ledger / "a.json").write_text(json.dumps(r1), encoding="utf-8")
        (self.ledger / "b.json").write_text(json.dumps(r1), encoding="utf-8")
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("duplicate" in line for line in lines))

    def test_orphan_parent(self):
        write_shard(
            self.ledger,
            make_record("20260518-100000-aaa001", parents=["does-not-exist"]),
        )
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("orphan" in line for line in lines))

    def test_malformed_json(self):
        (self.ledger / "bad.json").write_text("{not json", encoding="utf-8")
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("malformed" in line for line in lines))

    def test_non_utf8_shard_reported_not_crash(self):
        # A non-UTF8 shard raises UnicodeDecodeError (a ValueError, not OSError);
        # load_records must report it as malformed rather than crash.
        (self.ledger / "nonutf8.json").write_bytes(b'{"id": "\xff\xfe bad bytes"}')
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("malformed" in line for line in lines))

    def test_schema_invalid_record(self):
        bad = make_record("20260518-090000-aaa000")
        del bad["metrics"]
        write_shard(self.ledger, bad)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)

    def test_stem_must_equal_id(self):
        # Shard written under a filename whose stem != the internal id.
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        (self.ledger / "wrong-name.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(
            any("stem" in line and "internal id" in line for line in lines),
            lines,
        )

    def test_parent_ids_cycle_rejected(self):
        # Two records that point at each other: a 2-record cycle. Today this
        # passes orphan-resolution (both ids exist) but is not a valid DAG.
        a = make_record("20260518-090000-aaa000", parents=["20260518-100000-aaa001"])
        b = make_record("20260518-100000-aaa001", parents=["20260518-090000-aaa000"])
        write_shard(self.ledger, a)
        write_shard(self.ledger, b)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("cycle" in line for line in lines), lines)

    def test_pruned_lifecycle_requires_reason(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["lifecycle_status"] = "pruned"
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("pruned_reason" in line for line in lines), lines)

    def test_merged_lifecycle_requires_known_target(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["lifecycle_status"] = "merged"
        rec["merged_into"] = "20260518-100000-aaa001"
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("merged_into" in line for line in lines), lines)

    def test_blocked_lifecycle_requires_blocker(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["lifecycle_status"] = "blocked"
        rec["blocked_by"] = []
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("blocked_by" in line for line in lines), lines)

    def test_closed_lifecycle_cannot_be_frontier_eligible(self):
        write_shard(
            self.ledger,
            make_record("20260518-090000-aaa000", parents=["baseline"]),
        )
        cases = [
            (
                "20260518-100000-aaa001",
                "blocked",
                {"blocked_by": ["human:decision"]},
            ),
            (
                "20260518-110000-aaa002",
                "pruned",
                {"pruned_reason": "subsumed by stronger branch"},
            ),
            (
                "20260518-120000-aaa003",
                "merged",
                {"merged_into": "20260518-090000-aaa000"},
            ),
        ]
        for record_id, lifecycle, extra_fields in cases:
            rec = make_record(record_id, parents=["baseline"])
            rec["lifecycle_status"] = lifecycle
            rec["frontier_eligible"] = True
            rec.update(extra_fields)
            write_shard(self.ledger, rec)

        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        joined = "\n".join(lines)
        for _, lifecycle, _ in cases:
            self.assertIn(f"lifecycle_status {lifecycle!r}", joined)

    def test_branch_insight_requires_known_source_ids(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["branch_insights"] = [
            {
                "raw_observation": "Observation without real source.",
                "distilled_insight": "This should not affect future branches.",
                "source_record_ids": ["20260518-100000-missing"],
                "updates_parent_ids": ["baseline"],
                "validated_constraint": "Do not trust untraced lessons.",
                "confidence": "low",
            }
        ]
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("source_record_ids" in line for line in lines), lines)

    def test_branch_insight_requires_branch_action(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["branch_insights"] = [
            {
                "raw_observation": "Observation without a branch action.",
                "distilled_insight": "This should stay local narrative.",
                "source_record_ids": ["20260518-090000-aaa000"],
                "updates_parent_ids": ["baseline"],
                "confidence": "low",
            }
        ]
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(
            any(
                "requires validated_constraint or invalidated_ideas" in line
                for line in lines
            ),
            lines,
        )

    def test_branch_insight_requires_known_updated_parent(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["branch_insights"] = [
            {
                "raw_observation": "Observation points at a missing parent.",
                "distilled_insight": "This should not create a phantom branch view.",
                "source_record_ids": ["20260518-090000-aaa000"],
                "updates_parent_ids": ["20260518-100000-missing"],
                "validated_constraint": "Future work needs a real affected parent.",
                "confidence": "medium",
            }
        ]
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("updates_parent_ids" in line for line in lines), lines)

    def test_branch_insight_rejects_current_record_as_updated_parent(self):
        rec = make_record("20260518-090000-aaa000", parents=["baseline"])
        rec["branch_insights"] = [
            {
                "raw_observation": "Observation points at itself.",
                "distilled_insight": "A propagated insight should update an ancestor.",
                "source_record_ids": ["20260518-090000-aaa000"],
                "updates_parent_ids": ["20260518-090000-aaa000"],
                "validated_constraint": "Self-targeted updates are not allowed.",
                "confidence": "medium",
            }
        ]
        write_shard(self.ledger, rec)
        ok, lines = validate_ledger.validate(self.ledger, SCHEMA_PATH)
        self.assertFalse(ok)
        self.assertTrue(any("current record id" in line for line in lines), lines)


# --- migration round-trip ----------------------------------------------------


class TestMigration(TempStateMixin):
    def _write_v04_jsonl(self, records):
        path = self.state / "experiment_ledger.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
        return path

    def test_round_trip_deep_equal_all_fields(self):
        # Rich records with additive/nested fields (AE-shaped).
        r1 = {
            "protocol_version": "0.4",
            "id": "20260521-205012-5a60bd-process-smoke",
            "timestamp": "2026-05-21T20:50:12Z",
            "branch": "baseline",
            "hypothesis": "h",
            "parent_ids": ["baseline"],
            "git_sha_before": "x",
            "git_sha_after": "y",
            "status": "baseline",
            "metrics": {"validation_nll": 0.80, "validation_set_queries": 0},
            "maturity_level": 3,
            "not_deployable": False,
            "artifacts": {"mlflow": {"run_id": "abc", "experiment_id": "1"}},
            "lessons": ["§17.6 budget note"],
        }
        r2 = {
            "protocol_version": "0.4",
            "id": "20260521-213555-5a60bd-gradient-loss-smoke",
            "timestamp": "2026-05-21T21:35:55Z",
            "branch": "loss",
            "hypothesis": "h2",
            "parent_ids": ["20260521-205012-5a60bd-process-smoke"],
            "git_sha_before": "y",
            "git_sha_after": "z",
            "status": "promising",
            "metrics": {},
            "val_queries_incurred_by_this_run": 0,
        }
        # remove the prior committed val_exposure so no reconciliation kicks in
        self.ledger.rmdir()
        self._write_v04_jsonl([r1, r2])
        migrate_mod.migrate(self.state, force=False)

        # Deep-equal every field EXCEPT protocol_version (stamped) and any
        # val-query reconciliation (none here since no prior committed counter).
        for orig in (r1, r2):
            shard = json.loads(
                (self.state / "ledger" / f"{orig['id']}.json").read_text()
            )
            expected = dict(orig)
            expected["protocol_version"] = "0.5"
            self.assertEqual(shard, expected)

    def test_val_reconciliation_honest_sum_passes(self):
        # Per-record val inputs HONESTLY sum to the prior committed counter (52):
        # the safety valve returns silently and does not mutate any record.
        self.ledger.rmdir()
        vals = [5, 0, 3, 3, 0, 3, 0, 12, 26]  # sums to 52
        records = []
        prev = None
        for i, v in enumerate(vals):
            rid = f"20260518-{i:02d}0000-bbb{i:03d}"
            r = make_legacy_record(
                rid, parents=([prev] if prev else ["baseline"]), val=v
            )
            r["protocol_version"] = "0.4"
            records.append(r)
            prev = rid
        self._write_v04_jsonl(records)
        (self.state / "val_exposure.json").write_text(
            json.dumps(
                {"protocol_version": "0.4", "val_set_version": 1, "queries": 52}
            ),
            encoding="utf-8",
        )
        stats = migrate_mod.migrate(self.state, force=False)
        self.assertEqual(stats["val_query_sum"], 52)
        ve = json.loads((self.state / "val_exposure.json").read_text())
        self.assertEqual(ve["queries"], 52)
        # No record was mutated: the last shard's val input is its honest 26.
        last = json.loads(
            (self.state / "ledger" / f"{records[-1]['id']}.json").read_text()
        )
        self.assertEqual(last["val_queries_incurred_by_this_run"], 26)

    def test_val_reconciliation_mismatch_aborts_without_mutating(self):
        # Per-record sum (28) != prior committed (52): the migrator MUST abort
        # with a clear message and MUST NOT fold the delta into the last record.
        self.ledger.rmdir()
        vals = [5, 0, 3, 3, 0, 3, 0, 12, 2]  # sums to 28
        records = []
        prev = None
        for i, v in enumerate(vals):
            rid = f"20260518-{i:02d}0000-bbb{i:03d}"
            r = make_legacy_record(
                rid, parents=([prev] if prev else ["baseline"]), val=v
            )
            r["protocol_version"] = "0.4"
            records.append(r)
            prev = rid
        self._write_v04_jsonl(records)
        (self.state / "val_exposure.json").write_text(
            json.dumps(
                {"protocol_version": "0.4", "val_set_version": 1, "queries": 52}
            ),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit) as cm:
            migrate_mod.migrate(self.state, force=False)
        self.assertIn("reconcile", str(cm.exception).lower())

    def test_refuses_clobber_without_force(self):
        self.ledger.rmdir()
        r = make_legacy_record("20260518-090000-aaa000", parents=["baseline"])
        r["protocol_version"] = "0.4"
        self._write_v04_jsonl([r])
        migrate_mod.migrate(self.state, force=False)
        with self.assertRaises(SystemExit):
            migrate_mod.migrate(self.state, force=False)

    def test_idempotent_with_force(self):
        self.ledger.rmdir()
        r = make_legacy_record("20260518-090000-aaa000", parents=["baseline"], val=2)
        r["protocol_version"] = "0.4"
        self._write_v04_jsonl([r])
        migrate_mod.migrate(self.state, force=False)
        shard1 = (self.state / "ledger" / f"{r['id']}.json").read_bytes()
        migrate_mod.migrate(self.state, force=True)
        shard2 = (self.state / "ledger" / f"{r['id']}.json").read_bytes()
        self.assertEqual(shard1, shard2)


# --- headline concurrency test -----------------------------------------------


class TestConcurrencyMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ledger-git-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        self._git("config", "commit.gpgsign", "false")
        # seed commit so branches share a base
        (self.repo / "state").mkdir()
        (self.repo / "state" / "ledger").mkdir()
        (self.repo / "README").write_text("seed\n", encoding="utf-8")
        # Mirror the real repo: derived aggregates are git-ignored.
        (self.repo / ".gitignore").write_text(
            "state/experiment_ledger.jsonl\n"
            "state/research_tree.json\n"
            "state/val_exposure.json\n"
            "state/INDEX.md\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "seed")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=True,
        )

    def _default_branch(self):
        return self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def _write_record_and_commit(self, branch, rid, base):
        self._git("checkout", "-q", base)
        self._git("checkout", "-q", "-b", branch)
        rec = make_record(rid, parents=["baseline"], branch=branch)
        (self.repo / "state" / "ledger").mkdir(parents=True, exist_ok=True)
        shard = self.repo / "state" / "ledger" / f"{rid}.json"
        shard.write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        # Only commit the immutable record shard. Derived aggregates are
        # git-ignored in real repos; committing them here would make them
        # "would be overwritten by checkout" on sibling branches.
        self._git("add", str(shard))
        self._git("commit", "-q", "-m", f"add {rid}")

    def _assert_no_conflict_markers(self):
        for shard in (self.repo / "state" / "ledger").glob("*.json"):
            text = shard.read_text(encoding="utf-8")
            self.assertNotIn("<<<<<<<", text)
            self.assertNotIn(">>>>>>>", text)
            self.assertNotIn("=======", text)

    def _regenerate_and_assert_both(self, id_a, id_b):
        regenerate_state.regenerate(self.repo / "state")
        tree = json.loads((self.repo / "state" / "research_tree.json").read_text())
        self.assertIn(id_a, tree["nodes"])
        self.assertIn(id_b, tree["nodes"])
        jsonl = (self.repo / "state" / "experiment_ledger.jsonl").read_text()
        self.assertIn(id_a, jsonl)
        self.assertIn(id_b, jsonl)

    def test_divergent_branch_merge_zero_conflicts(self):
        base = self._default_branch()
        id_a = "20260518-100000-aaa00a"
        id_b = "20260518-100000-bbb00b"
        self._write_record_and_commit("branch-a", id_a, base)
        self._write_record_and_commit("branch-b", id_b, base)

        # --- git merge ---
        self._git("checkout", "-q", "branch-a")
        merge = subprocess.run(
            ["git", "merge", "--no-edit", "branch-b"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertEqual(merge.returncode, 0, merge.stderr + merge.stdout)
        self._assert_no_conflict_markers()
        self.assertTrue((self.repo / "state" / "ledger" / f"{id_a}.json").exists())
        self.assertTrue((self.repo / "state" / "ledger" / f"{id_b}.json").exists())
        self._regenerate_and_assert_both(id_a, id_b)

        # --- git rebase ---
        id_c = "20260518-100000-ccc00c"
        id_d = "20260518-100000-ddd00d"
        self._write_record_and_commit("rebase-a", id_c, base)
        self._write_record_and_commit("rebase-b", id_d, base)
        self._git("checkout", "-q", "rebase-b")
        rebase = subprocess.run(
            ["git", "rebase", "rebase-a"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertEqual(rebase.returncode, 0, rebase.stderr + rebase.stdout)
        self._assert_no_conflict_markers()
        self.assertTrue((self.repo / "state" / "ledger" / f"{id_c}.json").exists())
        self.assertTrue((self.repo / "state" / "ledger" / f"{id_d}.json").exists())
        self._regenerate_and_assert_both(id_c, id_d)

        # --- git cherry-pick ---
        id_e = "20260518-100000-eee00e"
        id_f = "20260518-100000-fff00f"
        self._write_record_and_commit("cp-a", id_e, base)
        self._write_record_and_commit("cp-b", id_f, base)
        cp_b_sha = self._git("rev-parse", "cp-b").stdout.strip()
        self._git("checkout", "-q", "cp-a")
        cherry = subprocess.run(
            ["git", "cherry-pick", cp_b_sha],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
        )
        self.assertEqual(cherry.returncode, 0, cherry.stderr + cherry.stdout)
        self._assert_no_conflict_markers()
        self.assertTrue((self.repo / "state" / "ledger" / f"{id_e}.json").exists())
        self.assertTrue((self.repo / "state" / "ledger" / f"{id_f}.json").exists())
        self._regenerate_and_assert_both(id_e, id_f)

    def test_same_second_different_hex_no_collision(self):
        now = dt.datetime(2026, 5, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
        a = log_experiment.make_id(now, "slug")
        b = log_experiment.make_id(now, "slug")
        self.assertNotEqual(a, b)
        self.assertEqual(a.split("-")[:2], b.split("-")[:2])


class TestProvenanceHelpers(unittest.TestCase):
    """Positive + negative coverage for the git provenance helpers in a real
    repo (the build_record tests only exercise the fail-closed non-repo path)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ledger-prov-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("branch", "-M", "main")  # robust across git default-branch config
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        self._git("config", "commit.gpgsign", "false")
        (self.repo / "f").write_text("x\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "c0")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=str(self.repo), capture_output=True, text=True, check=True
        )

    def test_resolvable_true_for_commit_on_main(self):
        sha = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertTrue(log_experiment.is_resolvable_from_main(self.repo, sha))
        self.assertEqual(log_experiment.git_current_branch(self.repo), "main")

    def test_resolvable_false_for_offmain_commit(self):
        self._git("checkout", "-q", "-b", "feature")
        (self.repo / "g").write_text("y\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "c1")
        sha = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertFalse(log_experiment.is_resolvable_from_main(self.repo, sha))
        self.assertEqual(log_experiment.git_current_branch(self.repo), "feature")

    def test_helpers_fail_closed_in_non_repo(self):
        # self.tmp is NOT a repo (only self.tmp/repo is); fails closed.
        self.assertEqual(log_experiment.git_head_sha(self.tmp), "unknown")
        self.assertEqual(log_experiment.git_current_branch(self.tmp), "unknown")
        self.assertFalse(
            log_experiment.is_resolvable_from_main(self.tmp, "deadbeef")
        )

    def test_provenance_resolves_from_subdir_of_repo(self):
        # The documented scaffold layout copies the template to
        # <host>/autoresearch/ and runs log_experiment from there — a SUBDIR of
        # the host worktree. Provenance must resolve to the host repo's
        # HEAD/branch (git discovers the enclosing worktree), NOT degrade to
        # "unknown"; otherwise every scaffold-relative record loses provenance.
        sub = self.repo / "state" / "autoresearch"
        sub.mkdir(parents=True)
        head = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(log_experiment.git_head_sha(sub), head)
        self.assertEqual(log_experiment.git_current_branch(sub), "main")
        self.assertTrue(log_experiment.is_resolvable_from_main(sub, head))

    def test_detached_head_reports_unknown_branch(self):
        sha = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("checkout", "-q", sha)  # detached HEAD
        self.assertEqual(log_experiment.git_current_branch(self.repo), "unknown")


if __name__ == "__main__":
    unittest.main()
