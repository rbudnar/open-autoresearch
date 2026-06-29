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
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# A short non-UTF-8 byte sequence (0xff/0xfe are never valid UTF-8 lead bytes):
# reading with encoding="utf-8" (errors="strict") raises UnicodeDecodeError.
# Proves the decode-error path WITHOUT a chmod (no-op as root, can hang in some
# sandboxes).
_NON_UTF8 = b"\xff\xfe\x00\x01 not utf-8 \xff"

# chmod(0o000) does not deny the superuser, so permission-denied assertions are
# skipped when the suite runs as root.
_IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0

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
            # §18 promotion evidence required by rule 9 (baseline rerun + at least
            # one ablation), so the base request stays "well-formed-enough".
            "baseline_rerun": {"ledger_id": "br0", "content_sha256": "z" * 64},
            "ablation_runs": [{"ledger_id": "ab0", "content_sha256": "w" * 64}],
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


def _valid_record(rid: str, metrics: "dict | None" = None) -> dict:
    """A minimal schema-valid experiment_record. rule 9 now schema-validates every
    referenced shard, so test ledger entries must be valid; `id` must match the
    schema pattern ^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}(-[a-z0-9-]+)?$. Pass
    metrics={} for ablation-style evidence that need not carry the primary
    metric."""
    return {
        "protocol_version": "0.5",
        "id": rid,
        "timestamp": "2026-01-01T00:00:00Z",
        "branch": "test",
        "hypothesis": "test hypothesis",
        "parent_ids": [],
        "status": "branch_winner",
        "metrics": {"validation_nll": 0.8} if metrics is None else metrics,
        # Satisfy the schema's anyOf provenance branch (source_commit form).
        "source_commit": "abc123",
        "source_branch": "test",
        "resolvable_from_main": False,
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

    def test_unhashable_ledger_id_rule_2(self):
        # F-4: ledger_id is an unhashable list/dict. `ctx.ledger.get(ledger_id)`
        # would raise `TypeError: unhashable type` — must be a clean mismatch
        # (False, "ledger_id is not a string"), mirroring rule 9's string guard.
        for bad_id in ([1, 2], {"k": "v"}):
            with self.subTest(bad_id=bad_id):
                req = _base_request()
                req["references"] = {
                    "baseline_run": {"ledger_id": bad_id, "content_sha256": "x" * 64}
                }
                ok, reason = vr.rule_2_references_rehash(_ctx(req))
                self.assertFalse(ok)
                self.assertIn("ledger_id is not a string", reason)

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
                note = check["note"] or ""
                self.assertIn("internal error", note.lower())
                # Backstop message MUST carry the exception TYPE so a stringifies-
                # to-empty exception still names what went wrong.
                self.assertIn("RuntimeError", note)
                self.assertIn("synthetic rule crash", note)
        finally:
            vr.RULE_FUNCS["3_maturity_level_ge_3"] = original

    def test_backstop_includes_type_for_empty_str_exception(self):
        # An exception whose str() is empty (e.g. a bare KeyError) must still
        # produce a non-empty diagnostic via type(exc).__name__.
        original = vr.RULE_FUNCS["3_maturity_level_ge_3"]

        def _boom(ctx):
            raise KeyError()  # str(KeyError()) == "" -> type name is the only info

        vr.RULE_FUNCS["3_maturity_level_ge_3"] = _boom
        try:
            with tempfile.TemporaryDirectory(prefix="mal-backstop2-") as tmp:
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
                        "unittest-backstop2",
                        "--unsigned",
                    ]
                )
                self.assertEqual(rc, 1)
                packet = json.loads(
                    next(out_dir.glob("*-promotion-packet.json")).read_text(
                        encoding="utf-8"
                    )
                )
                note = packet["criteria_check"]["3_maturity_level_ge_3"]["note"] or ""
                self.assertIn("KeyError", note)
        finally:
            vr.RULE_FUNCS["3_maturity_level_ge_3"] = original


# --- CLASS D: I/O / encoding failures on verifier inputs ----------------------
#
# Every verifier read of an external/operator/agent-provided file (ledger shard,
# request, metrics/enforcement config, referenced skeptic file, referenced ref
# path) must convert OSError (unreadable) and UnicodeDecodeError (non-UTF-8) into
# the verifier's clean-error form — a CONFIG ERROR exit, a rejected packet, or a
# (False, reason) — never a raw traceback.


class TestLoadLedgerIOErrors(unittest.TestCase):
    """load_ledger: a non-UTF-8 or unreadable shard is a CONFIG ERROR, not a
    traceback. The open() is INSIDE the guard now."""

    def test_non_utf8_shard(self):
        with tempfile.TemporaryDirectory(prefix="vr-utf8-") as tmp:
            ledger = Path(tmp) / "ledger"
            ledger.mkdir()
            (ledger / "bad.json").write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                vr.load_ledger(ledger)
            msg = str(cm.exception)
            self.assertIn("CONFIG ERROR", msg)
            self.assertIn("bad.json", msg)

    def test_unreadable_shard(self):
        if _IS_ROOT:
            self.skipTest("chmod-based permission test is a no-op as root")
        with tempfile.TemporaryDirectory(prefix="vr-perm-") as tmp:
            ledger = Path(tmp) / "ledger"
            ledger.mkdir()
            shard = ledger / "b0.json"
            shard.write_text(json.dumps({"id": "b0"}), encoding="utf-8")
            shard.chmod(0o000)
            try:
                with self.assertRaises(SystemExit) as cm:
                    vr.load_ledger(ledger)
                msg = str(cm.exception)
                self.assertIn("CONFIG ERROR", msg)
                self.assertIn("not readable", msg)
            finally:
                shard.chmod(0o644)


class TestLoadConfigIOErrors(unittest.TestCase):
    """load_json / load_yaml: a non-UTF-8 request/config is a CONFIG ERROR, not a
    traceback."""

    def test_non_utf8_request_json(self):
        with tempfile.TemporaryDirectory(prefix="vr-req-") as tmp:
            req = Path(tmp) / "req.json"
            req.write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                vr.load_json(req)
            self.assertIn("not readable/parseable", str(cm.exception))

    def test_non_utf8_metrics_yaml(self):
        with tempfile.TemporaryDirectory(prefix="vr-yaml-") as tmp:
            mx = Path(tmp) / "metrics.yaml"
            mx.write_bytes(_NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                vr.load_yaml(mx)
            self.assertIn("not readable/parseable", str(cm.exception))


class TestRule8SkepticFileIOErrors(unittest.TestCase):
    """rule_8: a non-UTF-8 or unreadable skeptic-review file -> (False, reason),
    never a traceback."""

    def _ctx_with_skeptic_root(self, root: Path, rel: str) -> "vr.VerifierContext":
        # The skeptic file must live INSIDE the campaign root (path-containment
        # is now enforced), so reference it by a RELATIVE path and point
        # request_path at <root>/proposals/req.json (root == parent.parent).
        req = _base_request()
        req["references"] = {"skeptic_review": {"path": rel}}
        return vr.VerifierContext(
            request=req,
            request_path=root / "proposals" / "req.json",
            ledger={},
            metrics={},
            enforcement={},
            unsigned=True,
        )

    def test_non_utf8_skeptic_file(self):
        with tempfile.TemporaryDirectory(prefix="vr-skep-") as tmp:
            root = Path(tmp)
            (root / "reports").mkdir()
            (root / "reports" / "skeptic.md").write_bytes(_NON_UTF8)
            ok, reason = vr.rule_8_skeptic_verdict_clean(
                self._ctx_with_skeptic_root(root, "reports/skeptic.md")
            )
            self.assertFalse(ok)
            self.assertIn("not readable/decodable", reason)

    def test_unreadable_skeptic_file(self):
        if _IS_ROOT:
            self.skipTest("chmod-based permission test is a no-op as root")
        with tempfile.TemporaryDirectory(prefix="vr-skep-perm-") as tmp:
            root = Path(tmp)
            (root / "reports").mkdir()
            skeptic = root / "reports" / "skeptic.md"
            skeptic.write_text("---\nverdict: no_objection\n---\n", encoding="utf-8")
            skeptic.chmod(0o000)
            try:
                ok, reason = vr.rule_8_skeptic_verdict_clean(
                    self._ctx_with_skeptic_root(root, "reports/skeptic.md")
                )
                self.assertFalse(ok)
                self.assertIn("not readable/decodable", reason)
            finally:
                skeptic.chmod(0o644)


class TestCheckRefUnreadablePath(unittest.TestCase):
    """rule_2 check_ref: an OSError mid-read on a referenced path is recorded as a
    missing ref (False, reason), never raised."""

    def test_unreadable_ref_path(self):
        if _IS_ROOT:
            self.skipTest("chmod-based permission test is a no-op as root")
        with tempfile.TemporaryDirectory(prefix="vr-ref-") as tmp:
            work = Path(tmp)
            # request_path.parent.parent is the base for relative ref paths; place
            # the referenced file there and reference it by basename.
            proposals = work / "proposals"
            proposals.mkdir()
            target = work / "artifact.bin"
            target.write_bytes(b"some bytes")
            target.chmod(0o000)
            req = _base_request()
            req["references"] = {
                "baseline_run": {"content_sha256": "a" * 64, "path": "artifact.bin"}
            }
            ctx = vr.VerifierContext(
                request=req,
                request_path=proposals / "req.json",
                ledger={},
                metrics={},
                enforcement={},
                unsigned=True,
            )
            try:
                ok, reason = vr.rule_2_references_rehash(ctx)
                self.assertFalse(ok)
                self.assertIn("not readable", reason)
            finally:
                target.chmod(0o644)


class TestEndToEndNonUtf8ShardRejected(unittest.TestCase):
    """A non-UTF-8 ledger shard drives the CLI to a CONFIG ERROR (nonzero exit)
    with NO traceback on stderr."""

    def test_non_utf8_shard_cli(self):
        request = {
            "protocol_version": "0.5",
            "request_id": "non-utf8-ledger",
            "maturity_level_used": 3,
            "requested_status": "promoted",
            "references": {"candidate_runs": []},
            "claims": {},
        }
        with tempfile.TemporaryDirectory(prefix="vr-e2e-utf8-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            (ledger_dir / "bad.json").write_bytes(_NON_UTF8)
            req_path = work / "req.json"
            req_path.write_text(json.dumps(request), encoding="utf-8")
            proc = _run_verifier(req_path, ledger_dir, work)
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            self.assertNotEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
            self.assertIn("CONFIG ERROR", proc.stderr)
            self.assertIn("bad.json", proc.stderr)


# Load sign_packet as a module so we can call its helpers/cmds directly.
SIGN_PACKET = SCRIPTS_DIR / "verifier" / "sign_packet.py"
_sp_spec = importlib.util.spec_from_file_location("sign_packet", SIGN_PACKET)
assert _sp_spec is not None and _sp_spec.loader is not None
sp = importlib.util.module_from_spec(_sp_spec)
sys.modules["sign_packet"] = sp
_sp_spec.loader.exec_module(sp)

# A 32-byte key satisfies get_signing_key()'s length floor (the cmds load it).
_SIGN_KEY = b"k" * 32


class TestSignPacketMalformed(unittest.TestCase):
    """F-A: sign_packet had ZERO test coverage. A packet whose `verifier` field is
    a non-dict (string/list) crashed `packet.get("verifier", {}).get("signature")`
    (cmd_sign/cmd_verify) and `verifier.get(k)` (compute_signature) with
    AttributeError. The `_load_packet` guard now rejects it as a clean CONFIG
    ERROR. Also locks the non-UTF-8/unreadable packet path (no traceback)."""

    def _write(self, tmp: str, obj_or_bytes) -> Path:
        p = Path(tmp) / "packet.json"
        if isinstance(obj_or_bytes, (bytes, bytearray)):
            p.write_bytes(obj_or_bytes)
        else:
            p.write_text(json.dumps(obj_or_bytes), encoding="utf-8")
        return p

    def test_verifier_non_dict_load_packet(self):
        for bad in ("a string", ["a", "list"], 42, True):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory(prefix="sp-vnd-") as tmp:
                    p = self._write(tmp, {"verifier": bad})
                    with self.assertRaises(SystemExit) as cm:
                        sp._load_packet(p)
                    self.assertIn(
                        "'verifier' block is missing or not an object",
                        str(cm.exception),
                    )

    def test_verifier_non_dict_cmd_sign(self):
        # cmd_sign reads packet.get("verifier", {}).get("signature") -> would
        # crash on a list verifier; the _load_packet guard fires first.
        with tempfile.TemporaryDirectory(prefix="sp-sign-") as tmp:
            p = self._write(tmp, {"verifier": ["not", "a", "dict"]})
            with self.assertRaises(SystemExit) as cm:
                sp.cmd_sign(p, _SIGN_KEY)
            self.assertIn("not an object", str(cm.exception))

    def test_verifier_non_dict_cmd_verify(self):
        with tempfile.TemporaryDirectory(prefix="sp-verify-") as tmp:
            p = self._write(tmp, {"verifier": "unsigned-but-a-string"})
            with self.assertRaises(SystemExit) as cm:
                sp.cmd_verify(p, _SIGN_KEY)
            self.assertIn("not an object", str(cm.exception))

    def test_non_utf8_packet(self):
        # Non-UTF-8 bytes -> UnicodeDecodeError inside _load_packet -> clean
        # CONFIG ERROR, never a traceback.
        with tempfile.TemporaryDirectory(prefix="sp-utf8-") as tmp:
            p = self._write(tmp, _NON_UTF8)
            with self.assertRaises(SystemExit) as cm:
                sp._load_packet(p)
            msg = str(cm.exception)
            self.assertIn("CONFIG ERROR", msg)
            self.assertIn("not readable/parseable", msg)

    def test_unreadable_packet(self):
        if _IS_ROOT:
            self.skipTest("chmod-based permission test is a no-op as root")
        with tempfile.TemporaryDirectory(prefix="sp-perm-") as tmp:
            p = self._write(tmp, {"verifier": {"signature": "unsigned"}})
            p.chmod(0o000)
            try:
                with self.assertRaises(SystemExit) as cm:
                    sp._load_packet(p)
                self.assertIn("not readable/parseable", str(cm.exception))
            finally:
                p.chmod(0o644)

    def test_non_string_signature_load_packet(self):
        # D4/G3: verifier.signature is later hit by existing[:16] (cmd_sign),
        # claimed[:16] and hmac.compare_digest (cmd_verify) — all str-only. A
        # present-but-non-string signature (int/float/list/dict/bool) crashed
        # those with TypeError; _load_packet now rejects it as a clean CONFIG
        # ERROR. (A list signature even SILENTLY slipped past `existing[:16]`
        # because list slicing succeeds — the guard closes that too.)
        for bad in (42, 3.14, ["sig"], {"s": "ig"}, True):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory(prefix="sp-sig-") as tmp:
                    p = self._write(tmp, {"verifier": {"signature": bad}})
                    with self.assertRaises(SystemExit) as cm:
                        sp._load_packet(p)
                    self.assertIn(
                        "'verifier.signature' is not a string", str(cm.exception)
                    )

    def test_non_string_signature_cmd_sign(self):
        # The existing[:16] subscript site in cmd_sign — the _load_packet guard
        # fires first, so the cmd never reaches the crash.
        with tempfile.TemporaryDirectory(prefix="sp-sig-sign-") as tmp:
            p = self._write(tmp, {"verifier": {"signature": 1234}})
            with self.assertRaises(SystemExit) as cm:
                sp.cmd_sign(p, _SIGN_KEY)
            self.assertIn("is not a string", str(cm.exception))

    def test_non_string_signature_cmd_verify(self):
        # The hmac.compare_digest / claimed[:16] site in cmd_verify.
        with tempfile.TemporaryDirectory(prefix="sp-sig-verify-") as tmp:
            p = self._write(tmp, {"verifier": {"signature": ["not", "a", "str"]}})
            with self.assertRaises(SystemExit) as cm:
                sp.cmd_verify(p, _SIGN_KEY)
            self.assertIn("is not a string", str(cm.exception))

    def test_null_signature_tolerated(self):
        # Boundary: a null (None) signature is NOT rejected — cmd_sign signs it.
        # Locks that the guard fires only on non-string NON-null values.
        with tempfile.TemporaryDirectory(prefix="sp-sig-null-") as tmp:
            p = self._write(
                tmp,
                {
                    "request_id": "r1",
                    "verifier": {
                        "type": "non_agent_ci",
                        "identity": "ci-1",
                        "signed_at": "2026-01-01T00:00:00+00:00",
                        "signature": None,
                    },
                },
            )
            loaded = sp._load_packet(p)  # tolerated: no raise
            self.assertIsNone(loaded["verifier"]["signature"])
            self.assertEqual(sp.cmd_sign(p, _SIGN_KEY), 0)

    def test_unwritable_packet_sign_is_clean_error(self):
        # Codex round 5 [Medium]: signing a read-only packet raised a raw
        # PermissionError; cmd_sign now wraps the write -> clean CONFIG ERROR.
        if _IS_ROOT:
            self.skipTest("chmod-based permission test is a no-op as root")
        with tempfile.TemporaryDirectory(prefix="sp-ro-") as tmp:
            p = self._write(
                tmp,
                {
                    "verifier": {
                        "type": "non_agent_ci",
                        "identity": "ci-1",
                        "signed_at": "2026-01-01T00:00:00+00:00",
                        "signature": "unsigned",
                    }
                },
            )
            p.chmod(0o400)
            try:
                with self.assertRaises(SystemExit) as cm:
                    sp.cmd_sign(p, _SIGN_KEY)
                self.assertIn("cannot write", str(cm.exception))
            finally:
                p.chmod(0o644)

    def test_well_formed_packet_still_loads(self):
        # Behavior preserved on valid input: a dict verifier loads fine and the
        # round-trip sign->verify succeeds.
        with tempfile.TemporaryDirectory(prefix="sp-ok-") as tmp:
            p = self._write(
                tmp,
                {
                    "request_id": "r1",
                    "status": "promoted",
                    "verifier": {
                        "type": "non_agent_ci",
                        "identity": "ci-1",
                        "signed_at": "2026-01-01T00:00:00+00:00",
                        "signature": "unsigned",
                    },
                },
            )
            self.assertEqual(sp.cmd_sign(p, _SIGN_KEY), 0)
            self.assertEqual(sp.cmd_verify(p, _SIGN_KEY), 0)


class TestRule3MaturityBool(unittest.TestCase):
    """Codex#4 sibling: maturity_level_used as a JSON bool. bool is an int
    subclass, so the old isinstance(int) accepted True/False; _is_int excludes
    it -> a clean rejection instead of a boolean masquerading as a level."""

    def test_bool_maturity_rejected(self):
        for bad in (True, False):
            with self.subTest(bad=bad):
                req = _base_request()
                req["maturity_level_used"] = bad
                ok, reason = vr.rule_3_maturity_level_ge_3(_ctx(req))
                self.assertFalse(ok)
                self.assertIn("not an int", reason)


class TestRule6ExposureBoolAndNegative(unittest.TestCase):
    """Codex#4 [Medium] fail-open: bool queries/budget (false/true == 0/1) passed
    the int check and could reach a deployable promoted packet. _is_int excludes
    bool; explicit non-negative bounds reject malformed negative counts."""

    def test_bool_exposure_rejected(self):
        req = _base_request()
        req["claims"]["val_set_exposure_at_request"] = {
            "queries_against_val_this_campaign": False,
            "exposure_budget": True,
        }
        ok, reason = vr.rule_6_val_exposure_not_exhausted(_ctx(req))
        self.assertFalse(ok)
        self.assertIn("requires int", reason)

    def test_negative_exposure_rejected(self):
        req = _base_request()
        req["claims"]["val_set_exposure_at_request"] = {
            "queries_against_val_this_campaign": -1,
            "exposure_budget": 10,
        }
        ok, reason = vr.rule_6_val_exposure_not_exhausted(_ctx(req))
        self.assertFalse(ok)
        self.assertIn("non-negative", reason)


class TestEndToEndEnforcementMechanismValidation(unittest.TestCase):
    """Codex#1 [High] fail-open: a malformed enforcement.yaml (`mechanism:
    not_real` / `[]` / a bool) was treated as real out-of-band enforcement and
    could mint a deployable `promoted` packet. main() now fails closed (CONFIG
    ERROR, no packet) on an unrecognized/non-string mechanism."""

    def _run(self, mechanism_yaml: str):
        with tempfile.TemporaryDirectory(prefix="mal-enf-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            (ledger_dir / "b0.json").write_text(
                json.dumps({"id": "b0", "metrics": {}}), encoding="utf-8"
            )
            metrics = work / "metrics.yaml"
            metrics.write_text("protocol_version: '0.5'\n", encoding="utf-8")
            enforcement = work / "enforcement.yaml"
            enforcement.write_text(
                f"mechanism: {mechanism_yaml}\n", encoding="utf-8"
            )
            out_dir = work / "out"
            out_dir.mkdir()
            req_path = work / "req.json"
            req_path.write_text(json.dumps(_base_request()), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VERIFIER),
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
                    "unittest-enf",
                    "--unsigned",
                ],
                capture_output=True,
                text=True,
            )
            return proc, list(out_dir.glob("*-promotion-packet.json"))

    def test_unknown_mechanism_fails_closed(self):
        # str-not-in-enum, a YAML list, a bool, and a whitespace string.
        for bad in ("not_real", "[]", "true", "'  '"):
            with self.subTest(bad=bad):
                proc, packets = self._run(bad)
                self.assertNotIn(
                    "Traceback (most recent call last)", proc.stderr
                )
                self.assertNotEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
                self.assertIn("enforcement.mechanism must be one of", proc.stderr)
                self.assertEqual(
                    packets, [], "no deployable packet on malformed mechanism"
                )

    def test_valid_mechanism_none_still_runs(self):
        # Regression: a VALID mechanism still produces a packet.
        proc, packets = self._run("none")
        self.assertNotIn("Traceback (most recent call last)", proc.stderr)
        self.assertTrue(
            packets, f"valid mechanism should write a packet; stderr={proc.stderr!r}"
        )


class TestEndToEndRequestIdFilenameSafety(unittest.TestCase):
    """Codex#2 [High]: request_id is the packet filename stem. `a/b` tracebacked
    (missing parent dir) and `../escaped` wrote OUTSIDE --out-dir. main() now
    rejects an unsafe request_id (CONFIG ERROR) before writing anything."""

    def test_unsafe_request_id_rejected(self):
        # traversal/separators, plus the filesystem-boundary cases codex round 2
        # found: embedded NUL (write_text -> ValueError) and an overlong stem.
        for bad in (
            "bad/id",
            "../escaped",
            "..",
            ".",
            "a/../b",
            "bad\x00id",
            "x" * 201,
        ):
            with self.subTest(bad=bad):
                with tempfile.TemporaryDirectory(prefix="mal-rid-") as tmp:
                    work = Path(tmp)
                    ledger_dir = work / "ledger"
                    ledger_dir.mkdir()
                    (ledger_dir / "b0.json").write_text(
                        json.dumps({"id": "b0", "metrics": {}}), encoding="utf-8"
                    )
                    req = _base_request()
                    req["request_id"] = bad
                    req_path = work / "req.json"
                    req_path.write_text(json.dumps(req), encoding="utf-8")
                    proc = _run_verifier(req_path, ledger_dir, work)
                    self.assertNotIn(
                        "Traceback (most recent call last)", proc.stderr
                    )
                    self.assertNotEqual(
                        proc.returncode, 0, f"stderr={proc.stderr!r}"
                    )
                    self.assertIn("request_id must be", proc.stderr)
                    # Nothing written anywhere under work (no escape, no partial).
                    escaped = list(work.rglob("*promotion-packet*"))
                    self.assertEqual(
                        escaped, [], f"no packet should be written for {bad!r}"
                    )


class TestRule5StackFactorialTruthiness(unittest.TestCase):
    """Codex round 3 [High]: rule 5 used `not factorial`, so a truthy non-bool
    (the string "false", 1, a list) let a stack change skip the §16.1.2
    factorial-grid evidence. It now requires `factorial_grid_completed is True`."""

    def test_truthy_nonbool_factorial_rejected(self):
        for bad in ("false", "true", 1, ["x"], {"k": "v"}):
            with self.subTest(bad=bad):
                req = _base_request()
                req["claims"]["ablation"] = {
                    "change_type": "stack",
                    "factorial_grid_completed": bad,
                }
                ok, reason = vr.rule_5_stack_requires_factorial(_ctx(req))
                self.assertFalse(ok)
                self.assertIn("factorial_grid_completed is not true", reason)

    def test_missing_factorial_rejected(self):
        req = _base_request()
        req["claims"]["ablation"] = {"change_type": "stack"}
        ok, _ = vr.rule_5_stack_requires_factorial(_ctx(req))
        self.assertFalse(ok)

    def test_true_factorial_passes(self):
        req = _base_request()
        req["claims"]["ablation"] = {
            "change_type": "stack",
            "factorial_grid_completed": True,
        }
        ok, _ = vr.rule_5_stack_requires_factorial(_ctx(req))
        self.assertTrue(ok)

    def test_non_stack_passes_regardless(self):
        req = _base_request()
        req["claims"]["ablation"] = {
            "change_type": "single",
            "factorial_grid_completed": "false",
        }
        ok, _ = vr.rule_5_stack_requires_factorial(_ctx(req))
        self.assertTrue(ok)


class TestRule6NegativeLedgerExposure(unittest.TestCase):
    """Codex round 3 [High]: a negative ledger val-query count canceled real
    exposure in the §17.6 anti-spoof sum, letting an under-reported claim pass.
    resolve_val_queries clamps negatives to 0 (round 3); round 4 then made rule 6
    REJECT a present-but-malformed exposure field outright, so a negative shard is
    now rejected directly rather than clamped — either way it cannot cancel
    positive exposure."""

    def test_negative_shard_cannot_cancel_exposure(self):
        req = _base_request()
        req["claims"]["val_set_exposure_at_request"] = {
            "queries_against_val_this_campaign": 0,
            "exposure_budget": 50,
        }
        ledger = {
            "a": {
                "entry": {"id": "a", "val_queries_incurred_by_this_run": 50},
                "canonical_bytes": b"{}",
            },
            "b": {
                "entry": {"id": "b", "val_queries_incurred_by_this_run": -1000},
                "canonical_bytes": b"{}",
            },
        }
        ok, reason = vr.rule_6_val_exposure_not_exhausted(_ctx(req, ledger))
        # The negative shard is now rejected as a malformed exposure field
        # (stronger than the round-3 clamp); the bypass stays closed.
        self.assertFalse(ok)
        self.assertIn("malformed val-exposure", reason)


class TestReferencePathTraversal(unittest.TestCase):
    """Codex round 3 [High]: references.*.path was resolved against the campaign
    root but never checked for containment, so `../escaped` or an absolute path
    let an agent satisfy the verifier's rehash/skeptic gates with an artifact
    OUTSIDE the auditable campaign tree. Both rule 2 and rule 8 now reject it."""

    def test_resolve_reference_path_helper(self):
        ctx = _ctx({})
        for bad in ("../escaped", "/etc/passwd", "a/../../x"):
            with self.subTest(bad=bad):
                self.assertIsNone(vr._resolve_reference_path(ctx, bad))
        # A relative path inside the root resolves (existence not required here).
        self.assertIsNotNone(vr._resolve_reference_path(ctx, "reports/x.md"))

    def test_skeptic_path_escape_rejected(self):
        for bad in ("../escaped-skeptic.md", "/etc/passwd", "a/../../x"):
            with self.subTest(bad=bad):
                req = _base_request()
                req["references"]["skeptic_review"] = {"path": bad}
                ok, reason = vr.rule_8_skeptic_verdict_clean(_ctx(req))
                self.assertFalse(ok)
                self.assertIn("escapes the campaign root", reason)

    def test_rule2_path_escape_rejected(self):
        req = _base_request()
        req["references"] = {
            "artifact": {"content_sha256": "a" * 64, "path": "../escaped.bin"}
        }
        ok, reason = vr.rule_2_references_rehash(_ctx(req))
        self.assertFalse(ok)
        self.assertIn("escapes the campaign root", reason)


class TestRule9RequiresPromotionEvidence(unittest.TestCase):
    """Codex round 4 [High]: rule 9 only checked candidate_runs + baseline_run, so
    a request omitting §18's required baseline_rerun / ablation_runs evidence
    could still mint a deployable `promoted` packet. rule 9 now requires both.
    Codex round 5 [High]: rule 9 now also schema-validates every referenced shard
    and requires a finite primary metric on the candidate + baseline evidence."""

    # ctx.metrics drives the primary-metric + direction check. rule 9 now
    # requires a COMPLETE decision config (round 7), so include direction +
    # min-delta and make the candidate beat the baseline.
    PRIMARY = {
        "primary_metric": {
            "name": "validation_nll",
            "direction": "minimize",
            "minimum_meaningful_delta": 0.005,
        }
    }

    def _full_ledger(self) -> dict:
        # Keyed by _base_request's reference ids; each a schema-valid record.
        # Candidate (0.825) beats baseline (0.847) by > min-delta. Ablation
        # evidence may carry empty metrics (no primary metric required).
        return {
            "b0": {
                "entry": _valid_record(
                    "20260101-000000-aaa000", metrics={"validation_nll": 0.847}
                ),
                "canonical_bytes": b"{}",
            },
            "c0": {
                "entry": _valid_record(
                    "20260101-000000-bbb000", metrics={"validation_nll": 0.825}
                ),
                "canonical_bytes": b"{}",
            },
            "br0": {
                "entry": _valid_record("20260101-000000-ccc000"),
                "canonical_bytes": b"{}",
            },
            "ab0": {
                "entry": _valid_record("20260101-000000-ddd000", metrics={}),
                "canonical_bytes": b"{}",
            },
        }

    def _ctx(self, req: dict, ledger: "dict | None" = None) -> "vr.VerifierContext":
        return vr.VerifierContext(
            request=req,
            request_path=Path("/nonexistent/proposals/req.json"),
            ledger=ledger if ledger is not None else self._full_ledger(),
            metrics=self.PRIMARY,
            enforcement={},
            unsigned=True,
        )

    def test_complete_evidence_passes(self):
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(_base_request()))
        self.assertTrue(ok, reason)

    def test_baseline_rerun_aliasing_baseline_rejected(self):
        # Codex round 8 [High]: a baseline rerun that IS the baseline shard.
        req = _base_request()
        req["references"]["baseline_rerun"]["ledger_id"] = "b0"  # == baseline_run
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertFalse(ok)
        self.assertIn("baseline_rerun aliases", reason)

    def test_ablation_aliasing_candidate_rejected(self):
        req = _base_request()
        req["references"]["ablation_runs"][0]["ledger_id"] = "c0"  # == candidate
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertFalse(ok)
        self.assertIn("aliases other evidence", reason)

    def test_ablation_aliasing_baseline_rejected(self):
        req = _base_request()
        req["references"]["ablation_runs"][0]["ledger_id"] = "b0"  # == baseline
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertFalse(ok)
        self.assertIn("aliases other evidence", reason)

    def test_baseline_rerun_may_equal_candidate(self):
        # level3 pattern: the candidate record also carries the baseline-rerun
        # data, so baseline_rerun == candidate is allowed (must NOT reject).
        req = _base_request()
        req["references"]["baseline_rerun"]["ledger_id"] = "c0"  # == candidate
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertTrue(ok, reason)

    def test_missing_baseline_rerun_rejected(self):
        req = _base_request()
        del req["references"]["baseline_rerun"]
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertFalse(ok)
        self.assertIn("baseline_rerun", reason)

    def test_missing_ablation_runs_rejected(self):
        req = _base_request()
        del req["references"]["ablation_runs"]
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertFalse(ok)
        self.assertIn("ablation_runs", reason)

    def test_empty_ablation_runs_rejected(self):
        req = _base_request()
        req["references"]["ablation_runs"] = []
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(req))
        self.assertFalse(ok)
        self.assertIn("ablation", reason)

    def test_schema_invalid_referenced_shard_rejected(self):
        # A referenced candidate shard missing required schema fields rejects
        # (the verifier must not promote from evidence validate_ledger rejects).
        ledger = self._full_ledger()
        ledger["c0"] = {
            "entry": {"id": "c0", "metrics": {}},  # not schema-valid
            "canonical_bytes": b"{}",
        }
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(_base_request(), ledger))
        self.assertFalse(ok)
        self.assertIn("fails schema", reason)

    def test_tree_invalid_referenced_shard_rejected(self):
        # Schema-valid but validate_ledger-invalid lifecycle metadata must reject
        # before the verifier signs a packet.
        ledger = self._full_ledger()
        candidate = _valid_record(
            "20260101-000000-bbb000", metrics={"validation_nll": 0.825}
        )
        candidate["lifecycle_status"] = "pruned"
        ledger["c0"] = {
            "entry": candidate,
            "canonical_bytes": b"{}",
        }
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(_base_request(), ledger))
        self.assertFalse(ok)
        self.assertIn("fails tree validation", reason)
        self.assertIn("pruned_reason", reason)

    def test_closed_candidate_lifecycle_rejected_even_when_tree_valid(self):
        for lifecycle, extra in (
            ("blocked", {"blocked_by": ["human:decision"]}),
            ("pruned", {"pruned_reason": "subsumed by stronger branch"}),
            ("merged", {"merged_into": "br0"}),
        ):
            with self.subTest(lifecycle=lifecycle):
                ledger = self._full_ledger()
                candidate = _valid_record(
                    "20260101-000000-bbb000", metrics={"validation_nll": 0.825}
                )
                candidate["lifecycle_status"] = lifecycle
                candidate.update(extra)
                ledger["c0"] = {
                    "entry": candidate,
                    "canonical_bytes": b"{}",
                }
                ok, reason = vr.rule_9_statistics_recomputed(
                    self._ctx(_base_request(), ledger)
                )
                self.assertFalse(ok)
                self.assertIn("closed and cannot be promoted", reason)

    def test_metric_empty_evidence_rejected(self):
        # Schema-valid candidate but with empty metrics (no primary metric) -> no
        # §13.2.1 evidence -> reject rather than mint a deployable packet.
        ledger = self._full_ledger()
        ledger["c0"] = {
            "entry": _valid_record("20260101-000000-bbb000", metrics={}),
            "canonical_bytes": b"{}",
        }
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(_base_request(), ledger))
        self.assertFalse(ok)
        self.assertIn("finite primary metric", reason)

    def test_nonfinite_primary_metric_rejected(self):
        ledger = self._full_ledger()
        ledger["b0"] = {
            "entry": _valid_record(
                "20260101-000000-aaa000", metrics={"validation_nll": float("nan")}
            ),
            "canonical_bytes": b"{}",
        }
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(_base_request(), ledger))
        self.assertFalse(ok)
        self.assertIn("finite primary metric", reason)


class TestRule6MalformedLedgerExposure(unittest.TestCase):
    """Codex round 4 [High]: a present-but-malformed (non-int / negative) ledger
    val-exposure field resolved to 0, under-reporting the §17.6 ledger-derived
    total. rule 6 now REJECTS a malformed exposure field rather than treat it as
    zero (the round-3 fix only handled negatives)."""

    def test_non_int_exposure_field_rejected(self):
        req = _base_request()
        req["claims"]["val_set_exposure_at_request"] = {
            "queries_against_val_this_campaign": 0,
            "exposure_budget": 1,
        }
        ledger = {
            "c0": {
                "entry": {"id": "c0", "val_queries_incurred_by_this_run": "100"},
                "canonical_bytes": b"{}",
            },
        }
        ok, reason = vr.rule_6_val_exposure_not_exhausted(_ctx(req, ledger))
        self.assertFalse(ok)
        self.assertIn("malformed val-exposure", reason)

    def test_nested_malformed_exposure_rejected(self):
        req = _base_request()
        req["claims"]["val_set_exposure_at_request"] = {
            "queries_against_val_this_campaign": 0,
            "exposure_budget": 1,
        }
        ledger = {
            "c0": {
                "entry": {"id": "c0", "metrics": {"validation_set_queries": True}},
                "canonical_bytes": b"{}",
            },
        }
        ok, reason = vr.rule_6_val_exposure_not_exhausted(_ctx(req, ledger))
        self.assertFalse(ok)
        self.assertIn("malformed val-exposure", reason)


class TestMaturityYamlInjection(unittest.TestCase):
    """Codex round 4 [Medium]: an untrusted maturity_level_used string injected
    YAML keys into the rendered .md packet frontmatter (a tool parsing the .md
    would read a rejected request as promoted). build_packet now coerces maturity
    to a safe int, so the frontmatter cannot carry injected keys."""

    def test_build_packet_coerces_maturity(self):
        req = _base_request()
        req["maturity_level_used"] = "3\nstatus: promoted\nnot_deployable: false"
        packet = vr.build_packet(
            _ctx(req),
            [("3_maturity_level_ge_3", False, "maturity_level_used is not an int")],
            verifier_identity="unittest",
            verifier_type="non_agent_ci",
            signing_key=None,
        )
        self.assertEqual(packet["maturity_level"], 0)
        self.assertEqual(packet["status"], "rejected")

    def test_markdown_frontmatter_not_injectable(self):
        import yaml  # available under the suite's pyyaml dep

        req = _base_request()
        req["maturity_level_used"] = "3\nstatus: promoted\nnot_deployable: false"
        with tempfile.TemporaryDirectory(prefix="vr-mat-") as tmp:
            work = Path(tmp)
            ledger_dir = work / "ledger"
            ledger_dir.mkdir()
            (ledger_dir / "b0.json").write_text(
                json.dumps({"id": "b0", "metrics": {}}), encoding="utf-8"
            )
            req_path = work / "req.json"
            req_path.write_text(json.dumps(req), encoding="utf-8")
            proc = _run_verifier(req_path, ledger_dir, work)
            self.assertNotIn("Traceback (most recent call last)", proc.stderr)
            md = list((work / "out").glob("*-promotion-packet.md"))[0].read_text(
                encoding="utf-8"
            )
            frontmatter = yaml.safe_load(md.split("---")[1])
            # The injected duplicate keys must NOT have flipped the machine-read
            # frontmatter to a promoted / deployable view.
            self.assertEqual(frontmatter.get("status"), "rejected")
            self.assertNotEqual(frontmatter.get("not_deployable"), False)


class TestRule9PrimaryDirectionComparison(unittest.TestCase):
    """Codex round 6 [High]: rule 9 checked the primary metric was present+finite
    but never that the candidate BEATS the baseline, so a worse (or `failed`)
    candidate with a finite metric could promote. rule 9 now requires the
    candidate to beat baseline by minimum_meaningful_delta in the configured
    direction (the deterministic part of §13.2.1; full CI re-derivation stays the
    implementer's job)."""

    MIN = {
        "primary_metric": {
            "name": "validation_nll",
            "direction": "minimize",
            "minimum_meaningful_delta": 0.005,
        }
    }

    def _ctx(self, baseline_val, candidate_val, metrics=None):
        ledger = {
            "b0": {
                "entry": _valid_record(
                    "20260101-000000-aaa000", metrics={"validation_nll": baseline_val}
                ),
                "canonical_bytes": b"{}",
            },
            "c0": {
                "entry": _valid_record(
                    "20260101-000000-bbb000", metrics={"validation_nll": candidate_val}
                ),
                "canonical_bytes": b"{}",
            },
            "br0": {
                "entry": _valid_record("20260101-000000-ccc000"),
                "canonical_bytes": b"{}",
            },
            "ab0": {
                "entry": _valid_record("20260101-000000-ddd000", metrics={}),
                "canonical_bytes": b"{}",
            },
        }
        return vr.VerifierContext(
            request=_base_request(),
            request_path=Path("/nonexistent/proposals/req.json"),
            ledger=ledger,
            metrics=metrics if metrics is not None else self.MIN,
            enforcement={},
            unsigned=True,
        )

    def test_worse_candidate_rejected(self):
        # minimize: candidate 999 is far worse than baseline 0.5.
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(0.5, 999.0))
        self.assertFalse(ok)
        self.assertIn("does not beat baseline", reason)

    def test_improvement_within_delta_rejected(self):
        # candidate only 0.001 better < min_delta 0.005.
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(0.847, 0.846))
        self.assertFalse(ok)
        self.assertIn("does not beat baseline", reason)

    def test_beats_by_delta_passes(self):
        ok, reason = vr.rule_9_statistics_recomputed(self._ctx(0.847, 0.825))
        self.assertTrue(ok, reason)

    def test_maximize_direction(self):
        maximize = {
            "primary_metric": {
                "name": "validation_nll",
                "direction": "maximize",
                "minimum_meaningful_delta": 0.01,
            }
        }
        # maximize: candidate must exceed baseline by >= 0.01.
        ok, _ = vr.rule_9_statistics_recomputed(self._ctx(0.80, 0.805, maximize))
        self.assertFalse(ok)  # only +0.005
        ok, _ = vr.rule_9_statistics_recomputed(self._ctx(0.80, 0.82, maximize))
        self.assertTrue(ok)  # +0.02

    def test_incomplete_decision_config_fails_closed(self):
        # Codex round 7 [High]: a missing/malformed primary_metric decision config
        # must FAIL CLOSED (not skip the comparison) even when the candidate is
        # actually worse than baseline (0.5 vs 999).
        bad_configs = [
            ({}, "primary_metric"),  # no primary_metric block
            ({"primary_metric": {"direction": "minimize",
                                 "minimum_meaningful_delta": 0.005}}, "name"),
            ({"primary_metric": {"name": "validation_nll",
                                 "minimum_meaningful_delta": 0.005}}, "direction"),
            ({"primary_metric": {"name": "validation_nll", "direction": "sideways",
                                 "minimum_meaningful_delta": 0.005}}, "direction"),
            ({"primary_metric": {"name": "validation_nll", "direction": "minimize"}},
             "minimum_meaningful_delta"),
            ({"primary_metric": {"name": "validation_nll", "direction": "minimize",
                                 "minimum_meaningful_delta": float("nan")}},
             "minimum_meaningful_delta"),
            ({"primary_metric": {"name": "validation_nll", "direction": "minimize",
                                 "minimum_meaningful_delta": True}},
             "minimum_meaningful_delta"),
            ({"primary_metric": {"name": "validation_nll", "direction": "minimize",
                                 "minimum_meaningful_delta": 0}},
             "minimum_meaningful_delta"),
        ]
        for metrics, needle in bad_configs:
            with self.subTest(metrics=metrics):
                ok, reason = vr.rule_9_statistics_recomputed(
                    self._ctx(0.5, 999.0, metrics)
                )
                self.assertFalse(ok)
                self.assertIn(needle, reason)


class TestCampaignRootFromLedger(unittest.TestCase):
    """Codex round 6 [High]: deriving the evidence-boundary root from the
    agent-influenceable --request location let a shallow request path expand the
    boundary to '/'. The root is now the operator-controlled campaign_root
    (from --ledger)."""

    def _ctx(self, campaign_root):
        return vr.VerifierContext(
            request={},
            request_path=Path("/tmp/shallow-req.json"),  # parent.parent == '/'
            ledger={},
            metrics={},
            enforcement={},
            unsigned=True,
            campaign_root=campaign_root,
        )

    def test_root_is_campaign_not_request(self):
        ctx = self._ctx(Path("/some/campaign"))
        # Resolves against campaign_root, NOT request_path.parent.parent ('/').
        self.assertEqual(
            vr._resolve_reference_path(ctx, "reports/x.md"),
            Path("/some/campaign/reports/x.md"),
        )
        # An escape relative to the campaign root is still rejected.
        self.assertIsNone(vr._resolve_reference_path(ctx, "../escape.md"))
        self.assertIsNone(vr._resolve_reference_path(ctx, "/etc/passwd"))

    def test_shallow_request_does_not_widen_boundary(self):
        # With campaign_root set, a ref that WOULD be 'inside' '/' (the shallow
        # request's parent.parent) but is outside the campaign is not reachable:
        # it resolves under the campaign root instead.
        ctx = self._ctx(Path("/some/campaign"))
        resolved = vr._resolve_reference_path(ctx, "tmp/outside.md")
        self.assertEqual(resolved, Path("/some/campaign/tmp/outside.md"))


class TestLoadLedgerStemIdInvariant(unittest.TestCase):
    """Codex round 7 [High]: the verifier promoted from ledger shards that
    validate_ledger.py rejects for filename-stem != internal id. load_ledger now
    enforces the same invariant (fail-closed at load)."""

    def test_stem_id_mismatch_rejected(self):
        with tempfile.TemporaryDirectory(prefix="vr-stem-") as tmp:
            d = Path(tmp)
            (d / "wrong-name.json").write_text(
                json.dumps({"id": "20260101-000000-aaa000", "metrics": {}}),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as cm:
                vr.load_ledger(d)
            self.assertIn("filename stem", str(cm.exception))

    def test_matching_stem_loads(self):
        with tempfile.TemporaryDirectory(prefix="vr-stem-ok-") as tmp:
            d = Path(tmp)
            (d / "20260101-000000-aaa000.json").write_text(
                json.dumps({"id": "20260101-000000-aaa000", "metrics": {}}),
                encoding="utf-8",
            )
            ledger = vr.load_ledger(d)
            self.assertIn("20260101-000000-aaa000", ledger)


if __name__ == "__main__":
    unittest.main()
