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
import os
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
    direct = entry.get("val_queries_incurred_by_this_run")
    if isinstance(direct, bool):
        # bool is an int subclass; a stray True/False is not a query count.
        direct = None
    if isinstance(direct, int):
        return direct

    metrics = entry.get("metrics")
    if isinstance(metrics, dict):
        nested = metrics.get("validation_set_queries")
        if isinstance(nested, bool):
            nested = None
        if isinstance(nested, int):
            return nested

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
# properties, items, pattern, const, enum, additionalProperties (boolean OR
# schema-valued — each extra property validated against the subschema), anyOf.
# It is NOT a complete draft-2020-12 implementation.

_JSON_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def load_schema(schema_path: "os.PathLike[str] | str") -> dict[str, Any]:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                errors.extend(
                    validate_against_schema(item, item_schema, f"{path}[{i}]")
                )

    return errors
