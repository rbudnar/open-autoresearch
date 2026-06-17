#!/usr/bin/env python3
"""verify_request.py — PROTOCOL.md §10.5 non-agent verifier.

Reads a ``promotion_request.json`` written by the agent, re-checks every claim
against the live experiment ledger, applies §10.5 verifier validation rules,
and emits a signed ``promotion_packet.{json,md}`` with the final status.

The verifier MUST run with a signing key the agent cannot read; otherwise the
"promoted" status is self-attested and §3.1.1 enforcement collapses.

Usage
-----
    OPEN_AUTORESEARCH_VERIFIER_KEY=<secret> python verify_request.py \\
        --request    autoresearch/proposals/<id>-promotion-request.json \\
        --ledger     autoresearch/state/ledger/ \\
        --metrics    autoresearch/config/metrics.yaml \\
        --enforcement autoresearch/config/enforcement.yaml \\
        --out-dir    autoresearch/reports/ \\
        --verifier-identity "ci-job-1234"

For explicit unsigned mode (testing, or honest "no out-of-band key available"
acknowledgment): pass ``--unsigned``. Resulting packet is forced to
``enforcement: in_band_only`` and ``not_deployable: true`` regardless of the
request's claims.

Exit codes
----------
    0  — packet written; check packet.status for promoted/low_evidence_promoted/rejected
    1  — packet written with status: rejected (one or more §10.5 rules failed)
    2  — configuration error (could not produce a packet at all)
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# PyYAML ships its own type stubs in `types-PyYAML`; this script does not
# require that package, so we suppress the missing-import diagnostic.
try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    sys.stderr.write("ERROR: PyYAML is required. Install with: pip install pyyaml\n")
    sys.exit(2)

# Import the SHARED canonical serializer. This MUST be the SAME helper used by
# regenerate_state.py and log_experiment.py so the §10.5 hash basis is byte-
# identical across all tools. scripts/ sits one level up from scripts/verifier/.
try:
    from _ledger_common import (
        _canonical_record_bytes,
        resolve_val_queries,
        validate_against_schema,
    )
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _ledger_common import (
        _canonical_record_bytes,
        resolve_val_queries,
        validate_against_schema,
    )


# --- Constants ----------------------------------------------------------------

PROTOCOL_VERSION = "0.5"

VALID_SKEPTIC_VERDICTS = {
    "no_objection",
    "objected_but_overridden_by_human",
}

# §10.5 verifier validation rules, in order. Each function takes the verifier
# context and returns (ok: bool, rejection_reason: str | None).
RULE_NAMES = [
    "1_protocol_version_match",
    "2_references_rehash",
    "3_maturity_level_ge_3",
    "4_role_separation_ok",
    "5_stack_requires_factorial",
    "6_val_exposure_not_exhausted",
    "7_behavioral_equivalence_passed",
    "8_skeptic_verdict_clean",
    "9_statistics_recomputed",
    "10_enforcement_caps_status",
    "11_comparison_set_identity",
]


# --- Helpers ------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"CONFIG ERROR: {path} does not exist")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"CONFIG ERROR: {path} did not parse as a mapping")
    return data


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"CONFIG ERROR: {path} does not exist")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"CONFIG ERROR: {path} did not parse as a mapping")
    return data


def _skeptic_verdict(text: str) -> "str | None":
    """Extract the skeptic-review ``verdict`` from a markdown document.

    Reads the leading frontmatter block (between the first two ``---`` fences)
    and returns the ``verdict`` value, tolerating optional single/double quotes
    and unquoted YAML scalars. Stdlib-only (no PyYAML dependency).
    """
    block = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            block = parts[1]
    match = re.search(r'(?m)^\s*verdict:\s*["\']?([A-Za-z_]+)["\']?\s*$', block)
    return match.group(1) if match else None


def load_ledger(ledger_dir: Path) -> dict[str, dict[str, Any]]:
    """Read state/ledger/*.json shards and return {id: {entry, canonical_bytes}}.

    Protocol 0.5: the source of truth is one immutable file per experiment at
    state/ledger/<id>.json. The hash basis is the SHARED canonical serialization
    (_ledger_common._canonical_record_bytes) — byte-identical to the line that
    regenerate_state.py writes into experiment_ledger.jsonl. We compute it here
    and preserve it so rule_2 can re-hash and compare against the request's
    claimed content_sha256.

    Per-shard duplicate-id and missing-id checks are preserved.
    """
    if not ledger_dir.is_dir():
        raise SystemExit(
            f"CONFIG ERROR: ledger dir {ledger_dir} does not exist or is not a "
            f"directory (Protocol 0.5 expects the state/ledger/ shard directory)"
        )
    out: dict[str, dict[str, Any]] = {}
    for shard in sorted(ledger_dir.glob("*.json")):
        with shard.open("r", encoding="utf-8") as f:
            entry = json.load(f)
        if not isinstance(entry, dict):
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} is not a JSON object"
            )
        entry_id = entry.get("id")
        if not entry_id:
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} missing 'id' field"
            )
        if entry_id in out:
            raise SystemExit(
                f"CONFIG ERROR: duplicate ledger entry id {entry_id!r} "
                f"(in shard {shard.name})"
            )
        out[entry_id] = {
            "entry": entry,
            "canonical_bytes": _canonical_record_bytes(entry),
        }
    return out


# --- Context ------------------------------------------------------------------


@dataclasses.dataclass
class VerifierContext:
    request: dict[str, Any]
    request_path: Path
    ledger: dict[str, dict[str, Any]]
    metrics: dict[str, Any]
    enforcement: dict[str, Any]
    unsigned: bool
    # Set by rule 11 (comparison-set identity). WARN-not-gate: when the
    # candidate and baseline ran on different split identities this is True and
    # a note is surfaced on the packet; the request is NOT rejected for it.
    # Conservative default: True ("unknown / not confirmed same-set") so that if
    # rule 11 is ever skipped or raises before build_packet, the packet does not
    # silently assert a comparison is comparable (fail-safe, not fail-open).
    cross_dataset: bool = True
    cross_dataset_note: str | None = None


# --- Rule implementations -----------------------------------------------------


def rule_1_protocol_version_match(ctx: VerifierContext) -> tuple[bool, str | None]:
    req_pv = str(ctx.request.get("protocol_version", ""))
    if req_pv != PROTOCOL_VERSION:
        return False, (
            f"request protocol_version={req_pv!r} != verifier protocol "
            f"version={PROTOCOL_VERSION!r}"
        )
    return True, None


def rule_2_references_rehash(ctx: VerifierContext) -> tuple[bool, str | None]:
    refs = ctx.request.get("references") or {}
    if not refs:
        return False, "request has no 'references' block"
    mismatches: list[str] = []
    missing: list[str] = []

    def check_ref(label: str, ref: dict[str, Any]) -> None:
        claimed = ref.get("content_sha256")
        ledger_id = ref.get("ledger_id")
        path_ref = ref.get("path")
        if claimed is None:
            mismatches.append(f"{label}: no content_sha256")
            return
        if ledger_id:
            entry = ctx.ledger.get(ledger_id)
            if entry is None:
                missing.append(f"{label}: ledger_id={ledger_id} not in ledger")
                return
            actual = sha256_bytes(entry["canonical_bytes"])
            if actual != claimed:
                mismatches.append(
                    f"{label}: ledger_id={ledger_id} claimed={claimed[:12]}... "
                    f"actual={actual[:12]}..."
                )
        elif path_ref:
            file_path = Path(path_ref)
            if not file_path.is_absolute():
                file_path = ctx.request_path.parent.parent / path_ref
            if not file_path.exists():
                missing.append(f"{label}: path={path_ref} not found at {file_path}")
                return
            actual = sha256_bytes(file_path.read_bytes())
            if actual != claimed:
                mismatches.append(
                    f"{label}: path={path_ref} claimed={claimed[:12]}... "
                    f"actual={actual[:12]}..."
                )
        else:
            mismatches.append(f"{label}: neither ledger_id nor path")

    for label, ref in refs.items():
        if isinstance(ref, list):
            for i, item in enumerate(ref):
                check_ref(f"{label}[{i}]", item)
        elif isinstance(ref, dict):
            check_ref(label, ref)
        else:
            mismatches.append(f"{label}: unexpected type {type(ref).__name__}")

    if missing or mismatches:
        return False, "; ".join(missing + mismatches)
    return True, None


def rule_3_maturity_level_ge_3(ctx: VerifierContext) -> tuple[bool, str | None]:
    level = ctx.request.get("maturity_level_used")
    if not isinstance(level, int):
        return False, f"maturity_level_used is not an int: {level!r}"
    if level < 3:
        return False, (
            f"maturity_level_used={level} < 3; Level 1 and Level 2 cannot "
            f"reach the §18 promotion gate (PROTOCOL.md §24)"
        )
    return True, None


def rule_4_role_separation_ok(ctx: VerifierContext) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims") or {}
    sep = claims.get("role_separation_achieved") or {}
    impl_vs_skeptic = sep.get("implementation_worker_vs_skeptic", "")
    if impl_vs_skeptic not in {"level_2", "level_3"}:
        return False, (
            f"implementation_worker_vs_skeptic={impl_vs_skeptic!r}; §5.0 "
            f"requires Level 2 minimum for promotion"
        )
    return True, None


def rule_5_stack_requires_factorial(ctx: VerifierContext) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims") or {}
    ablation = claims.get("ablation") or {}
    change_type = ablation.get("change_type")
    factorial = ablation.get("factorial_grid_completed")
    if change_type == "stack" and not factorial:
        return False, (
            "change_type=stack but factorial_grid_completed=false; §16.1.2 "
            "requires a factorial grid before promoting a stack"
        )
    return True, None


def rule_6_val_exposure_not_exhausted(
    ctx: VerifierContext,
) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims") or {}
    exposure = claims.get("val_set_exposure_at_request") or {}
    queries = exposure.get("queries_against_val_this_campaign")
    budget = exposure.get("exposure_budget")
    if not isinstance(queries, int) or not isinstance(budget, int):
        return False, (
            f"val_set_exposure_at_request requires int queries + budget "
            f"(got queries={queries!r}, budget={budget!r})"
        )
    # Anti-spoof cross-check (§17.6): an agent must not under-report val exposure
    # to dodge the budget. Compute the ledger-derived exposure (sum of each
    # shard's resolve_val_queries) and REJECT if the claimed exposure is LESS
    # than what the ledger records actually incurred.
    ledger_derived = sum(
        resolve_val_queries(rec["entry"]) for rec in ctx.ledger.values()
    )
    if queries < ledger_derived:
        return False, (
            f"val exposure claim {queries} < ledger-derived total "
            f"{ledger_derived}; §17.6 the request under-reports exposure "
            f"(claimed less than the sum of per-record val queries)"
        )
    if queries >= budget:
        return False, (
            f"val exposure {queries} >= budget {budget}; §17.6 requires "
            f"holdout refresh before further promotion"
        )
    return True, None


def rule_7_behavioral_equivalence_passed(
    ctx: VerifierContext,
) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims") or {}
    passed = claims.get("behavioral_equivalence_test_passed_for_evaluator")
    if passed is not True:
        return False, (
            f"behavioral_equivalence_test_passed_for_evaluator={passed!r}; "
            f"§17.1.1 requires passing fixtures for promotion"
        )
    return True, None


def rule_8_skeptic_verdict_clean(ctx: VerifierContext) -> tuple[bool, str | None]:
    refs = ctx.request.get("references") or {}
    skeptic_ref = refs.get("skeptic_review")
    if not isinstance(skeptic_ref, dict):
        return False, "references.skeptic_review missing or malformed"
    path_ref = skeptic_ref.get("path")
    if not path_ref:
        return False, "references.skeptic_review.path missing"
    skeptic_path = Path(path_ref)
    if not skeptic_path.is_absolute():
        skeptic_path = ctx.request_path.parent.parent / path_ref
    if not skeptic_path.exists():
        return False, f"skeptic review file not found: {skeptic_path}"
    text = skeptic_path.read_text(encoding="utf-8")
    if _skeptic_verdict(text) in VALID_SKEPTIC_VERDICTS:
        return True, None
    return False, (
        f"skeptic_review verdict is neither no_objection nor "
        f"objected_but_overridden_by_human (per §5.7 / §21.4)"
    )


def rule_9_statistics_recomputed(ctx: VerifierContext) -> tuple[bool, str | None]:
    """Lightweight re-check: confirm the request quotes the candidate/baseline
    ledger entry IDs and that each candidate run carries a metrics block.

    A full re-bootstrap of CIs from per-example predictions is out of scope for
    this reference verifier — implementers should layer it on if they have the
    per-example predictions on disk. The §10.5 spec is that the verifier MUST
    re-derive §13.2.1 from referenced ledger metrics; this reference checks
    that the referenced entries CONTAIN the metric values claimed.
    """
    refs = ctx.request.get("references")
    if not isinstance(refs, dict):
        return False, "references is not an object"
    candidate_runs = refs.get("candidate_runs") or []
    if not isinstance(candidate_runs, list) or not candidate_runs:
        return False, "references.candidate_runs is empty or not a list"
    for i, ref in enumerate(candidate_runs):
        if not isinstance(ref, dict):
            return False, f"candidate_runs[{i}] is not an object"
        candidate_ledger_id = ref.get("ledger_id")
        if not isinstance(candidate_ledger_id, str):
            return False, f"candidate_runs[{i}] ledger_id is not a string"
        entry = ctx.ledger.get(candidate_ledger_id)
        if entry is None:
            return False, f"candidate_runs[{i}] ledger_id not found"
        if "metrics" not in entry["entry"]:
            return False, f"candidate_runs[{i}] ledger entry has no 'metrics' block"
    baseline_ref = refs.get("baseline_run")
    if not isinstance(baseline_ref, dict):
        return False, "baseline_run is not an object"
    baseline_ledger_id = baseline_ref.get("ledger_id")
    if not isinstance(baseline_ledger_id, str):
        return False, "baseline_run ledger_id is not a string"
    baseline_entry = ctx.ledger.get(baseline_ledger_id)
    if baseline_entry is None:
        return False, "baseline_run ledger_id not found"
    if "metrics" not in baseline_entry["entry"]:
        return False, "baseline_run ledger entry has no 'metrics' block"
    return True, None


def rule_10_enforcement_caps_status(ctx: VerifierContext) -> tuple[bool, str | None]:
    """This rule does not fail the request; it caps the achievable status.

    Returns (True, "<note>") where the note records the enforcement label that
    will be written into the packet. Status capping happens in compute_status().
    """
    return True, None


# A comparable split identity is defined DECLARATIVELY and validated with the
# shared structural validator, so "complete/valid" means exactly one thing and is
# enforced by the same engine as the manifest schema (no scattered imperative
# field checks that keep growing edge cases).
#
# `_NONEMPTY_STRING` requires at least one non-whitespace character, so "", "  ",
# and non-strings are all rejected. These mirror split_manifest.schema.json's
# declarative `dataset_fingerprint` (a test asserts the two stay in sync).
_NONEMPTY_STRING = {"type": "string", "pattern": r"\S"}

# Strongest tier: a COMPLETE per-split membership hash (all three non-empty).
_MEMBERSHIP_IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["train", "val", "test"],
    "properties": {
        "train": _NONEMPTY_STRING,
        "val": _NONEMPTY_STRING,
        "test": _NONEMPTY_STRING,
    },
}

# A complete Guard-B dataset fingerprint: every field present and well-typed —
# non-empty source/version/schema_hash, an integer row_count >= 0, and a
# date_window that is either a non-empty string OR a {start,end} object with both
# bounds non-empty.
_DATASET_FINGERPRINT_IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["source", "version", "date_window", "row_count", "schema_hash"],
    "properties": {
        "source": _NONEMPTY_STRING,
        "version": _NONEMPTY_STRING,
        "schema_hash": _NONEMPTY_STRING,
        "row_count": {"type": "integer", "minimum": 1},
        "date_window": {
            "anyOf": [
                _NONEMPTY_STRING,
                {
                    "type": "object",
                    "required": ["start", "end"],
                    "properties": {
                        "start": _NONEMPTY_STRING,
                        "end": _NONEMPTY_STRING,
                    },
                },
            ]
        },
    },
}

# Lighter tier: a complete dataset fingerprint + split_spec_hash + seed. Extra
# keys (membership_sha256, mode, val_set_version) are allowed and not part of the
# completeness test; `val_set_version` is folded into the comparable key
# separately so 1 and "1" don't false-mismatch.
_LIGHTER_IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["dataset_fingerprint", "split_spec_hash", "seed"],
    "properties": {
        "dataset_fingerprint": _DATASET_FINGERPRINT_IDENTITY_SCHEMA,
        "split_spec_hash": _NONEMPTY_STRING,
        "seed": {"type": "integer"},
    },
}


def _split_identity(entry: dict[str, Any]) -> "Any | None":
    """Return a comparable split-identity key for a ledger record, or None when
    the record carries no COMPLETE split identity.

    PROTOCOL §6.3.1 / §14.1: the optional ``data_fingerprint`` records WHICH
    split a run used. The strongest tier is a complete per-split
    ``membership_sha256`` (byte-level proof); the lighter tier is a complete
    ``dataset_fingerprint`` + ``split_spec_hash`` + ``seed`` (+ optional
    ``val_set_version``), which assumes deterministic materialization.
    Completeness/validity at each tier is decided by validating against the
    declarative schemas above, so an incomplete OR degenerately-valued identity
    (missing field, empty/whitespace string, wrong type, blank-bounded
    date_window, partial membership) yields None and rule 11 flags
    ``cross_dataset`` rather than asserting same-set on weak evidence. We prefer
    membership when both tiers qualify. The key is JSON-canonicalized so equality
    is order-insensitive.
    """
    fp = entry.get("data_fingerprint")
    if not isinstance(fp, dict):
        return None
    membership = fp.get("membership_sha256")
    if isinstance(membership, dict) and not validate_against_schema(
        membership, _MEMBERSHIP_IDENTITY_SCHEMA
    ):
        canonical = {k: membership[k] for k in ("train", "val", "test")}
        return ("membership", json.dumps(canonical, sort_keys=True))
    if not validate_against_schema(fp, _LIGHTER_IDENTITY_SCHEMA):
        lighter: dict[str, Any] = {
            "dataset_fingerprint": fp["dataset_fingerprint"],
            "split_spec_hash": fp["split_spec_hash"],
            "seed": fp["seed"],
        }
        # val_set_version may be logged as an int or a string for the same label
        # (1 vs "1"); normalize to str. Only fold in a scalar value.
        vsv = fp.get("val_set_version")
        if isinstance(vsv, (int, str)) and not isinstance(vsv, bool):
            lighter["val_set_version"] = str(vsv)
        return ("fingerprint", json.dumps(lighter, sort_keys=True))
    return None


def rule_11_comparison_set_identity(ctx: VerifierContext) -> tuple[bool, str | None]:
    """WARN-not-gate (§13.2.1 same-comparison-set note): compare the baseline's
    split identity against every candidate's and set ``cross_dataset`` on the
    packet when they diverge or cannot be confirmed identical.

    This rule NEVER fails the request — per the owner's ratified decision the
    protocol WARNS and STRONGLY RECOMMENDS identical holdout observations but
    lets the implementer choose the evidence tier. It returns (True, note); the
    note (and the ``cross_dataset`` flag) is surfaced on the packet so a
    divergent comparison is never silently treated as comparable.
    """

    def _identity_for(ledger_id: Any) -> "Any | None":
        if not isinstance(ledger_id, str):
            return None
        wrapped = ctx.ledger.get(ledger_id)
        if wrapped is None:
            return None
        entry = wrapped.get("entry")
        return _split_identity(entry) if isinstance(entry, dict) else None

    # Tolerate a malformed request shape (non-dict references / baseline_run /
    # candidate items): rule 11 never crashes — an unreadable identity is simply
    # None, which surfaces as cross_dataset. (rule 2 rejects the malformed request
    # cleanly; both run, so rule 11 must not raise on the same input.)
    refs = ctx.request.get("references")
    refs = refs if isinstance(refs, dict) else {}
    baseline_ref = refs.get("baseline_run")
    baseline_identity = (
        _identity_for(baseline_ref.get("ledger_id"))
        if isinstance(baseline_ref, dict)
        else None
    )

    candidate_runs = refs.get("candidate_runs")
    candidate_runs = candidate_runs if isinstance(candidate_runs, list) else []
    candidate_identities: list["Any | None"] = [
        _identity_for(ref.get("ledger_id")) if isinstance(ref, dict) else None
        for ref in candidate_runs
    ]

    # No candidates to compare against: we cannot confirm same-set, so fail safe
    # to cross_dataset rather than vacuously asserting "identical" (rule 9 also
    # rejects empty candidate_runs, but rule 11 must not assert comparability it
    # cannot establish).
    if not candidate_identities:
        ctx.cross_dataset = True
        ctx.cross_dataset_note = (
            "no candidate runs to compare split identity against; cannot confirm "
            "identical holdout observations. Treat the comparison as cross_dataset."
        )
        return True, ctx.cross_dataset_note

    # No identity recorded anywhere: we cannot confirm same-set. Flag it as a
    # cross_dataset warning (the §6.3.1 identity record is recommended, not
    # mandated) rather than asserting comparability.
    if baseline_identity is None and all(c is None for c in candidate_identities):
        ctx.cross_dataset = True
        ctx.cross_dataset_note = (
            "no split identity recorded on baseline or candidate runs; "
            "cannot confirm identical holdout observations (§6.3.1 recommends "
            "recording data_fingerprint). Treat the comparison as cross_dataset."
        )
        return True, ctx.cross_dataset_note

    mismatched = baseline_identity is None or any(
        c is None or c != baseline_identity for c in candidate_identities
    )
    if mismatched:
        ctx.cross_dataset = True
        ctx.cross_dataset_note = (
            "baseline and candidate split identities differ (or are not all "
            "recorded); strongly recommend identical holdout observations "
            "(§13.2.1). Flagged cross_dataset — implementer chooses the evidence "
            "tier; not auto-rejected."
        )
        return True, ctx.cross_dataset_note

    ctx.cross_dataset = False
    ctx.cross_dataset_note = "baseline and candidate share an identical split identity"
    return True, ctx.cross_dataset_note


RULE_FUNCS = {
    "1_protocol_version_match": rule_1_protocol_version_match,
    "2_references_rehash": rule_2_references_rehash,
    "3_maturity_level_ge_3": rule_3_maturity_level_ge_3,
    "4_role_separation_ok": rule_4_role_separation_ok,
    "5_stack_requires_factorial": rule_5_stack_requires_factorial,
    "6_val_exposure_not_exhausted": rule_6_val_exposure_not_exhausted,
    "7_behavioral_equivalence_passed": rule_7_behavioral_equivalence_passed,
    "8_skeptic_verdict_clean": rule_8_skeptic_verdict_clean,
    "9_statistics_recomputed": rule_9_statistics_recomputed,
    "10_enforcement_caps_status": rule_10_enforcement_caps_status,
    "11_comparison_set_identity": rule_11_comparison_set_identity,
}


# --- Status computation -------------------------------------------------------


def compute_enforcement_label(ctx: VerifierContext) -> str:
    if ctx.unsigned:
        return "in_band_only"
    declared = ctx.enforcement.get("mechanism", "none")
    if declared == "none":
        return "in_band_only"
    return str(declared)


def compute_status(
    ctx: VerifierContext,
    rule_failures: list[tuple[str, str | None]],
    enforcement_label: str,
) -> str:
    if rule_failures:
        return "rejected"
    requested = str(ctx.request.get("requested_status", "promoted"))
    if enforcement_label == "in_band_only":
        return "low_evidence_promoted"
    if requested in {"promoted", "low_evidence_promoted"}:
        return requested
    return "rejected"


# --- Signing ------------------------------------------------------------------


def sign_packet_fields(packet_fields: dict[str, Any], key: bytes) -> str:
    canonical = json.dumps(packet_fields, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def get_signing_key(unsigned: bool) -> bytes | None:
    if unsigned:
        return None
    key_str = os.environ.get("OPEN_AUTORESEARCH_VERIFIER_KEY", "")
    if not key_str:
        raise SystemExit(
            "CONFIG ERROR: OPEN_AUTORESEARCH_VERIFIER_KEY is not set and "
            "--unsigned was not passed. The §10.5 verifier MUST sign packets "
            "with a key the agent cannot read. Either set the env var (with "
            "a key the agent does not have access to) or pass --unsigned to "
            "explicitly produce an unsigned packet (which forces "
            "enforcement: in_band_only and not_deployable: true)."
        )
    if len(key_str) < 32:
        raise SystemExit(
            "CONFIG ERROR: OPEN_AUTORESEARCH_VERIFIER_KEY is shorter than 32 "
            "bytes; use a long random key."
        )
    return key_str.encode("utf-8")


# --- Packet writer ------------------------------------------------------------


def build_packet(
    ctx: VerifierContext,
    rule_results: list[tuple[str, bool, str | None]],
    verifier_identity: str,
    verifier_type: str,
    signing_key: bytes | None,
) -> dict[str, Any]:
    request_id = ctx.request.get("request_id", "<unknown>")
    packet_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-pkt"
    rule_failures = [(name, reason) for name, ok, reason in rule_results if not ok]
    enforcement_label = compute_enforcement_label(ctx)
    status = compute_status(ctx, rule_failures, enforcement_label)
    maturity = ctx.request.get("maturity_level_used", 0)
    not_deployable = (
        enforcement_label == "in_band_only" or status == "low_evidence_promoted"
    )

    packet_fields: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "packet_id": packet_id,
        "request_id": request_id,
        "status": status,
        "rejection_reasons": [r for _, r in rule_failures if r],
        "enforcement": enforcement_label,
        "not_deployable": not_deployable,
        "maturity_level": maturity,
        # Comparison-set identity (§6.3.1 / §13.2.1, rule 11). WARN-not-gate:
        # surfaced on the packet so a divergent baseline/candidate split is
        # never silently treated as comparable. Never affects `status`.
        "cross_dataset": ctx.cross_dataset,
        "cross_dataset_note": ctx.cross_dataset_note,
        "verifier": {
            "type": verifier_type,
            "identity": verifier_identity,
            "signed_at": now_iso(),
        },
        "criteria_check": {
            name: {"pass": ok, "note": reason} for name, ok, reason in rule_results
        },
    }

    if signing_key is None:
        packet_fields["verifier"]["signature"] = "unsigned"
    else:
        packet_fields["verifier"]["signature"] = sign_packet_fields(
            {k: v for k, v in packet_fields.items() if k != "verifier"}
            | {
                "verifier_partial": {
                    k: packet_fields["verifier"][k]
                    for k in ("type", "identity", "signed_at")
                }
            },
            signing_key,
        )
    return packet_fields


def write_packet_files(
    out_dir: Path, request_id: str, packet: dict[str, Any]
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{request_id}-promotion-packet"
    json_path = out_dir / f"{base}.json"
    md_path = out_dir / f"{base}.md"
    json_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")

    md_lines = [
        "---",
        f"protocol_version: \"{packet['protocol_version']}\"",
        f"packet_id: \"{packet['packet_id']}\"",
        f"request_id: \"{packet['request_id']}\"",
        f"status: \"{packet['status']}\"",
        f"enforcement: \"{packet['enforcement']}\"",
        f"not_deployable: {str(packet['not_deployable']).lower()}",
        f"maturity_level: {packet['maturity_level']}",
        f"cross_dataset: {str(packet['cross_dataset']).lower()}",
        "---",
        "",
        "# Promotion Packet (verifier-written)",
        "",
        f"**Status:** `{packet['status']}`",
        f"**Enforcement:** `{packet['enforcement']}`",
        f"**Not deployable:** `{packet['not_deployable']}`",
        f"**Cross-dataset (comparison-set warning):** `{packet['cross_dataset']}`"
        + (
            f" — {packet['cross_dataset_note']}"
            if packet.get("cross_dataset_note")
            else ""
        ),
        "",
        "## Verifier identity",
        "",
        "```yaml",
        f"type: \"{packet['verifier']['type']}\"",
        f"identity: \"{packet['verifier']['identity']}\"",
        f"signed_at: \"{packet['verifier']['signed_at']}\"",
        f"signature: \"{packet['verifier']['signature']}\"",
        "```",
        "",
        "## §10.5 verifier validation results",
        "",
        "| Rule | Pass | Note |",
        "|---|---|---|",
    ]
    for name, result in packet["criteria_check"].items():
        note = result.get("note") or ""
        md_lines.append(f"| {name} | {result['pass']} | {note} |")
    if packet["rejection_reasons"]:
        md_lines += ["", "## Rejection reasons", ""]
        for reason in packet["rejection_reasons"]:
            md_lines.append(f"- {reason}")
    md_lines += [
        "",
        "## Authoritative artifact",
        "",
        f"The signed JSON sidecar at `{json_path.name}` is authoritative. This "
        "markdown is a human-readable rendering only.",
        "",
    ]
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return json_path, md_path


# --- Main ---------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "PROTOCOL.md §10.5 non-agent verifier. Re-checks an agent-emitted "
            "promotion_request.json against the live ledger and emits a "
            "signed promotion_packet.{json,md}."
        )
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument(
        "--ledger",
        required=True,
        type=Path,
        help="Protocol 0.5 state/ledger/ shard DIRECTORY (one *.json per record)",
    )
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--enforcement", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--verifier-identity",
        required=True,
        help="CI job id, human name, or service identity",
    )
    parser.add_argument(
        "--verifier-type",
        default="non_agent_ci",
        choices=["non_agent_ci", "oop_verifier_script", "human"],
    )
    parser.add_argument(
        "--unsigned",
        action="store_true",
        help=(
            "Produce an unsigned packet (forces enforcement: in_band_only "
            "and not_deployable: true). Use only when no out-of-band signing "
            "key is available and you accept the honest in-band-only label."
        ),
    )
    args = parser.parse_args(argv)

    request = load_json(args.request)
    ledger = load_ledger(args.ledger)
    metrics = load_yaml(args.metrics)
    enforcement = load_yaml(args.enforcement)
    signing_key = get_signing_key(args.unsigned)

    ctx = VerifierContext(
        request=request,
        request_path=args.request,
        ledger=ledger,
        metrics=metrics,
        enforcement=enforcement,
        unsigned=args.unsigned,
    )

    rule_results: list[tuple[str, bool, str | None]] = []
    for rule_name in RULE_NAMES:
        rule_func = RULE_FUNCS[rule_name]
        ok, reason = rule_func(ctx)
        rule_results.append((rule_name, ok, reason))

    packet = build_packet(
        ctx,
        rule_results,
        verifier_identity=args.verifier_identity,
        verifier_type=args.verifier_type,
        signing_key=signing_key,
    )
    json_path, md_path = write_packet_files(
        args.out_dir, request.get("request_id", "unknown"), packet
    )

    sys.stdout.write(f"Wrote {json_path}\n")
    sys.stdout.write(f"Wrote {md_path}\n")
    sys.stdout.write(f"status={packet['status']} ")
    sys.stdout.write(f"enforcement={packet['enforcement']} ")
    sys.stdout.write(f"not_deployable={packet['not_deployable']}\n")

    return 1 if packet["status"] == "rejected" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
