#!/usr/bin/env python3
"""_ledger_common.py — shared helpers for the Protocol 0.5 sharded-ledger tools.

Stdlib only. Imported by ``log_experiment.py``, ``regenerate_state.py``,
``validate_ledger.py``, ``migrate_ledger_v04_to_v05.py`` and the §10.5 verifier
(``verifier/verify_request.py``).

The single load-bearing function here is :func:`_canonical_record_bytes`, which
defines the §14.1 / §10.5 hash basis. It MUST be the only place any tool computes
the canonical serialization of a record. See PROTOCOL §14.1:

    json.dumps(entry, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

INSERTION ORDER (no ``sort_keys``), NO trailing newline. ``ensure_ascii=False`` is
mandatory: the protocol stores ``§`` and other non-ASCII characters raw UTF-8.

Portability assumption (explicit): Python >= 3.7, where ``dict`` preserves
insertion order. The whole sharded-ledger design depends on this guarantee.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from typing import Any

# Python >= 3.7 is required: the canonical serializer relies on dict insertion
# order being preserved. 3.6 had it as a CPython implementation detail only.
if sys.version_info < (3, 7):  # pragma: no cover - portability guard
    raise RuntimeError(
        "open-autoresearch ledger tools require Python >= 3.7 "
        "(dict insertion-order guarantee)"
    )


def _canonical_record_bytes(entry: dict[str, Any]) -> bytes:
    """Return the canonical byte serialization of a single experiment record.

    This is THE §10.5 hash basis and THE one-line-per-record jsonl form. It is
    deliberately insertion-order (no ``sort_keys``), compact, UTF-8, and carries
    no trailing newline on the hashed unit.

    Do NOT inline ``json.dumps`` elsewhere for the hash basis — always call this.
    """
    return json.dumps(entry, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def resolve_val_queries(entry: dict[str, Any]) -> int:
    """Resolve the per-record validation-query input.

    VAL-QUERY FIELD RULE (PROTOCOL §17.6): the per-record contribution to the
    derived ``val_exposure.json`` counter is the first present of:

        1. ``val_queries_incurred_by_this_run`` (top level)
        2. ``metrics.validation_set_queries``
        3. ``0``

    A record shape that carries neither field contributes 0. This single rule
    lets one ``regenerate_state.py`` serve both the example record shape
    (``val_queries_incurred_by_this_run``) and the AE record shape
    (``metrics.validation_set_queries``).
    """
    if not isinstance(entry, dict):
        return 0
    direct = entry.get("val_queries_incurred_by_this_run")
    if isinstance(direct, bool):
        # bool is an int subclass; a stray True/False is not a query count.
        direct = None
    if isinstance(direct, int):
        # Clamp negative to 0. A negative count is malformed, and the verifier's
        # §17.6 anti-spoof check sums these (ledger_derived); a negative shard
        # must NOT be able to CANCEL real exposure and slip a request under the
        # budget. (validate_ledger separately flags it via the schema minimum.)
        return max(0, direct)

    metrics = entry.get("metrics")
    if isinstance(metrics, dict):
        nested = metrics.get("validation_set_queries")
        if isinstance(nested, bool):
            nested = None
        if isinstance(nested, int):
            return max(0, nested)

    return 0


def sanitize_slug(raw: str) -> str:
    """Sanitize an arbitrary slug for use in a ``state/ledger/<id>.json`` filename.

    SLUG RULE (PROTOCOL, F5 resolution):

      - lowercase
      - map any char outside ``[a-z0-9-]`` to ``-``
      - collapse repeated ``-``
      - strip leading/trailing ``-``
      - cap at 40 chars (then re-strip trailing ``-``)

    Uniqueness comes from the timestamp + 6-hex prefix, so the slug is cosmetic
    and may be aggressively sanitized. An empty result is allowed (caller emits
    an id with no trailing ``-<slug>``).
    """
    if raw is None:
        return ""
    out_chars: list[str] = []
    for ch in str(raw).lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "-":
            out_chars.append(ch)
        else:
            out_chars.append("-")
    collapsed: list[str] = []
    prev_dash = False
    for ch in out_chars:
        if ch == "-":
            if prev_dash:
                continue
            prev_dash = True
        else:
            prev_dash = False
        collapsed.append(ch)
    slug = "".join(collapsed).strip("-")
    if len(slug) > 40:
        slug = slug[:40].strip("-")
    return slug


# --- Stdlib structural JSON Schema validator ---------------------------------
#
# We deliberately do NOT depend on the pip `jsonschema` package (Driver: stdlib
# only, so non-Python repos can run these scripts). This is a small structural
# validator covering exactly the constructs used by
# experiment_record.schema.json (draft 2020-12 subset): type, required,
# properties, items, pattern, minLength, minimum, maximum, minItems, const, enum,
# additionalProperties (boolean OR schema-valued — each extra property validated
# against the subschema), anyOf. It is NOT a complete draft-2020-12 implementation.

_JSON_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    # json.loads accepts NaN/Infinity by default; a non-finite number must NOT
    # validate (it would freeze a non-deterministic/invalid split rule or metric
    # as "passing"). A Python int can never be non-finite, so only "number"
    # needs the math.isfinite gate.
    "number": (
        lambda v: isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(v)
    ),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


_SAFE_FILENAME_STEM_RE = re.compile(r"[A-Za-z0-9._-]+")

LIFECYCLE_STATUSES = (
    "proposed",
    "pending",
    "running",
    "completed",
    "merged",
    "pruned",
    "blocked",
)

PROMOTION_STATUSES = (
    "none",
    "promising",
    "level1_branch_winner",
    "level2_branch_winner",
    "branch_winner",
    "promotion_candidate",
    "promoted",
    "low_evidence_promoted",
    "rejected",
)

NODE_TYPES = (
    "baseline",
    "candidate",
    "ablation",
    "verifier",
    "admin",
    "counter_example",
)

INSIGHT_CONFIDENCE_LEVELS = ("low", "medium", "high")

INSIGHT_REVIEW_STATUSES = ("draft", "reviewed", "contested", "rejected")

STATUSES_REQUIRING_FAILURE_REASON = ("infra_failed", "budget_truncated")

_CLOSED_LIFECYCLE_STATUSES = {"blocked", "pruned", "merged"}
_BASELINE_SENTINEL = "baseline"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(_nonempty_string(item) for item in value)
    )


def validate_tree_fields(
    entry: dict[str, Any], all_ids: set[str] | None = None
) -> list[str]:
    """Validate optional lifecycle/frontier fields when a record opts into them.

    ``all_ids`` is optional so writers can use the same checks before the full
    ledger exists. When supplied, ``merged_into`` must resolve to a known record
    id; validate_ledger.py passes the complete ledger id set.
    """
    errors: list[str] = []
    rid = entry.get("id")
    lifecycle = entry.get("lifecycle_status")

    if lifecycle == "blocked":
        blockers = entry.get("blocked_by")
        if not (
            isinstance(blockers, list)
            and any(_nonempty_string(blocker) for blocker in blockers)
        ):
            errors.append("lifecycle_status 'blocked' requires non-empty blocked_by")

    if lifecycle == "pruned" and not _nonempty_string(entry.get("pruned_reason")):
        errors.append("lifecycle_status 'pruned' requires pruned_reason")

    merged_into = entry.get("merged_into")
    if lifecycle == "merged" and not _nonempty_string(merged_into):
        errors.append("lifecycle_status 'merged' requires merged_into")
    if _nonempty_string(merged_into):
        if all_ids is not None and merged_into not in all_ids:
            errors.append(f"merged_into {merged_into!r} is not a known id")
        if isinstance(rid, str) and merged_into == rid:
            errors.append("merged_into cannot point to the same record id")

    if (
        entry.get("frontier_eligible") is True
        and isinstance(lifecycle, str)
        and lifecycle in _CLOSED_LIFECYCLE_STATUSES
    ):
        errors.append(
            f"frontier_eligible true conflicts with lifecycle_status {lifecycle!r}"
        )

    return errors


def validate_status_fields(entry: dict[str, Any]) -> list[str]:
    """Validate semantic status side-fields that JSON Schema cannot express."""
    status = entry.get("status")
    if (
        status in STATUSES_REQUIRING_FAILURE_REASON
        and not _nonempty_string(entry.get("failure_reason"))
    ):
        return [f"status {status!r} requires failure_reason"]
    return []


def validate_branch_insights(
    entry: dict[str, Any], all_ids: set[str] | None = None
) -> list[str]:
    """Validate optional propagated branch insights.

    ``branch_insights`` is for lessons that change future branch behavior, not
    local narrative notes. When ``all_ids`` is supplied, every source/review id
    must resolve to a ledger record; ``updates_parent_ids`` may also name the
    baseline sentinel because root constraints can affect the whole campaign.
    """
    errors: list[str] = []
    insights = entry.get("branch_insights")
    if insights is None:
        return errors
    if not isinstance(insights, list):
        return ["branch_insights must be a list"]

    for i, insight in enumerate(insights):
        prefix = f"branch_insights[{i}]"
        if not isinstance(insight, dict):
            errors.append(f"{prefix} must be an object")
            continue

        for field in ("raw_observation", "distilled_insight"):
            if not _nonempty_string(insight.get(field)):
                errors.append(f"{prefix}.{field} must be a non-empty string")

        source_ids = insight.get("source_record_ids")
        if not _nonempty_string_list(source_ids):
            errors.append(f"{prefix}.source_record_ids must be a non-empty string list")
        elif all_ids is not None:
            unknown = [sid for sid in source_ids if sid not in all_ids]
            if unknown:
                errors.append(
                    f"{prefix}.source_record_ids contains unknown id {unknown[0]!r}"
                )

        update_ids = insight.get("updates_parent_ids")
        if not _nonempty_string_list(update_ids):
            errors.append(f"{prefix}.updates_parent_ids must be a non-empty string list")
        elif all_ids is not None:
            unknown_updates = [
                uid
                for uid in update_ids
                if uid != _BASELINE_SENTINEL and uid not in all_ids
            ]
            if unknown_updates:
                errors.append(
                    f"{prefix}.updates_parent_ids contains unknown id "
                    f"{unknown_updates[0]!r}"
                )
        entry_id = entry.get("id")
        if _nonempty_string(entry_id) and isinstance(update_ids, list):
            if entry_id in update_ids:
                errors.append(
                    f"{prefix}.updates_parent_ids must not contain the current "
                    "record id"
                )

        constraint = insight.get("validated_constraint")
        if constraint is not None and not _nonempty_string(constraint):
            errors.append(f"{prefix}.validated_constraint must be a non-empty string")

        invalidated = insight.get("invalidated_ideas")
        if invalidated is not None and not _nonempty_string_list(invalidated):
            errors.append(f"{prefix}.invalidated_ideas must be a non-empty string list")

        if not _nonempty_string(constraint) and not _nonempty_string_list(invalidated):
            errors.append(
                f"{prefix} requires validated_constraint or invalidated_ideas"
            )

        confidence = insight.get("confidence")
        if confidence not in INSIGHT_CONFIDENCE_LEVELS:
            errors.append(
                f"{prefix}.confidence must be one of "
                f"{INSIGHT_CONFIDENCE_LEVELS!r}"
            )

        review_status = insight.get("review_status")
        if review_status is not None and review_status not in INSIGHT_REVIEW_STATUSES:
            errors.append(
                f"{prefix}.review_status must be one of "
                f"{INSIGHT_REVIEW_STATUSES!r}"
            )

        review_ids = insight.get("review_record_ids")
        if review_ids is not None:
            if not _nonempty_string_list(review_ids):
                errors.append(
                    f"{prefix}.review_record_ids must be a non-empty string list"
                )
            elif all_ids is not None:
                unknown_review_ids = [rid for rid in review_ids if rid not in all_ids]
                if unknown_review_ids:
                    errors.append(
                        f"{prefix}.review_record_ids contains unknown id "
                        f"{unknown_review_ids[0]!r}"
                    )

        retirement_signal = insight.get("retirement_signal")
        if retirement_signal is not None and not _nonempty_string(retirement_signal):
            errors.append(f"{prefix}.retirement_signal must be a non-empty string")

    return errors


def is_safe_filename_stem(value: Any, max_length: int = 200) -> bool:
    """True iff ``value`` is safe to use as a SINGLE path component (a packet or
    ledger-shard filename stem).

    Untrusted ids (verifier ``request_id``, legacy v0.4 ledger ``id``) become
    filenames. A value that is not a conservative stem either escapes the target
    dir (path separators, ``..``) or tracebacks at the filesystem boundary:
    an embedded NUL raises ``ValueError: embedded null byte`` and an overlong
    name raises ``OSError: File name too long``. One allowlist closes all of
    those: 1..``max_length`` chars from ``[A-Za-z0-9._-]`` (which excludes path
    separators, NUL/control chars, and whitespace), minus the directory aliases
    ``.``/``..``. ``max_length`` defaults to 200 so the longest derived filename
    (``<stem>-promotion-packet.json``) stays well under the 255-byte limit."""
    if not isinstance(value, str) or value in (".", ".."):
        return False
    if not (1 <= len(value) <= max_length):
        return False
    return _SAFE_FILENAME_STEM_RE.fullmatch(value) is not None


def load_schema(schema_path: "os.PathLike[str] | str") -> dict[str, Any]:
    """Load a JSON Schema document, raising a clean, typed ``ValueError`` on any
    open/read/decode failure.

    Every failure mode of reading an external schema file — ``OSError`` (missing,
    permission denied, is-a-directory), ``UnicodeDecodeError`` (non-UTF-8 bytes),
    and ``json.JSONDecodeError`` (malformed JSON) — is converted into a single
    ``ValueError`` carrying the path and the underlying cause. Callers catch
    ``ValueError`` (or the broader set) and convert it to their own clean-error
    form, so a corrupt/inaccessible schema never surfaces as a raw traceback.
    """
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"schema {schema_path} not loadable: {exc}") from exc


def _check_type(value: Any, type_spec: Any) -> bool:
    if isinstance(type_spec, list):
        return any(_check_type(value, t) for t in type_spec)
    checker = _JSON_TYPE_CHECKS.get(type_spec)
    if checker is None:
        # Unknown type keyword: do not block (forward-compat).
        return True
    return checker(value)


def validate_against_schema(
    instance: Any, schema: dict[str, Any], path: str = "$"
) -> list[str]:
    """Return a list of human-readable validation error strings (empty == valid).

    Structural subset of draft 2020-12. Sufficient for the experiment record
    schema. Recurses into properties / items.
    """
    import re

    errors: list[str] = []

    type_spec = schema.get("type")
    if type_spec is not None and not _check_type(instance, type_spec):
        errors.append(
            f"{path}: expected type {type_spec!r}, got " f"{type(instance).__name__}"
        )
        # If the top-level type is wrong, deeper checks are noise.
        return errors

    if "const" in schema:
        const = schema["const"]
        if instance != const:
            errors.append(f"{path}: value {instance!r} != const {const!r}")

    enum = schema.get("enum")
    if enum is not None and instance not in enum:
        errors.append(f"{path}: value {instance!r} not in enum {enum!r}")

    any_of = schema.get("anyOf")
    if any_of is not None and not any(
        not validate_against_schema(instance, sub, path) for sub in any_of
    ):
        errors.append(
            f"{path}: does not satisfy any of the {len(any_of)} allowed schemas"
        )

    if isinstance(instance, str):
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, instance) is None:
            errors.append(f"{path}: {instance!r} does not match pattern {pattern!r}")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            errors.append(
                f"{path}: string shorter than minLength {min_length} (len {len(instance)})"
            )

    # `minimum`/`maximum` apply to numbers (not bools, which are excluded by the
    # `integer`/`number` type checks above).
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and instance < minimum:
            errors.append(f"{path}: {instance} is less than minimum {minimum}")
        maximum = schema.get("maximum")
        if isinstance(maximum, (int, float)) and instance > maximum:
            errors.append(f"{path}: {instance} is greater than maximum {maximum}")

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in instance:
                errors.extend(
                    validate_against_schema(instance[key], subschema, f"{path}.{key}")
                )
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: additional property {key!r} not allowed")
        elif isinstance(additional, dict):
            # Schema-valued additionalProperties: every property NOT named in
            # `properties` must itself validate against this subschema (e.g. a
            # ratio map whose values must all be numbers). Without this branch
            # the value constraint was silently skipped.
            for key, value in instance.items():
                if key not in props:
                    errors.extend(
                        validate_against_schema(value, additional, f"{path}.{key}")
                    )

    if isinstance(instance, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(instance) < min_items:
            errors.append(
                f"{path}: array shorter than minItems {min_items} (len {len(instance)})"
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(
                    validate_against_schema(item, item_schema, f"{path}[{i}]")
                )

    return errors
