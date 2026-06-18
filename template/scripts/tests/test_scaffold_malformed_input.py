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
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import behavioral_equivalence as be  # noqa: E402
import check_questionnaire_drift as cqd  # noqa: E402
import migrate_ledger_v04_to_v05 as mig  # noqa: E402
import regenerate_state as rs  # noqa: E402
import validate_ledger as vl  # noqa: E402
from _ledger_common import load_schema, resolve_val_queries  # noqa: E402

BE_SCRIPT = SCRIPTS_DIR / "behavioral_equivalence.py"
DRIFT_SCRIPT = SCRIPTS_DIR / "check_questionnaire_drift.py"

_NON_DICTS = ["a string", ["a", "list"], 42, 3.14, True, None]

# A short non-UTF-8 byte sequence: 0xff/0xfe are never valid UTF-8 lead bytes,
# so reading this with encoding="utf-8" (errors="strict") raises
# UnicodeDecodeError. Used to prove the decode-error path WITHOUT a chmod (which
# is a no-op under root and can hang in some sandboxes).
_NON_UTF8 = b"\xff\xfe\x00\x01 not utf-8 \xff"

# chmod(0o000) is a no-op for the superuser (root can read anything), so the
# permission-denied assertions are skipped when the suite runs as root.
_IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def _make_unreadable(path: Path) -> bool:
    """chmod a file to 0o000; return True if the OSError path is testable here.

    Returns False (caller should skip) when running as root, where the mode bits
    do not deny the owner."""
    if _IS_ROOT:
        return False
    path.chmod(0o000)
    return True


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


class TestValidateLedgerScalarParentIdsCyclePass(unittest.TestCase):
    """F-1: a truthy SCALAR parent_ids (`parent_ids: 42`) must not crash the
    second (cycle-detection) pass — the orphan pass is guarded, this one was not.
    `obj.get("parent_ids") or []` kept the scalar and the graph comprehension
    raised `TypeError: 'int' object is not iterable`. Now it reaches a clean
    per-record FAIL line."""

    def test_scalar_parent_ids(self):
        # Schema requires parent_ids to be an array, so the scalar is also a clean
        # schema FAIL — but the load-bearing assertion is that the CYCLE pass did
        # not traceback (it reaches the SUMMARY line) regardless of verdict.
        schema_doc = {
            "type": "object",
            "properties": {"parent_ids": {"type": "array"}},
        }
        for bad in (42, 3.14, "ghost", True):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory(prefix="vl-scalar-pid-") as tmp:
                    ledger = Path(tmp) / "ledger"
                    ledger.mkdir()
                    (ledger / "a.json").write_text(
                        json.dumps({"id": "a", "parent_ids": bad}),
                        encoding="utf-8",
                    )
                    schema = Path(tmp) / "schema.json"
                    schema.write_text(json.dumps(schema_doc), encoding="utf-8")
                    ok, lines = vl.validate(ledger, schema)  # must not raise
                    # Crucially the cycle pass did not crash: a SUMMARY line is
                    # always emitted, and the scalar parent_ids is a schema FAIL.
                    self.assertFalse(ok)
                    self.assertTrue(any(ln.startswith("SUMMARY") for ln in lines))


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

    def test_per_metric_non_numeric_rtol(self):
        # F-3/G3: rtol: "abc" -> float() ValueError; now a clean CONFIG ERROR.
        for bad in ("abc", [1], {"k": "v"}, True):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit) as cm:
                    be.tolerance_for_metric(
                        "m",
                        "fp32",
                        {"per_metric": {"m": {"rtol": bad, "atol": 1e-6}}},
                    )
                self.assertIn("must be numeric", str(cm.exception))

    def test_per_metric_non_numeric_atol(self):
        with self.assertRaises(SystemExit) as cm:
            be.tolerance_for_metric(
                "m", "fp32", {"per_metric": {"m": {"rtol": 1e-4, "atol": "nope"}}}
            )
        self.assertIn("must be numeric", str(cm.exception))

    def test_dtype_defaults_non_numeric(self):
        # F-3/G3: the defaults_by_dtype branch also coerces with the guard.
        for bad in ("abc", [1], None):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit) as cm:
                    be.tolerance_for_metric(
                        "m",
                        "fp32",
                        {"defaults_by_dtype": {"fp32": {"rtol": bad, "atol": 1e-6}}},
                    )
                self.assertIn("must be numeric", str(cm.exception))


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


class TestBehavioralEquivalenceEvaluatorEquivalenceNotMapping(unittest.TestCase):
    """F-3: a truthy non-mapping evaluator_equivalence (a YAML list/string)
    survives `or {}` and would crash tolerance_for_metric's `.get("per_metric")`
    with AttributeError. Driven end-to-end through the CLI -> exit 2, no
    traceback."""

    def test_evaluator_equivalence_list(self):
        with tempfile.TemporaryDirectory(prefix="be-eqcfg-") as tmp:
            work = Path(tmp)
            metrics = work / "metrics.yaml"
            # evaluator_equivalence is a non-empty LIST: truthy, survives `or {}`.
            metrics.write_text(
                "primary_metric:\n"
                "  name: acc\n"
                "  eval_dtype: fp32\n"
                "evaluator_equivalence:\n"
                "  - not\n"
                "  - a\n"
                "  - mapping\n",
                encoding="utf-8",
            )
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
                    "json:loads",  # never reached; config fails first
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertEqual(proc.returncode, 2, f"stderr={proc.stderr!r}")
            self.assertIn("evaluator_equivalence must be a mapping", proc.stderr)


class TestBehavioralEquivalenceGoldenOutputsNotMapping(unittest.TestCase):
    """F-3/G4: a fixture whose golden_outputs is a non-mapping (e.g. a JSON list)
    survives load_fixtures' presence-only check and would crash check_fixture's
    `.items()` with AttributeError. Now a clean CONFIG ERROR (SystemExit)."""

    def test_golden_outputs_list(self):
        fixture = {
            "fixture_id": "fx1",
            "input": {},
            "golden_outputs": [1, 2, 3],  # not a mapping
        }
        with self.assertRaises(SystemExit) as cm:
            be.check_fixture(
                fixture,
                lambda _inp: {},  # evaluator never reached
                {},
                {},
                None,
                None,
            )
        self.assertIn("golden_outputs must be an object", str(cm.exception))


class TestBehavioralEquivalenceGoldenValueNonNumeric(unittest.TestCase):
    """D2/G3: a fixture golden_outputs VALUE that is non-numeric (str/list/dict/
    bool) survives the golden_outputs-is-a-mapping check but flows into
    abs()/math.isnan() in within_tolerance()/sanity_check_tolerance() and crashes
    with TypeError. check_fixture now rejects it as a clean CONFIG ERROR
    (SystemExit), consistent with the non-mapping golden_outputs rejection."""

    def test_non_numeric_golden(self):
        for bad in ("abc", [1, 2], {"k": "v"}, True, None):
            with self.subTest(bad=bad):
                fixture = {
                    "fixture_id": "fx1",
                    "input": {},
                    "golden_outputs": {"acc": bad},
                }
                with self.assertRaises(SystemExit) as cm:
                    be.check_fixture(
                        fixture,
                        lambda _inp: {"acc": 0.5},  # dict-shaped; golden fails first
                        {},  # metric_idx unused — golden check is loop-first
                        {},  # equivalence_cfg unused
                        None,
                        None,
                    )
                self.assertIn("must be numeric", str(cm.exception))


class TestBehavioralEquivalenceObservedNonNumeric(unittest.TestCase):
    """D3/G3: the evaluator returns a dict but with a non-numeric VALUE for a
    metric. math.isnan(observed) would crash with TypeError. check_fixture now
    records a clean behavioral FAILURE (exit 1, in the failures list), consistent
    with the evaluator-returned-a-non-dict path — not a traceback. (None is a
    distinct, already-covered 'metric not returned' case and is excluded here.)"""

    def test_non_numeric_observed(self):
        for bad in ("abc", [1], {"k": "v"}, True):
            with self.subTest(bad=bad):
                fixture = {
                    "fixture_id": "fx1",
                    "input": {},
                    "golden_outputs": {"acc": 0.5},
                }
                failures = be.check_fixture(
                    fixture,
                    lambda _inp, _b=bad: {"acc": _b},
                    {},  # observed check is before metric_idx use
                    {},
                    None,
                    None,
                )
                self.assertEqual(len(failures), 1, f"failures={failures!r}")
                self.assertIn("non-numeric", failures[0])


class TestBehavioralEquivalenceMinDeltaNonNumeric(unittest.TestCase):
    """D1/G3: primary_metric.minimum_meaningful_delta that is present but
    non-numeric (str/list/dict/bool) flows into sanity_check_tolerance's
    abs(minimum_meaningful_delta) and crashes with TypeError. main() now rejects
    it up front as a clean CONFIG ERROR (exit 2). Driven end-to-end through the
    CLI; the fixtures dir is never read (the guard precedes load_fixtures)."""

    def _run(self, min_delta_yaml: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory(prefix="be-mindelta-") as tmp:
            work = Path(tmp)
            metrics = work / "metrics.yaml"
            metrics.write_text(
                "primary_metric:\n"
                "  name: acc\n"
                "  eval_dtype: fp32\n"
                f"  minimum_meaningful_delta: {min_delta_yaml}\n"
                "evaluator_equivalence:\n"
                "  defaults_by_dtype:\n"
                "    fp32: {rtol: 1.0e-4, atol: 1.0e-6}\n",
                encoding="utf-8",
            )
            fixtures = work / "fixtures"
            fixtures.mkdir()
            return subprocess.run(
                [
                    sys.executable,
                    str(BE_SCRIPT),
                    "--metrics",
                    str(metrics),
                    "--fixtures",
                    str(fixtures),
                    "--evaluator",
                    "json:loads",  # never reached; config fails first
                ],
                capture_output=True,
                text=True,
            )

    def test_min_delta_non_numeric(self):
        # YAML string, list, mapping, and bool each parse to a non-numeric value.
        for bad_yaml in ('"not a number"', "[1, 2]", "{a: 1}", "true"):
            with self.subTest(bad=bad_yaml):
                proc = self._run(bad_yaml)
                self.assertNotIn(
                    "Traceback (most recent call last)", proc.stderr
                )
                self.assertEqual(proc.returncode, 2, f"stderr={proc.stderr!r}")
                self.assertIn("minimum_meaningful_delta must be", proc.stderr)


# --- CLASS D: I/O / encoding failures are clean errors, never tracebacks ------
#
# Every read of an external/operator/agent-provided file must convert OSError
# (unreadable) and UnicodeDecodeError (non-UTF-8) into the script's clean-error
# form (skip-with-warning, (False, ...), or SystemExit/exit-2) — never a raw
# traceback. These lock the non-verifier scaffold scripts; the verifier sites are
# locked in test_verifier_malformed_input.py.


class TestLoadSchemaIOErrors(unittest.TestCase):
    """_ledger_common.load_schema raises a clean, typed ValueError (not a raw
    OSError/UnicodeDecodeError/JSONDecodeError traceback) on any read failure."""

    def test_non_utf8_schema(self):
        with tempfile.TemporaryDirectory(prefix="ls-utf8-") as tmp:
            schema = Path(tmp) / "schema.json"
            schema.write_bytes(_NON_UTF8)
            with self.assertRaises(ValueError) as cm:
                load_schema(schema)
            self.assertIn("not loadable", str(cm.exception))

    def test_missing_schema(self):
        with tempfile.TemporaryDirectory(prefix="ls-miss-") as tmp:
            with self.assertRaises(ValueError) as cm:
                load_schema(Path(tmp) / "nope.json")
            self.assertIn("not loadable", str(cm.exception))

    def test_unreadable_schema(self):
        with tempfile.TemporaryDirectory(prefix="ls-perm-") as tmp:
            schema = Path(tmp) / "schema.json"
            schema.write_text("{}", encoding="utf-8")
            if not _make_unreadable(schema):
                self.skipTest("chmod-based permission test is a no-op as root")
            try:
                with self.assertRaises(ValueError) as cm:
                    load_schema(schema)
                self.assertIn("not loadable", str(cm.exception))
            finally:
                schema.chmod(0o644)


class TestValidateLedgerNonUtf8(unittest.TestCase):
    """validate_ledger: a non-UTF-8 shard and a non-UTF-8 schema both resolve to
    a clean (False, [FAIL ...]) — never a traceback."""

    def test_non_utf8_shard(self):
        with tempfile.TemporaryDirectory(prefix="vl-utf8-") as tmp:
            root = Path(tmp)
            ledger = root / "ledger"
            ledger.mkdir()
            (ledger / "bad.json").write_bytes(_NON_UTF8)
            schema = root / "schema.json"
            schema.write_text(json.dumps({"type": "object"}), encoding="utf-8")
            ok, lines = vl.validate(ledger, schema)  # must not raise
            self.assertFalse(ok)
            self.assertTrue(any("malformed JSON / unreadable" in ln for ln in lines))

    def test_non_utf8_schema(self):
        with tempfile.TemporaryDirectory(prefix="vl-schema-utf8-") as tmp:
            root = Path(tmp)
            ledger = root / "ledger"
            ledger.mkdir()
            (ledger / "g.json").write_text(json.dumps({"id": "g"}), encoding="utf-8")
            schema = root / "schema.json"
            schema.write_bytes(_NON_UTF8)
            ok, lines = vl.validate(ledger, schema)  # must not raise
            self.assertFalse(ok)
            self.assertTrue(lines and lines[0].startswith("FAIL schema not loadable"))


class TestRegenerateNonUtf8(unittest.TestCase):
    """regenerate_state: a non-UTF-8 shard is skipped with a warning, and a
    non-UTF-8 campaign.json degrades to no-metadata — neither crashes."""

    def test_non_utf8_shard_skipped(self):
        with tempfile.TemporaryDirectory(prefix="regen-utf8-") as tmp:
            ledger = Path(tmp) / "ledger"
            ledger.mkdir()
            (ledger / "good.json").write_text(
                json.dumps({"id": "good"}), encoding="utf-8"
            )
            (ledger / "bad.json").write_bytes(_NON_UTF8)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                records = rs.load_records(ledger)
            self.assertEqual([r.get("id") for r in records], ["good"])
            self.assertIn("bad.json", err.getvalue())

    def test_non_utf8_campaign_degrades(self):
        with tempfile.TemporaryDirectory(prefix="regen-camp-") as tmp:
            state = Path(tmp) / "state"
            state.mkdir(parents=True)
            (state / "campaign.json").write_bytes(_NON_UTF8)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                campaign = rs.load_campaign(state)  # must not raise
            self.assertEqual(campaign, {})
            self.assertIn("campaign.json", err.getvalue())


class TestMigrateNonUtf8Jsonl(unittest.TestCase):
    """migrate.read_jsonl: a non-UTF-8 file raises a clean SystemExit during the
    iteration-time decode, never a UnicodeDecodeError traceback."""

    def test_non_utf8_jsonl(self):
        with tempfile.TemporaryDirectory(prefix="mig-utf8-") as tmp:
            jsonl = Path(tmp) / "ledger.jsonl"
            jsonl.write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                mig.read_jsonl(jsonl)
            self.assertIn("not readable/decodable", str(cm.exception))

    def test_unreadable_jsonl(self):
        with tempfile.TemporaryDirectory(prefix="mig-perm-") as tmp:
            jsonl = Path(tmp) / "ledger.jsonl"
            jsonl.write_text('{"id":"a"}\n', encoding="utf-8")
            if not _make_unreadable(jsonl):
                self.skipTest("chmod-based permission test is a no-op as root")
            try:
                with self.assertRaises(SystemExit) as cm:
                    mig.read_jsonl(jsonl)
                self.assertIn("not readable/decodable", str(cm.exception))
            finally:
                jsonl.chmod(0o644)


class TestBehavioralEquivalenceNonUtf8(unittest.TestCase):
    """behavioral_equivalence: a non-UTF-8 fixture and a non-UTF-8 metrics.yaml
    both resolve to a clean CONFIG ERROR, never a traceback."""

    def test_non_utf8_fixture(self):
        with tempfile.TemporaryDirectory(prefix="be-utf8-") as tmp:
            (Path(tmp) / "f.json").write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                be.load_fixtures(Path(tmp))
            msg = str(cm.exception)
            self.assertTrue("not valid JSON" in msg or "not readable" in msg)

    def test_unreadable_fixture(self):
        with tempfile.TemporaryDirectory(prefix="be-perm-") as tmp:
            fx = Path(tmp) / "f.json"
            fx.write_text(json.dumps({"fixture_id": "x"}), encoding="utf-8")
            if not _make_unreadable(fx):
                self.skipTest("chmod-based permission test is a no-op as root")
            try:
                with self.assertRaises(SystemExit) as cm:
                    be.load_fixtures(Path(tmp))
                self.assertIn("not readable", str(cm.exception))
            finally:
                fx.chmod(0o644)

    def test_non_utf8_metrics_yaml_cli(self):
        # End-to-end through the CLI: a non-UTF-8 metrics.yaml -> exit 2 with a
        # message, no traceback.
        with tempfile.TemporaryDirectory(prefix="be-mx-") as tmp:
            work = Path(tmp)
            metrics = work / "metrics.yaml"
            metrics.write_bytes(_NON_UTF8)
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
                    "json:loads",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertEqual(proc.returncode, 2, f"stderr={proc.stderr!r}")
            self.assertIn("CONFIG ERROR", proc.stderr)


class TestCheckQuestionnaireDriftIO(unittest.TestCase):
    """check_questionnaire_drift: an unreadable/non-UTF-8 questionnaire or
    .example config is a clean SystemExit, never a traceback."""

    def test_non_utf8_questionnaire(self):
        with tempfile.TemporaryDirectory(prefix="cqd-utf8-") as tmp:
            q = Path(tmp) / "BOOTSTRAP_QUESTIONS.yaml"
            q.write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                cqd.load_questionnaire(q)
            self.assertIn("not readable/parseable", str(cm.exception))

    def test_non_utf8_example_config(self):
        with tempfile.TemporaryDirectory(prefix="cqd-cfg-") as tmp:
            cfg = Path(tmp) / "metrics.yaml.example"
            cfg.write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                cqd.load_example_config(cfg)
            self.assertIn("not readable/parseable", str(cm.exception))

    def test_unreadable_questionnaire(self):
        with tempfile.TemporaryDirectory(prefix="cqd-perm-") as tmp:
            q = Path(tmp) / "BOOTSTRAP_QUESTIONS.yaml"
            q.write_text("groups: []\n", encoding="utf-8")
            if not _make_unreadable(q):
                self.skipTest("chmod-based permission test is a no-op as root")
            try:
                with self.assertRaises(SystemExit) as cm:
                    cqd.load_questionnaire(q)
                self.assertIn("not readable/parseable", str(cm.exception))
            finally:
                q.chmod(0o644)


class TestCheckQuestionnaireDriftGroupsNotList(unittest.TestCase):
    """G1: a truthy non-list `groups` (e.g. `groups: 42` or a bare string)
    survives `questionnaire.get("groups") or []` and would either crash iteration
    with TypeError (int) or silently iterate string characters. collect_questions
    now coerces to a list and yields zero questions, never a traceback."""

    def test_groups_scalar_int(self):
        # `groups: 42` previously raised TypeError on iteration.
        self.assertEqual(cqd.collect_questions({"groups": 42}), [])

    def test_groups_string(self):
        # `groups: "abc"` previously iterated characters silently; now empty.
        self.assertEqual(cqd.collect_questions({"groups": "abc"}), [])

    def test_groups_mapping(self):
        self.assertEqual(cqd.collect_questions({"groups": {"k": "v"}}), [])


# --- CLASS E: --repo-root / --scaffold-root / default three-way resolution -----


class TestDriftRootResolution(unittest.TestCase):
    """The drift check resolves the scaffold root three ways:
      1. default (no flag)  = scaffold-relative (this script's parent.parent),
      2. --scaffold-root X  = X is the scaffold,
      3. --repo-root X      = DEPRECATED alias; the scaffold is X/template.
    The deprecated alias must keep working for old callers that pass the
    REPOSITORY root (containing template/).

    Layout-independent: the synthetic-scaffold cases build their own copy of the
    scaffold in a tempdir, so they pass identically in the upstream `template/`
    layout AND in a host install where the module lives under `autoresearch/`
    (where no `template/` sibling exists). The real scaffold is `SCAFFOLD_DIR`,
    the directory two levels up from this test that holds BOOTSTRAP_QUESTIONS.yaml
    and config/."""

    # The scaffold this test ships inside: <scaffold>/scripts/tests/<this file>.
    SCAFFOLD_DIR = SCRIPTS_DIR.parent

    @classmethod
    def _copy_scaffold(cls, dest: Path) -> None:
        """Copy the minimal scaffold (BOOTSTRAP_QUESTIONS.yaml + config/ +
        scripts/) into dest so the drift check has a real scaffold to read."""
        import shutil

        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            cls.SCAFFOLD_DIR / "BOOTSTRAP_QUESTIONS.yaml",
            dest / "BOOTSTRAP_QUESTIONS.yaml",
        )
        shutil.copytree(cls.SCAFFOLD_DIR / "config", dest / "config")

    def test_default_flagless(self):
        # No flag: resolves to the scaffold THIS script lives in (its own
        # parent.parent) — works whether that is template/ or a host autoresearch/.
        proc = subprocess.run(
            [sys.executable, str(DRIFT_SCRIPT)],
            capture_output=True,
            text=True,
        )
        self.assertNotIn("Traceback (most recent call last)", proc.stderr)
        self.assertEqual(proc.returncode, 0, f"out={proc.stdout!r} err={proc.stderr!r}")

    def test_scaffold_root_explicit(self):
        # --scaffold-root X : X IS the scaffold (holds BOOTSTRAP_QUESTIONS.yaml +
        # config/ directly).
        with tempfile.TemporaryDirectory(prefix="cqd-scaf-") as tmp:
            scaffold = Path(tmp) / "myscaffold"
            self._copy_scaffold(scaffold)
            proc = subprocess.run(
                [sys.executable, str(DRIFT_SCRIPT), "--scaffold-root", str(scaffold)],
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertEqual(
                proc.returncode, 0, f"out={proc.stdout!r} err={proc.stderr!r}"
            )

    def test_repo_root_deprecated_alias(self):
        # --repo-root X : DEPRECATED — X is the REPOSITORY root that CONTAINS the
        # scaffold under template/, so the scaffold is X/template. This must still
        # find template/... (the original --repo-root contract).
        with tempfile.TemporaryDirectory(prefix="cqd-repo-") as tmp:
            repo = Path(tmp) / "myrepo"
            self._copy_scaffold(repo / "template")
            proc = subprocess.run(
                [sys.executable, str(DRIFT_SCRIPT), "--repo-root", str(repo)],
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertEqual(
                proc.returncode, 0, f"out={proc.stdout!r} err={proc.stderr!r}"
            )

    def test_repo_root_points_at_template_subdir(self):
        # Sanity that the alias really appends template/: pointing --repo-root at a
        # directory WITHOUT a template/ subdir is an invocation error (exit 2),
        # never a traceback.
        with tempfile.TemporaryDirectory(prefix="cqd-repo-bad-") as tmp:
            proc = subprocess.run(
                [sys.executable, str(DRIFT_SCRIPT), "--repo-root", tmp],
                capture_output=True,
                text=True,
            )
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertEqual(
                proc.returncode, 2, f"out={proc.stdout!r} err={proc.stderr!r}"
            )


if __name__ == "__main__":
    unittest.main()
