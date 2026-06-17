#!/usr/bin/env python3
"""test_scaffold_malformed_input.py — malformed-input robustness for the
non-verifier scaffold scripts.

Locks the Class-B fixes outside ``verify_request.py``: every malformed/untrusted
input resolves to a clean ``(False, ...)`` / skipped record / ``SystemExit`` with
a message — never an uncaught traceback.

Covers:
  - B10 ``_ledger_common.resolve_val_queries`` — non-dict entry -> 0.
  - B11 ``regenerate_state.build_research_tree`` — non-list ``parent_ids``.
  - B12 ``regenerate_state.load_records`` — corrupt shard skipped (warned).
  - B13 ``migrate_ledger_v04_to_v05.read_jsonl`` — corrupt JSONL line -> SystemExit.
  - B14 ``validate_ledger.validate`` — unloadable schema -> (False, [FAIL ...]).
  - B15 ``behavioral_equivalence`` main — metrics.yaml not a mapping -> exit 2.
  - B16 ``behavioral_equivalence.metric_index`` — malformed metric entries.
  - B17 ``behavioral_equivalence.tolerance_for_metric`` — missing rtol/atol.
  - B18 ``behavioral_equivalence.load_fixtures`` — corrupt / non-object fixture.

Run:
    python3 -m unittest template.scripts.tests.test_scaffold_malformed_input -v
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import behavioral_equivalence as be  # noqa: E402
import migrate_ledger_v04_to_v05 as mig  # noqa: E402
import regenerate_state as rs  # noqa: E402
import validate_ledger as vl  # noqa: E402
from _ledger_common import resolve_val_queries  # noqa: E402

BE_SCRIPT = SCRIPTS_DIR / "behavioral_equivalence.py"

_NON_DICTS = ["a string", ["a", "list"], 42, 3.14, True, None]


class TestResolveValQueriesNonDict(unittest.TestCase):
    """B10: a non-dict ledger entry contributes 0, never raises."""

    def test_non_dict_entry(self):
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                self.assertEqual(resolve_val_queries(bad), 0)


class TestBuildResearchTreeMalformedParents(unittest.TestCase):
    """B11: build_research_tree tolerates non-list parent_ids without crashing."""

    def test_non_list_parent_ids(self):
        records = [
            {"id": "a", "parent_ids": 42, "branch": "b"},  # int
            {"id": "c", "parent_ids": "baseline", "branch": "b"},  # str
            {"id": "d", "parent_ids": {"k": "v"}, "branch": "b"},  # dict
            {"id": "e", "branch": "b"},  # missing
        ]
        tree = rs.build_research_tree(records, {})
        # All become roots (no usable parents); parent_ids stored as [].
        self.assertEqual(sorted(tree["nodes"]), ["a", "c", "d", "e"])
        for rid in ("a", "c", "d", "e"):
            self.assertEqual(tree["nodes"][rid]["parent_ids"], [])
        self.assertEqual(tree["roots"], ["a", "c", "d", "e"])

    def test_list_parent_ids_with_unhashable_elements(self):
        # B11 sibling: parent_ids is a LIST whose elements are non-strings
        # (dict/list/int). The `p in nodes` membership test must not raise
        # "unhashable type" — non-string elements are dropped, like the validator.
        records = [
            {"id": "root", "branch": "b"},
            {"id": "a", "parent_ids": [{"nested": "obj"}], "branch": "b"},
            {"id": "c", "parent_ids": ["root", 5, {"x": 1}, "ghost"], "branch": "b"},
        ]
        tree = rs.build_research_tree(records, {})  # must not raise
        self.assertEqual(sorted(tree["nodes"]), ["a", "c", "root"])
        # only the valid string parent that exists ("root") is kept
        self.assertEqual(tree["nodes"]["a"]["parent_ids"], [])
        self.assertEqual(tree["nodes"]["c"]["parent_ids"], ["root", "ghost"])
        self.assertIn("c", tree["children"]["root"])
        self.assertEqual(sorted(tree["roots"]), ["a", "root"])


class TestRegenerateLoadRecordsCorruptShard(unittest.TestCase):
    """B12: a corrupt shard is skipped with a warning, not a crash."""

    def test_corrupt_shard_skipped(self):
        with tempfile.TemporaryDirectory(prefix="regen-mal-") as tmp:
            ledger = Path(tmp) / "ledger"
            ledger.mkdir()
            (ledger / "good.json").write_text(
                json.dumps({"id": "good"}), encoding="utf-8"
            )
            (ledger / "broken.json").write_text("{ not json", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                records = rs.load_records(ledger)
            self.assertEqual([r.get("id") for r in records], ["good"])
            self.assertIn("broken.json", err.getvalue())

    def test_full_regenerate_survives_corrupt_shard(self):
        # End-to-end: regenerate() over a state dir with a corrupt shard does not
        # raise and still produces the derived aggregates.
        with tempfile.TemporaryDirectory(prefix="regen-e2e-") as tmp:
            state = Path(tmp) / "state"
            ledger = state / "ledger"
            ledger.mkdir(parents=True)
            (ledger / "good.json").write_text(
                json.dumps({"id": "good", "branch": "b", "parent_ids": ["baseline"]}),
                encoding="utf-8",
            )
            (ledger / "broken.json").write_text("nope", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                stats = rs.regenerate(state)
            self.assertEqual(stats["records"], 1)


class TestMigrateReadJsonlCorruptLine(unittest.TestCase):
    """B13: a non-JSON line raises SystemExit with a message, not a traceback."""

    def test_corrupt_line(self):
        with tempfile.TemporaryDirectory(prefix="mig-mal-") as tmp:
            jsonl = Path(tmp) / "ledger.jsonl"
            jsonl.write_text('{"id":"a"}\n{ broken line\n', encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                mig.read_jsonl(jsonl)
            self.assertIn("not valid JSON", str(cm.exception))


class TestValidateLedgerUnloadableSchema(unittest.TestCase):
    """B14: an unloadable schema yields (False, [FAIL ...]), never a traceback."""

    def _ledger_with_record(self, root: Path) -> Path:
        ledger = root / "ledger"
        ledger.mkdir()
        (ledger / "g.json").write_text(json.dumps({"id": "g"}), encoding="utf-8")
        return ledger

    def test_corrupt_schema(self):
        with tempfile.TemporaryDirectory(prefix="vl-mal-") as tmp:
            root = Path(tmp)
            ledger = self._ledger_with_record(root)
            bad_schema = root / "schema.json"
            bad_schema.write_text("{ not json", encoding="utf-8")
            ok, lines = vl.validate(ledger, bad_schema)
            self.assertFalse(ok)
            self.assertTrue(lines and lines[0].startswith("FAIL schema not loadable"))

    def test_missing_schema(self):
        with tempfile.TemporaryDirectory(prefix="vl-miss-") as tmp:
            root = Path(tmp)
            ledger = self._ledger_with_record(root)
            ok, lines = vl.validate(ledger, root / "does-not-exist.json")
            self.assertFalse(ok)
            self.assertTrue(lines and lines[0].startswith("FAIL schema not loadable"))


class TestBehavioralEquivalenceMetricIndex(unittest.TestCase):
    """B16: malformed metric entries fail with a CONFIG ERROR, never an
    AttributeError/KeyError."""

    def test_primary_non_dict_is_skipped(self):
        # A non-dict primary_metric is coerced to {} and skipped (no name).
        self.assertEqual(be.metric_index({"primary_metric": "nope"}), {})

    def test_secondary_entry_non_dict(self):
        with self.assertRaises(SystemExit) as cm:
            be.metric_index({"secondary_metrics": ["x", 7]})
        self.assertIn("not a mapping", str(cm.exception))

    def test_secondary_entry_missing_name(self):
        with self.assertRaises(SystemExit) as cm:
            be.metric_index({"secondary_metrics": [{"direction": "min"}]})
        self.assertIn("missing 'name'", str(cm.exception))

    def test_guardrails_entry_non_dict(self):
        with self.assertRaises(SystemExit):
            be.metric_index({"guardrails": [42]})

    def test_secondary_non_list_ignored(self):
        # A non-list secondary_metrics is coerced to [] (no iteration crash).
        self.assertEqual(be.metric_index({"secondary_metrics": "nope"}), {})

    def test_primary_name_unhashable(self):
        # S3: a primary_metric name that is a list/dict must not reach out[name]
        # (unhashable dict key) — clean CONFIG ERROR instead.
        for bad in ([1, 2], {"k": "v"}):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit) as cm:
                    be.metric_index({"primary_metric": {"name": bad}})
                self.assertIn("must be a string", str(cm.exception))

    def test_secondary_name_unhashable(self):
        # S4: a secondary/guardrail name that is a list/dict must not reach
        # out[name].
        for bad in ([1], {"x": 1}):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    be.metric_index({"secondary_metrics": [{"name": bad}]})


class TestValidateLedgerUnhashableParentId(unittest.TestCase):
    """S1: a parent_id that is an unhashable list/dict must not crash the
    `pid not in all_ids` set-membership test."""

    def test_non_string_parent_id(self):
        with tempfile.TemporaryDirectory(prefix="vl-pid-") as tmp:
            ledger = Path(tmp) / "ledger"
            ledger.mkdir()
            (ledger / "a.json").write_text(
                json.dumps({"id": "a", "parent_ids": [{"nested": "obj"}, 5, "ghost"]}),
                encoding="utf-8",
            )
            schema = Path(tmp) / "schema.json"
            schema.write_text(json.dumps({"type": "object"}), encoding="utf-8")
            ok, lines = vl.validate(ledger, schema)  # must not raise
            self.assertFalse(ok)
            self.assertTrue(any("is not a string" in ln for ln in lines))


class TestBehavioralEquivalenceTolerance(unittest.TestCase):
    """B17: missing rtol/atol -> CONFIG ERROR, not a KeyError."""

    def test_per_metric_missing_atol(self):
        with self.assertRaises(SystemExit) as cm:
            be.tolerance_for_metric("m", "fp32", {"per_metric": {"m": {"rtol": 1e-4}}})
        self.assertIn("missing rtol/atol", str(cm.exception))

    def test_per_metric_non_dict(self):
        with self.assertRaises(SystemExit) as cm:
            be.tolerance_for_metric("m", "fp32", {"per_metric": {"m": "nope"}})
        self.assertIn("missing rtol/atol", str(cm.exception))

    def test_dtype_defaults_missing_keys(self):
        with self.assertRaises(SystemExit) as cm:
            be.tolerance_for_metric(
                "m", "fp32", {"defaults_by_dtype": {"fp32": {"rtol": 1e-4}}}
            )
        self.assertIn("missing rtol/atol", str(cm.exception))


class TestBehavioralEquivalenceLoadFixtures(unittest.TestCase):
    """B18: corrupt or non-object fixtures -> CONFIG ERROR, not a traceback."""

    def test_corrupt_fixture_json(self):
        with tempfile.TemporaryDirectory(prefix="be-fx-") as tmp:
            (Path(tmp) / "f.json").write_text("{ not json", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                be.load_fixtures(Path(tmp))
            self.assertIn("not valid JSON", str(cm.exception))

    def test_non_object_fixture(self):
        with tempfile.TemporaryDirectory(prefix="be-fx2-") as tmp:
            (Path(tmp) / "f.json").write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                be.load_fixtures(Path(tmp))
            self.assertIn("top-level must be an object", str(cm.exception))


class TestBehavioralEquivalenceMainMetricsNotMapping(unittest.TestCase):
    """B15: metrics.yaml that parses to a non-mapping -> exit 2 with a message,
    not a traceback. Driven end-to-end through the CLI."""

    def test_metrics_yaml_scalar(self):
        with tempfile.TemporaryDirectory(prefix="be-main-") as tmp:
            work = Path(tmp)
            metrics = work / "metrics.yaml"
            # A YAML scalar -> safe_load returns a str, not a mapping.
            metrics.write_text("just a string\n", encoding="utf-8")
            fixtures = work / "fixtures"
            fixtures.mkdir()
            proc = subprocess.run(
                [
                    sys.executable,
                    str(BE_SCRIPT),
                    "--metrics",
                    str(metrics),
                    "--fixtures",
                    str(fixtures),
                    "--evaluator",
                    "json:loads",  # never reached; metrics fails first
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertEqual(proc.returncode, 2, f"stderr={proc.stderr!r}")
            self.assertIn("did not parse as a mapping", proc.stderr)


if __name__ == "__main__":
    unittest.main()
