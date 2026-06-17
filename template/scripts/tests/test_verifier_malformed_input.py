#!/usr/bin/env python3
"""test_verifier_malformed_input.py — malformed/untrusted-input robustness.

The §10.5 verifier contract: a malformed promotion request (or a corrupt ledger
shard) MUST resolve to a clean ``(False, reason)`` from each rule, a rejected
promotion packet end-to-end, or a nonzero exit with a message — and NEVER an
uncaught traceback.

Two surfaces are exercised:

  1. The rule functions directly (``rule_2`` .. ``rule_9``), proving each returns
     ``(False, str)`` rather than raising on a non-dict / wrong-typed field. This
     pins B1-B9.

  2. The full CLI / ``compute_status`` path: a request whose ``claims`` /
     ``references`` are arbitrary non-dicts, and a ledger directory holding a
     corrupt shard, both produce a rejected packet (exit 1) or a nonzero
     ``SystemExit("CONFIG ERROR: ...")`` — never a Python traceback (which would
     surface as a stderr ``Traceback (most recent call last)`` and NO packet).

Run:
    python3 -m unittest template.scripts.tests.test_verifier_malformed_input -v
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR / "verifier"))

VERIFIER = SCRIPTS_DIR / "verifier" / "verify_request.py"

# Load verify_request as a module so we can call the rule functions directly.
_spec = importlib.util.spec_from_file_location("verify_request", VERIFIER)
assert _spec is not None and _spec.loader is not None
vr = importlib.util.module_from_spec(_spec)
sys.modules["verify_request"] = vr  # dataclasses introspects sys.modules
_spec.loader.exec_module(vr)


def _ctx(request: dict, ledger: dict | None = None) -> "vr.VerifierContext":
    """Build a VerifierContext around an arbitrary (possibly malformed) request."""
    return vr.VerifierContext(
        request=request,
        request_path=Path("/nonexistent/proposals/req.json"),
        ledger=ledger if ledger is not None else {},
        metrics={},
        enforcement={},
        unsigned=True,
    )


# A minimal, well-formed-enough request used as the base for targeted mutations.
def _base_request() -> dict:
    return {
        "protocol_version": "0.5",
        "request_id": "20260101-000000-test",
        "maturity_level_used": 3,
        "requested_status": "promoted",
        "references": {
            "baseline_run": {"ledger_id": "b0", "content_sha256": "x" * 64},
            "candidate_runs": [{"ledger_id": "c0", "content_sha256": "y" * 64}],
            "skeptic_review": {"path": "reports/skeptic.md"},
        },
        "claims": {
            "role_separation_achieved": {"implementation_worker_vs_skeptic": "level_2"},
            "ablation": {"change_type": "single", "factorial_grid_completed": False},
            "val_set_exposure_at_request": {
                "queries_against_val_this_campaign": 1,
                "exposure_budget": 100,
            },
            "behavioral_equivalence_test_passed_for_evaluator": True,
        },
    }


# Every rule that the audit hardened. Each is invoked on malformed input and must
# return a (bool, reason) tuple WITHOUT raising.
_GUARDED_RULES = [
    "rule_2_references_rehash",
    "rule_4_role_separation_ok",
    "rule_5_stack_requires_factorial",
    "rule_6_val_exposure_not_exhausted",
    "rule_7_behavioral_equivalence_passed",
    "rule_8_skeptic_verdict_clean",
    "rule_9_statistics_recomputed",
    "rule_11_comparison_set_identity",
]

# A matrix of malformed scalars to substitute for fields the rules expect to be
# objects/mappings.
_NON_DICTS = ["a string", ["a", "list"], 42, 3.14, True, None]


class TestRulesNeverRaiseOnMalformedReferences(unittest.TestCase):
    """B1/B2/B3/B4: references as a non-dict, list refs with non-dict items, and
    non-string content_sha256 all yield clean (False, reason)."""

    def test_references_non_dict_rule_2(self):
        # B1: references is not a mapping.
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["references"] = bad
                ok, reason = vr.rule_2_references_rehash(_ctx(req))
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)

    def test_references_list_items_non_dict_rule_2(self):
        # B2: a list-valued reference whose items are not objects.
        req = _base_request()
        req["references"] = {"candidate_runs": ["not-an-object", 7, None]}
        ok, reason = vr.rule_2_references_rehash(_ctx(req))
        self.assertFalse(ok)
        self.assertIn("not an object", reason)

    def test_content_sha256_non_string_rule_2(self):
        # B3: content_sha256 is a non-string; the [:12] slice must not raise.
        for bad_sha in (123, ["x"], {"k": "v"}, True):
            with self.subTest(bad_sha=bad_sha):
                req = _base_request()
                req["references"] = {
                    "baseline_run": {"ledger_id": "b0", "content_sha256": bad_sha}
                }
                ledger = {"b0": {"entry": {"id": "b0"}, "canonical_bytes": b"{}"}}
                ok, reason = vr.rule_2_references_rehash(_ctx(req, ledger))
                self.assertFalse(ok)
                self.assertIn("not a string", reason)

    def test_non_string_path_rule_2(self):
        # B3 sibling: a reference 'path' that is a non-string must not reach
        # Path(123) (TypeError) — clean rejection instead.
        req = _base_request()
        req["references"] = {
            "baseline_run": {"content_sha256": "a" * 64, "path": 123}
        }
        ok, reason = vr.rule_2_references_rehash(_ctx(req))
        self.assertFalse(ok)
        self.assertIn("path is not a string", reason)

    def test_references_non_dict_rule_8(self):
        # B4: rule_8 with references as a non-dict.
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["references"] = bad
                ok, reason = vr.rule_8_skeptic_verdict_clean(_ctx(req))
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)

    def test_non_string_skeptic_path_rule_8(self):
        # rule_8 sibling: skeptic_review.path non-string must not reach Path(123).
        req = _base_request()
        req["references"] = {"skeptic_review": {"path": 123}}
        ok, reason = vr.rule_8_skeptic_verdict_clean(_ctx(req))
        self.assertFalse(ok)
        self.assertIn("not a string", reason)


class TestRulesNeverRaiseOnMalformedClaims(unittest.TestCase):
    """B5-B8: claims (and nested role_separation/ablation/val_exposure) as
    non-dicts yield clean (False, reason) instead of an AttributeError."""

    def test_claims_non_dict_reject_rules(self):
        # These rules REJECT when their required claim is absent (which a non-dict
        # claims block makes it) — and must do so cleanly, never raising.
        for rule_name in (
            "rule_4_role_separation_ok",
            "rule_6_val_exposure_not_exhausted",
            "rule_7_behavioral_equivalence_passed",
        ):
            rule = getattr(vr, rule_name)
            for bad in _NON_DICTS:
                with self.subTest(rule=rule_name, bad=bad):
                    req = _base_request()
                    req["claims"] = bad
                    ok, reason = rule(_ctx(req))
                    self.assertFalse(ok)
                    self.assertIsInstance(reason, str)

    def test_claims_non_dict_rule_5_never_raises(self):
        # rule_5 only fails for change_type=="stack" without a factorial grid; a
        # non-dict claims block makes change_type None, so it PASSES — the
        # contract here is purely "does not raise".
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["claims"] = bad
                ok, reason = vr.rule_5_stack_requires_factorial(_ctx(req))
                self.assertIsInstance(ok, bool)
                self.assertTrue(reason is None or isinstance(reason, str))

    def test_nested_role_separation_non_dict_rule_4(self):
        # B5: claims is a dict but role_separation_achieved is not.
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["claims"] = {"role_separation_achieved": bad}
                ok, reason = vr.rule_4_role_separation_ok(_ctx(req))
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)

    def test_role_separation_value_unhashable_rule_4(self):
        # S5: implementation_worker_vs_skeptic is an unhashable list/dict; the
        # `x in {"level_2","level_3"}` set test must not raise — clean reject.
        for bad in ([1, 2], {"k": "v"}):
            with self.subTest(bad=bad):
                req = _base_request()
                req["claims"] = {
                    "role_separation_achieved": {
                        "implementation_worker_vs_skeptic": bad
                    }
                }
                ok, reason = vr.rule_4_role_separation_ok(_ctx(req))
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)

    def test_nested_ablation_non_dict_rule_5(self):
        # B6: claims is a dict but ablation is not.
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["claims"] = {"ablation": bad}
                ok, reason = vr.rule_5_stack_requires_factorial(_ctx(req))
                # change_type cannot be "stack" on a non-dict ablation -> passes,
                # but the critical contract is: it does not RAISE.
                self.assertIsInstance(ok, bool)
                self.assertTrue(reason is None or isinstance(reason, str))

    def test_nested_val_exposure_non_dict_rule_6(self):
        # B7: claims is a dict but val_set_exposure_at_request is not.
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["claims"] = {"val_set_exposure_at_request": bad}
                ok, reason = vr.rule_6_val_exposure_not_exhausted(_ctx(req))
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)


class TestRule9MalformedReferences(unittest.TestCase):
    """rule_9 already guarded references; confirm it stays clean on every shape."""

    def test_references_non_dict(self):
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["references"] = bad
                ok, reason = vr.rule_9_statistics_recomputed(_ctx(req))
                self.assertFalse(ok)
                self.assertIsInstance(reason, str)


class TestRule11NeverRaises(unittest.TestCase):
    """rule_11 must never raise on a malformed request (it WARNs, never gates)."""

    def test_malformed_shapes(self):
        for bad in _NON_DICTS:
            with self.subTest(bad=bad):
                req = _base_request()
                req["references"] = bad
                ok, note = vr.rule_11_comparison_set_identity(_ctx(req))
                self.assertTrue(ok)  # WARN-not-gate: never fails the request
                self.assertIsInstance(note, str)


class TestEveryGuardedRuleSurvivesPureGarbage(unittest.TestCase):
    """A request that is an empty dict (no claims, no references) must not crash
    ANY rule — the rule-loop backstop is the last line, but per-rule guards must
    hold on their own too."""

    def test_empty_request(self):
        for rule_name in _GUARDED_RULES:
            rule = getattr(vr, rule_name)
            with self.subTest(rule=rule_name):
                ok, reason = rule(_ctx({}))
                self.assertIsInstance(ok, bool)
                self.assertTrue(reason is None or isinstance(reason, str))


# --- End-to-end CLI path ------------------------------------------------------


def _write_min_config(d: Path) -> tuple[Path, Path]:
    """Write the minimal metrics.yaml + enforcement.yaml the CLI requires."""
    metrics = d / "metrics.yaml"
    enforcement = d / "enforcement.yaml"
    metrics.write_text("protocol_version: '0.5'\n", encoding="utf-8")
    enforcement.write_text("mechanism: none\n", encoding="utf-8")
    return metrics, enforcement


def _run_verifier(request_path: Path, ledger_dir: Path, work: Path):
    metrics, enforcement = _write_min_config(work)
    out_dir = work / "out"
    out_dir.mkdir(exist_ok=True)
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--request",
            str(request_path),
            "--ledger",
            str(ledger_dir),
            "--metrics",
            str(metrics),
            "--enforcement",
            str(enforcement),
            "--out-dir",
            str(out_dir),
            "--verifier-identity",
            "unittest-malformed",
            "--unsigned",
        ],
        capture_output=True,
        text=True,
    )


class TestEndToEndMalformedRequestRejected(unittest.TestCase):
    """A wildly malformed request (claims/references as non-dicts) produces a
    rejected packet (exit 1) with NO traceback on stderr."""

    def test_garbage_claims_and_references(self):
        request = {
            "protocol_version": "0.5",
            "request_id": "garbage-req",
            "maturity_level_used": 3,
            "requested_status": "promoted",
            "references": "this is not an object",
            "claims": ["neither", "is", "this"],
        }
        with tempfile.TemporaryDirectory(prefix="mal-req-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            # one well-formed shard so load_ledger succeeds
            (ledger_dir / "b0.json").write_text(
                json.dumps({"id": "b0", "metrics": {}}), encoding="utf-8"
            )
            req_path = work / "req.json"
            req_path.write_text(json.dumps(request), encoding="utf-8")
            proc = _run_verifier(req_path, ledger_dir, work)

            self.assertNotIn(
                "Traceback (most recent call last)",
                proc.stderr,
                f"verifier crashed instead of rejecting: {proc.stderr!r}",
            )
            self.assertEqual(
                proc.returncode,
                1,
                f"expected rejected (exit 1). stdout={proc.stdout!r} "
                f"stderr={proc.stderr!r}",
            )
            packets = list((work / "out").glob("*-promotion-packet.json"))
            self.assertTrue(packets, "a rejected packet must still be written")
            packet = json.loads(packets[0].read_text(encoding="utf-8"))
            self.assertEqual(packet["status"], "rejected")

    def test_request_top_level_not_a_mapping(self):
        # load_json rejects a non-object request with a CONFIG ERROR (exit 2),
        # never a traceback.
        with tempfile.TemporaryDirectory(prefix="mal-top-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            (ledger_dir / "b0.json").write_text(
                json.dumps({"id": "b0"}), encoding="utf-8"
            )
            req_path = work / "req.json"
            req_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            proc = _run_verifier(req_path, ledger_dir, work)
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            # A SystemExit("CONFIG ERROR: ...") exits nonzero with a message
            # (Python maps a string SystemExit arg to exit code 1) — the contract
            # is "nonzero + message, never a traceback".
            self.assertNotEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
            self.assertIn("CONFIG ERROR", proc.stderr)


class TestEndToEndCorruptLedgerShard(unittest.TestCase):
    """B9: a corrupt ledger shard yields a CONFIG ERROR (exit 2), never a
    traceback."""

    def test_corrupt_shard(self):
        request = {
            "protocol_version": "0.5",
            "request_id": "corrupt-ledger",
            "maturity_level_used": 3,
            "requested_status": "promoted",
            "references": {"candidate_runs": []},
            "claims": {},
        }
        with tempfile.TemporaryDirectory(prefix="mal-shard-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            # A shard that is not valid JSON.
            (ledger_dir / "broken.json").write_text(
                "{ this is not json", encoding="utf-8"
            )
            req_path = work / "req.json"
            req_path.write_text(json.dumps(request), encoding="utf-8")
            proc = _run_verifier(req_path, ledger_dir, work)
            self.assertNotIn(
                "Traceback (most recent call last)",
                proc.stderr,
                f"verifier crashed on a corrupt shard: {proc.stderr!r}",
            )
            # SystemExit("CONFIG ERROR: ...") -> nonzero exit + message, no
            # traceback (the §10.5 malformed-input contract).
            self.assertNotEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
            self.assertIn("CONFIG ERROR", proc.stderr)
            self.assertIn("broken.json", proc.stderr)

    def test_non_string_shard_id(self):
        # S2: a shard whose 'id' is an unhashable list must not crash the
        # `entry_id in out` dict-key build in load_ledger.
        request = {
            "protocol_version": "0.5",
            "request_id": "badid",
            "maturity_level_used": 3,
            "requested_status": "promoted",
            "references": {"candidate_runs": []},
            "claims": {},
        }
        with tempfile.TemporaryDirectory(prefix="mal-id-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            (ledger_dir / "badid.json").write_text(
                json.dumps({"id": [1, 2], "branch": "b"}), encoding="utf-8"
            )
            req_path = work / "req.json"
            req_path.write_text(json.dumps(request), encoding="utf-8")
            proc = _run_verifier(req_path, ledger_dir, work)
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertNotEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
            self.assertIn("CONFIG ERROR", proc.stderr)
            self.assertIn("not a string", proc.stderr)


class TestRuleLoopBackstop(unittest.TestCase):
    """The rule-loop backstop converts an UNEXPECTED rule crash into a rejected
    packet, never a traceback. We force a crash by monkeypatching a rule to raise
    and driving main() in-process."""

    def test_backstop_converts_crash_to_rejection(self):
        original = vr.RULE_FUNCS["3_maturity_level_ge_3"]

        def _boom(ctx):
            raise RuntimeError("synthetic rule crash")

        vr.RULE_FUNCS["3_maturity_level_ge_3"] = _boom
        try:
            with tempfile.TemporaryDirectory(prefix="mal-backstop-") as tmp:
                work = Path(tmp)
                ledger_dir = work / "ledger"
                ledger_dir.mkdir()
                (ledger_dir / "b0.json").write_text(
                    json.dumps({"id": "b0", "metrics": {}}), encoding="utf-8"
                )
                metrics, enforcement = _write_min_config(work)
                out_dir = work / "out"
                out_dir.mkdir()
                req_path = work / "req.json"
                req_path.write_text(json.dumps(_base_request()), encoding="utf-8")

                rc = vr.main(
                    [
                        "--request",
                        str(req_path),
                        "--ledger",
                        str(ledger_dir),
                        "--metrics",
                        str(metrics),
                        "--enforcement",
                        str(enforcement),
                        "--out-dir",
                        str(out_dir),
                        "--verifier-identity",
                        "unittest-backstop",
                        "--unsigned",
                    ]
                )
                self.assertEqual(rc, 1, "a crashed rule must reject (exit 1)")
                packets = list(out_dir.glob("*-promotion-packet.json"))
                self.assertTrue(packets, "a packet must still be written")
                packet = json.loads(packets[0].read_text(encoding="utf-8"))
                self.assertEqual(packet["status"], "rejected")
                check = packet["criteria_check"]["3_maturity_level_ge_3"]
                self.assertFalse(check["pass"])
                self.assertIn("internal error", (check["note"] or "").lower())
        finally:
            vr.RULE_FUNCS["3_maturity_level_ge_3"] = original


if __name__ == "__main__":
    unittest.main()
