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
import math
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
        is_safe_filename_stem,
        load_schema,
        resolve_val_queries,
        validate_against_schema,
        validate_tree_fields,
    )
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _ledger_common import (
        _canonical_record_bytes,
        is_safe_filename_stem,
        load_schema,
        resolve_val_queries,
        validate_against_schema,
        validate_tree_fields,
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
    # An unreadable (OSError), non-UTF-8 (UnicodeDecodeError), or malformed
    # (yaml.YAMLError) config file is a clean CONFIG ERROR, never a traceback.
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(f"CONFIG ERROR: {path} not readable/parseable: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"CONFIG ERROR: {path} did not parse as a mapping")
    return data


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"CONFIG ERROR: {path} does not exist")
    # An unreadable (OSError), non-UTF-8 (UnicodeDecodeError), or malformed
    # (json.JSONDecodeError) file is a clean CONFIG ERROR, never a traceback.
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"CONFIG ERROR: {path} not readable/parseable: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"CONFIG ERROR: {path} did not parse as a mapping")
    return data


def _is_int(value: Any) -> bool:
    """True iff ``value`` is a real int (bool excluded). ``bool`` is an ``int``
    subclass, so a JSON ``true``/``false`` would otherwise satisfy
    ``isinstance(x, int)`` and let a boolean masquerade as an integer count/level
    in the promotion rules. Single predicate so every rule's int check agrees."""
    return isinstance(value, int) and not isinstance(value, bool)


# The §3.1.1 out-of-band enforcement mechanisms the verifier recognizes. The
# enforcement label (and therefore deployability) is derived from this value, so
# an UNRECOGNIZED or non-string mechanism must FAIL CLOSED (rejected as a config
# error) — treating any truthy value as real enforcement would let a malformed
# enforcement.yaml mint a deployable `promoted` packet. Kept in lock-step with
# template/config/enforcement.yaml.example.
VALID_ENFORCEMENT_MECHANISMS = frozenset(
    {"ci_enforced", "pre_receive", "oop_verifier", "container_ro", "none"}
)


def _malformed_exposure_field(entry: dict[str, Any]) -> "str | None":
    """Return a description if ``entry`` carries a PRESENT-but-malformed
    val-exposure field (non-int, bool, or negative), else ``None``.

    resolve_val_queries() resolves a malformed/absent field to 0; that is right
    for ABSENT, but a PRESENT-but-malformed field (e.g. ``"100"`` or ``-5``) must
    REJECT in the verifier — silently treating it as 0 under-reports the §17.6
    ledger-derived exposure and lets a request slip under the holdout budget."""
    direct = entry.get("val_queries_incurred_by_this_run")
    if direct is not None and not (_is_int(direct) and direct >= 0):
        return f"val_queries_incurred_by_this_run={direct!r}"
    metrics = entry.get("metrics")
    if isinstance(metrics, dict):
        nested = metrics.get("validation_set_queries")
        if nested is not None and not (_is_int(nested) and nested >= 0):
            return f"metrics.validation_set_queries={nested!r}"
    return None


# experiment_record.schema.json lives under schema/ — a sibling of scripts/ in
# both the template (template/schema/) and host (autoresearch/schema/) layouts.
# The verifier is the promotion GATE, so it must not sign a deployable packet
# from referenced ledger evidence that the repo's own schema (and
# validate_ledger.py) would reject.
_RECORD_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "schema"
    / "experiment_record.schema.json"
)


def _load_record_schema() -> "dict[str, Any] | None":
    """Load experiment_record.schema.json, or None if it cannot be loaded."""
    try:
        return load_schema(_RECORD_SCHEMA_PATH)
    except (ValueError, OSError):
        return None


def _is_finite_number(value: Any) -> bool:
    """True iff ``value`` is a finite int/float (bool excluded) — a usable
    metric value for the §13.2.1 comparison."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _resolve_reference_path(ctx: "VerifierContext", path_ref: str) -> "Path | None":
    """Resolve a request reference path against the campaign root
    (``request_path.parent.parent``) and confirm it stays INSIDE that root.

    Returns the resolved ``Path``, or ``None`` if ``path_ref`` is absolute or
    escapes the root (``..`` / symlink). Referenced evidence (skeptic review,
    rehashed artifacts) MUST live inside the auditable campaign tree — otherwise
    an agent can satisfy the verifier's hash/skeptic gates with an artifact
    outside the tree (a path-traversal / evidence-boundary bypass).

    The root is the OPERATOR-controlled campaign_root (from --ledger) when set;
    deriving it from the agent-influenceable --request location would let a
    shallow request path (e.g. /tmp/req.json -> root '/') expand the boundary.
    Falls back to request_path.parent.parent only in unit tests."""
    base = ctx.campaign_root if ctx.campaign_root is not None else ctx.request_path.parent.parent
    root = base.resolve()
    candidate = Path(path_ref)
    if candidate.is_absolute():
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


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
        # The open() itself is INSIDE the guard: an unreadable shard (OSError —
        # permission denied, transient FS, is-a-directory) is as much a clean
        # CONFIG ERROR as a non-UTF-8 (UnicodeDecodeError) or malformed
        # (json.JSONDecodeError) one, never a traceback.
        try:
            with shard.open("r", encoding="utf-8") as f:
                entry = json.load(f)
        except OSError as exc:
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} not readable: {exc}"
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} is not valid JSON: {exc}"
            )
        if not isinstance(entry, dict):
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} is not a JSON object"
            )
        entry_id = entry.get("id")
        if not entry_id:
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} missing 'id' field"
            )
        if not isinstance(entry_id, str):
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} 'id' is not a string"
            )
        # The shard filename stem MUST equal the internal id — validate_ledger.py
        # enforces this invariant, and the verifier must not promote from ledger
        # state the repo's own validator rejects. A mismatch indicates tampered /
        # mislabeled ledger state, so fail closed at load.
        if shard.stem != entry_id:
            raise SystemExit(
                f"CONFIG ERROR: ledger shard {shard.name} filename stem "
                f"{shard.stem!r} != internal id {entry_id!r}"
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
    # The campaign root that bounds path references (skeptic review, rehashed
    # artifacts). Derived in main() from the OPERATOR-controlled --ledger
    # (<campaign>/state/ledger -> <campaign>), NOT from the agent-influenceable
    # --request location: a shallow request path must not be able to expand the
    # evidence boundary. None only in unit tests, where _resolve_reference_path
    # falls back to request_path.parent.parent.
    campaign_root: "Path | None" = None
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
    refs = ctx.request.get("references")
    if not isinstance(refs, dict):
        return False, "references is not an object/mapping"
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
        if not isinstance(claimed, str):
            mismatches.append(f"{label}: content_sha256 is not a string")
            return
        # ledger_id keys ctx.ledger (a dict): an unhashable list/dict from an
        # untrusted request would crash `.get(ledger_id)` with `TypeError:
        # unhashable type`. Guard the type the way rule 9 does so a malformed
        # ledger_id is a clean mismatch, not a traceback.
        if ledger_id is not None and not isinstance(ledger_id, str):
            mismatches.append(f"{label}: ledger_id is not a string")
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
            if not isinstance(path_ref, str):
                mismatches.append(f"{label}: path is not a string")
                return
            file_path = _resolve_reference_path(ctx, path_ref)
            if file_path is None:
                mismatches.append(
                    f"{label}: path={path_ref} is absolute or escapes the "
                    f"campaign root"
                )
                return
            if not file_path.exists():
                missing.append(f"{label}: path={path_ref} not found at {file_path}")
                return
            # An OSError mid-read (after the .exists() check — a race, a
            # permission flip, or is-a-directory) is recorded as a missing ref,
            # not raised: a referenced file we cannot read fails the check
            # cleanly rather than crashing the verifier.
            try:
                contents = file_path.read_bytes()
            except OSError as exc:
                missing.append(f"{label}: path {path_ref} not readable: {exc}")
                return
            actual = sha256_bytes(contents)
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
                if not isinstance(item, dict):
                    mismatches.append(f"{label}[{i}]: not an object")
                    continue
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
    if not _is_int(level):
        return False, f"maturity_level_used is not an int: {level!r}"
    if level < 3:
        return False, (
            f"maturity_level_used={level} < 3; Level 1 and Level 2 cannot "
            f"reach the §18 promotion gate (PROTOCOL.md §24)"
        )
    return True, None


def rule_4_role_separation_ok(ctx: VerifierContext) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims")
    claims = claims if isinstance(claims, dict) else {}
    sep = claims.get("role_separation_achieved")
    sep = sep if isinstance(sep, dict) else {}
    impl_vs_skeptic = sep.get("implementation_worker_vs_skeptic", "")
    # Guard the type before the set-membership test: a non-string (unhashable
    # list/dict from an untrusted request) can never be a valid level label, and
    # `x in {…}` would otherwise raise on an unhashable value.
    if not isinstance(impl_vs_skeptic, str) or impl_vs_skeptic not in {
        "level_2",
        "level_3",
    }:
        return False, (
            f"implementation_worker_vs_skeptic={impl_vs_skeptic!r}; §5.0 "
            f"requires Level 2 minimum for promotion"
        )
    return True, None


def rule_5_stack_requires_factorial(ctx: VerifierContext) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims")
    claims = claims if isinstance(claims, dict) else {}
    ablation = claims.get("ablation")
    ablation = ablation if isinstance(ablation, dict) else {}
    change_type = ablation.get("change_type")
    factorial = ablation.get("factorial_grid_completed")
    # Require the boolean True, not merely a truthy value: a string "false"
    # (or any non-bool) would otherwise satisfy `not factorial == False` and let
    # a stack change skip the §16.1.2 factorial-grid evidence. Mirrors rule 7's
    # `passed is not True` gate.
    if change_type == "stack" and factorial is not True:
        return False, (
            f"change_type=stack but factorial_grid_completed is not true "
            f"(got {factorial!r}); §16.1.2 requires a factorial grid before "
            f"promoting a stack"
        )
    return True, None


def rule_6_val_exposure_not_exhausted(
    ctx: VerifierContext,
) -> tuple[bool, str | None]:
    claims = ctx.request.get("claims")
    claims = claims if isinstance(claims, dict) else {}
    exposure = claims.get("val_set_exposure_at_request")
    exposure = exposure if isinstance(exposure, dict) else {}
    queries = exposure.get("queries_against_val_this_campaign")
    budget = exposure.get("exposure_budget")
    # _is_int excludes bool: a JSON `true`/`false` is an int subclass and would
    # otherwise satisfy the type check, letting `queries=false, budget=true`
    # (i.e. 0 and 1) pass rule 6 and reach a deployable `promoted` packet.
    if not _is_int(queries) or not _is_int(budget):
        return False, (
            f"val_set_exposure_at_request requires int queries + budget "
            f"(got queries={queries!r}, budget={budget!r})"
        )
    # Exposure counts/budgets are non-negative by definition; a negative value is
    # a malformed claim, not a license to skip the budget comparison.
    if queries < 0 or budget < 0:
        return False, (
            f"val_set_exposure_at_request queries/budget must be non-negative "
            f"(got queries={queries}, budget={budget})"
        )
    # Anti-spoof cross-check (§17.6): an agent must not under-report val exposure
    # to dodge the budget. Compute the ledger-derived exposure (sum of each
    # shard's resolve_val_queries) and REJECT if the claimed exposure is LESS
    # than what the ledger records actually incurred. A PRESENT-but-malformed
    # exposure field in any shard is rejected up front rather than silently
    # resolving to 0 (which would under-report the total and bypass the budget).
    ledger_derived = 0
    for rec in ctx.ledger.values():
        entry = rec.get("entry") if isinstance(rec, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        bad = _malformed_exposure_field(entry)
        if bad is not None:
            return False, (
                f"ledger shard carries a malformed val-exposure field ({bad}); "
                f"refusing to treat it as zero (§17.6 anti-spoof)"
            )
        ledger_derived += resolve_val_queries(entry)
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
    claims = ctx.request.get("claims")
    claims = claims if isinstance(claims, dict) else {}
    passed = claims.get("behavioral_equivalence_test_passed_for_evaluator")
    if passed is not True:
        return False, (
            f"behavioral_equivalence_test_passed_for_evaluator={passed!r}; "
            f"§17.1.1 requires passing fixtures for promotion"
        )
    return True, None


def rule_8_skeptic_verdict_clean(ctx: VerifierContext) -> tuple[bool, str | None]:
    refs = ctx.request.get("references")
    refs = refs if isinstance(refs, dict) else {}
    skeptic_ref = refs.get("skeptic_review")
    if not isinstance(skeptic_ref, dict):
        return False, "references.skeptic_review missing or malformed"
    path_ref = skeptic_ref.get("path")
    if not path_ref:
        return False, "references.skeptic_review.path missing"
    if not isinstance(path_ref, str):
        return False, "references.skeptic_review.path is not a string"
    skeptic_path = _resolve_reference_path(ctx, path_ref)
    if skeptic_path is None:
        return False, (
            "references.skeptic_review.path is absolute or escapes the campaign "
            "root"
        )
    if not skeptic_path.exists():
        return False, f"skeptic review file not found: {skeptic_path}"
    # An unreadable (OSError) or non-UTF-8 (UnicodeDecodeError) skeptic-review
    # file fails the rule cleanly, never as a traceback.
    try:
        text = skeptic_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False, "references.skeptic_review.path not readable/decodable"
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
    # §18 (promotion evidence) requires a baseline RERUN and at least one
    # ablation, in addition to the candidate + baseline above. Without this an
    # otherwise-valid request that simply OMITS this evidence could mint a
    # deployable `promoted` packet. We require presence + a string ledger_id
    # here; rule 2 rehashes each reference's content_sha256 against the ledger
    # (catching a missing/altered shard), so this is a presence gate, not a
    # second integrity pass.
    baseline_rerun = refs.get("baseline_rerun")
    if not isinstance(baseline_rerun, dict) or not isinstance(
        baseline_rerun.get("ledger_id"), str
    ):
        return False, (
            "references.baseline_rerun missing or has no string ledger_id "
            "(§18 requires a baseline rerun before promotion)"
        )
    ablation_runs = refs.get("ablation_runs")
    if not isinstance(ablation_runs, list) or not ablation_runs:
        return False, (
            "references.ablation_runs is empty or not a list "
            "(§18 requires at least one ablation before promotion)"
        )
    for i, ablation_ref in enumerate(ablation_runs):
        if not isinstance(ablation_ref, dict) or not isinstance(
            ablation_ref.get("ledger_id"), str
        ):
            return False, (
                f"ablation_runs[{i}] is not an object with a string ledger_id"
            )

    # §18 evidence must be INDEPENDENT records, not aliases of already-accepted
    # baseline/candidate shards — otherwise the rerun/ablation gates are
    # satisfiable by reusing existing evidence. baseline_rerun must not BE the
    # baseline shard; each ablation must be distinct from the baseline, every
    # candidate, the baseline_rerun, and the other ablations. NOTE:
    # baseline_rerun MAY equal a candidate — the canonical level3 example records
    # the candidate metrics and the baseline-rerun-under-new-evaluator data in
    # one shard, so a strict baseline_rerun != candidate rule would wrongly
    # reject it.
    candidate_ids = [r["ledger_id"] for r in candidate_runs]
    rerun_id = baseline_rerun["ledger_id"]
    if rerun_id == baseline_ledger_id:
        return False, (
            "references.baseline_rerun aliases baseline_run; a baseline rerun "
            "must be an independent record (§18)"
        )
    forbidden_for_ablation = {baseline_ledger_id, rerun_id, *candidate_ids}
    seen_ablations: set[str] = set()
    for i, ablation_ref in enumerate(ablation_runs):
        aid = ablation_ref["ledger_id"]
        if aid in forbidden_for_ablation or aid in seen_ablations:
            return False, (
                f"ablation_runs[{i}] ledger_id {aid!r} aliases other evidence "
                f"(baseline / candidate / baseline_rerun / another ablation); "
                f"ablations must be independent records (§18)"
            )
        seen_ablations.add(aid)

    # The verifier must not mint a deployable packet from ledger evidence that
    # the repo's own validator (validate_ledger.py) would reject, nor from
    # metric-empty evidence. (a) Validate every referenced shard against
    # experiment_record.schema.json. (b) Require the configured primary metric to
    # be present and FINITE on the candidate + baseline evidence used for the
    # §13.2.1 comparison — rule 9's mandate is "the referenced entries CONTAIN
    # the metric values claimed", and `metrics: {}` contains none.
    schema = _load_record_schema()
    if schema is None:
        return False, (
            "cannot load experiment_record.schema.json to validate referenced "
            "ledger evidence"
        )
    referenced: list[tuple[str, str]] = [("baseline_run", baseline_ledger_id)]
    referenced += [
        (f"candidate_runs[{i}]", r["ledger_id"]) for i, r in enumerate(candidate_runs)
    ]
    referenced.append(("baseline_rerun", baseline_rerun["ledger_id"]))
    referenced += [
        (f"ablation_runs[{i}]", r["ledger_id"]) for i, r in enumerate(ablation_runs)
    ]
    all_ledger_ids = set(ctx.ledger.keys())
    for label, lid in referenced:
        rec = ctx.ledger.get(lid)
        if rec is None:
            return False, f"{label} ledger_id {lid!r} not found"
        errors = validate_against_schema(rec["entry"], schema)
        if errors:
            return False, f"{label} ledger shard fails schema: {errors[0]}"
        tree_errors = validate_tree_fields(rec["entry"], all_ledger_ids)
        if tree_errors:
            return False, f"{label} ledger shard fails tree validation: {tree_errors[0]}"
        if label.startswith("candidate_runs[") and rec["entry"].get(
            "lifecycle_status"
        ) in {"blocked", "pruned", "merged"}:
            return False, (
                f"{label} lifecycle_status {rec['entry'].get('lifecycle_status')!r} "
                "is closed and cannot be promoted"
            )

    # Primary metric present + finite on candidate + baseline (the §13.2.1
    # comparison evidence). Ablation/rerun shapes vary (factorial_cells etc.), so
    # they are not required to carry the primary metric here.
    # The decision config (metrics.yaml primary_metric) MUST be complete and
    # valid: name (non-empty string), direction (minimize|maximize), and a
    # positive finite minimum_meaningful_delta. A missing/malformed decision
    # config must FAIL CLOSED — silently skipping the §13.2.1 comparison would
    # let a worse candidate promote on a malformed metrics.yaml.
    primary_cfg = (
        ctx.metrics.get("primary_metric") if isinstance(ctx.metrics, dict) else None
    )
    if not isinstance(primary_cfg, dict):
        return False, (
            "metrics.yaml has no primary_metric block; the verifier cannot "
            "re-derive the §13.2.1 decision (fail-closed)"
        )
    primary_name = primary_cfg.get("name")
    if not isinstance(primary_name, str) or not primary_name:
        return False, "primary_metric.name must be a non-empty string"
    direction = primary_cfg.get("direction")
    if direction not in ("minimize", "maximize"):
        return False, (
            f"primary_metric.direction must be 'minimize' or 'maximize' "
            f"(got {direction!r}); the verifier will not skip the §13.2.1 "
            f"comparison and silently promote"
        )
    min_delta = primary_cfg.get("minimum_meaningful_delta")
    if not (_is_finite_number(min_delta) and min_delta > 0):
        return False, (
            f"primary_metric.minimum_meaningful_delta must be a positive finite "
            f"number (got {min_delta!r})"
        )

    def _primary(lid: str) -> Any:
        m = ctx.ledger[lid]["entry"].get("metrics")
        return m.get(primary_name) if isinstance(m, dict) else None

    # Primary metric present + finite on candidate + baseline (the §13.2.1
    # comparison evidence). Ablation/rerun shapes vary, so they are not required
    # to carry the primary metric here.
    primary_evidence = [("baseline_run", baseline_ledger_id)] + [
        (f"candidate_runs[{i}]", r["ledger_id"]) for i, r in enumerate(candidate_runs)
    ]
    for label, lid in primary_evidence:
        if not _is_finite_number(_primary(lid)):
            return False, (
                f"{label} is missing a finite primary metric '{primary_name}' "
                f"(§13.2.1 / §10.5: the verifier re-derives the decision from "
                f"referenced ledger metrics)"
            )

    # §13.2.1 direction check (deterministic, point-estimate): the candidate must
    # actually BEAT the baseline by minimum_meaningful_delta in the configured
    # direction, else a worse (or `failed`) candidate could promote. Full
    # CI/bootstrap/guardrail re-derivation from per-example predictions remains
    # the implementer's job (see the docstring).
    baseline_val = _primary(baseline_ledger_id)
    for i, r in enumerate(candidate_runs):
        cand_val = _primary(r["ledger_id"])
        beats = (
            cand_val <= baseline_val - min_delta
            if direction == "minimize"
            else cand_val >= baseline_val + min_delta
        )
        if not beats:
            return False, (
                f"candidate_runs[{i}] primary metric '{primary_name}'={cand_val} "
                f"does not beat baseline {baseline_val} by "
                f"minimum_meaningful_delta {min_delta} (direction={direction}); "
                f"§13.2.1"
            )
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

# A complete Guard-B dataset fingerprint. The IDENTITY is (source, version,
# date_window) — required — so a growing/forward-moving dataset identified by its
# date range alone qualifies (it cannot pin a stable row_count). row_count and
# schema_hash are OPTIONAL strengtheners: when PRESENT they must be well-typed
# (integer row_count >= 1, non-empty schema_hash) and they fold into the
# comparable identity key, so two runs over the same date_window but a different
# row_count are NOT asserted same-set. Kept in lock-step with the declarative
# dataset_fingerprint branch of split_manifest.schema.json (drift-lock test).
_DATASET_FINGERPRINT_IDENTITY_SCHEMA = {
    "type": "object",
    "required": ["source", "version", "date_window"],
    # additionalProperties: false — a misspelled strengthener key (rowcount /
    # schemaHash) must NOT silently ride along; it fails the identity check so the
    # record is treated as not-comparable (cross_dataset warns) rather than
    # asserting same-set on a malformed fingerprint. Kept in lock-step with the
    # manifest schema's dataset_fingerprint (drift-lock test).
    "additionalProperties": False,
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
    # Coerce maturity to a safe int for the packet. The .md frontmatter
    # interpolates it raw, so an untrusted string like
    # "3\nstatus: promoted\nnot_deployable: false" would inject duplicate YAML
    # keys into the rendered frontmatter (a human/tool parsing the .md would read
    # a rejected request as promoted). rule 3 already rejects a non-int maturity
    # (status=rejected); record 0 here when it is not a clean int.
    maturity = ctx.request.get("maturity_level_used", 0)
    if not _is_int(maturity):
        maturity = 0
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
    # request_id is validated as a safe filename stem in main(); the OSError
    # guards below cover the remaining write failures (unwritable out-dir, full
    # disk) so a packet-write failure is a clean CONFIG ERROR, not a traceback.
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(f"CONFIG ERROR: cannot create output dir {out_dir}: {exc}")
    base = f"{request_id}-promotion-packet"
    json_path = out_dir / f"{base}.json"
    md_path = out_dir / f"{base}.md"
    try:
        json_path.write_text(
            json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8"
        )
    except (OSError, ValueError) as exc:
        # ValueError covers an embedded NUL in the stem; OSError covers a full
        # disk / overlong name. request_id is already stem-validated, so this is
        # defense in depth.
        raise SystemExit(f"CONFIG ERROR: cannot write packet {json_path}: {exc}")

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
    try:
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"CONFIG ERROR: cannot write packet {md_path}: {exc}")
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
    # request_id becomes the packet filename stem (`<id>-promotion-packet.json`).
    # An untrusted id with path separators tracebacks (`a/b` -> missing parent)
    # or escapes --out-dir (`../escaped`). Validate it up front; absent is
    # tolerated (a safe default stem is used downstream).
    if "request_id" in request and not is_safe_filename_stem(request["request_id"]):
        raise SystemExit(
            "CONFIG ERROR: request_id must be a non-empty string usable as a "
            "filename (only [A-Za-z0-9._-], <=200 chars, not '.'/'..'), got "
            f"{request['request_id']!r}"
        )
    ledger = load_ledger(args.ledger)
    metrics = load_yaml(args.metrics)
    enforcement = load_yaml(args.enforcement)
    # The enforcement mechanism gates deployability (compute_enforcement_label /
    # compute_status). An unrecognized or non-string mechanism must fail closed:
    # otherwise a malformed enforcement.yaml (`mechanism: not_real` / `[]`) is
    # treated as real out-of-band enforcement and yields a deployable `promoted`
    # packet. load_yaml already guarantees `enforcement` is a mapping.
    mechanism = enforcement.get("mechanism", "none")
    if not isinstance(mechanism, str) or mechanism not in VALID_ENFORCEMENT_MECHANISMS:
        raise SystemExit(
            "CONFIG ERROR: enforcement.mechanism must be one of "
            f"{sorted(VALID_ENFORCEMENT_MECHANISMS)}, got {mechanism!r}. An "
            "unrecognized mechanism is rejected (fail-closed) so a malformed "
            "config cannot mint a deployable promoted packet."
        )
    signing_key = get_signing_key(args.unsigned)

    # Bound path references to the OPERATOR-controlled campaign root. --ledger is
    # <campaign>/state/ledger, so the campaign root is its grandparent. Using
    # this (rather than the agent-influenceable --request location) prevents a
    # shallow request path from expanding the evidence boundary.
    campaign_root = args.ledger.resolve().parent.parent
    ctx = VerifierContext(
        request=request,
        request_path=args.request,
        ledger=ledger,
        metrics=metrics,
        enforcement=enforcement,
        unsigned=args.unsigned,
        campaign_root=campaign_root,
    )

    rule_results: list[tuple[str, bool, str | None]] = []
    for rule_name in RULE_NAMES:
        rule_func = RULE_FUNCS[rule_name]
        # Defense-in-depth: a rule that raises an UNEXPECTED exception (despite
        # the per-rule input guards) must not escape as a bare traceback with no
        # packet. Convert it into a failed check so the request is rejected and
        # an auditable packet is still written.
        try:
            ok, reason = rule_func(ctx)
        except Exception as exc:  # noqa: BLE001 - last-resort verifier backstop
            # Include the exception TYPE: some exceptions (e.g. a bare
            # KeyError, or an exception with an empty str()) stringify to
            # nothing, which would drop the only diagnostic. type(exc).__name__
            # guarantees the rejection note names what went wrong.
            ok, reason = (
                False,
                f"internal error in {rule_name}: {type(exc).__name__}: {exc}",
            )
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
