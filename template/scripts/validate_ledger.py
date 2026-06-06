#!/usr/bin/env python3
"""validate_ledger.py — reference validator for the sharded experiment ledger.

Reads exactly one directory: ``state/ledger/`` (no archive, no rotation). Checks
that every record is schema-valid, that ids are unique, and that every
``parent_ids`` entry resolves to another record id or the sentinel ``"baseline"``.

Emits a per-record PASS/FAIL line and a summary count. Exits non-zero on any
violation so CI can gate on it.

Usage
-----
    python3 validate_ledger.py --ledger-dir state/ledger/ \\
        [--schema schema/experiment_record.schema.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow running both as a module and as a bare script.
try:
    from _ledger_common import load_schema, validate_against_schema
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _ledger_common import load_schema, validate_against_schema

BASELINE_SENTINEL = "baseline"

# schema/ sits one level up from scripts/ in the template layout.
DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "schema" / (
    "experiment_record.schema.json"
)


def load_records(ledger_dir: Path) -> list[tuple[Path, Any]]:
    """Return [(path, parsed_or_None)] for every *.json in ledger_dir, sorted."""
    records: list[tuple[Path, Any]] = []
    for path in sorted(ledger_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                records.append((path, json.load(f)))
        except (json.JSONDecodeError, OSError):
            records.append((path, None))
    return records


def validate(ledger_dir: Path, schema_path: Path) -> tuple[bool, list[str]]:
    schema = load_schema(schema_path)
    lines: list[str] = []
    ok_overall = True

    if not ledger_dir.is_dir():
        return False, [f"FAIL ledger dir does not exist: {ledger_dir}"]

    records = load_records(ledger_dir)
    seen_ids: dict[str, Path] = {}
    all_ids: set[str] = set()

    # First pass: collect ids (so parent resolution can see every id).
    for path, obj in records:
        if isinstance(obj, dict):
            rid = obj.get("id")
            if isinstance(rid, str):
                all_ids.add(rid)

    for path, obj in records:
        record_errors: list[str] = []

        if obj is None:
            lines.append(f"FAIL {path.name}: malformed JSON / unreadable")
            ok_overall = False
            continue

        # Schema validation.
        record_errors.extend(validate_against_schema(obj, schema))

        rid = obj.get("id") if isinstance(obj, dict) else None
        if isinstance(rid, str):
            if rid in seen_ids:
                record_errors.append(
                    f"duplicate id {rid!r} (also in {seen_ids[rid].name})"
                )
            else:
                seen_ids[rid] = path

        # parent_ids resolution.
        parent_ids = obj.get("parent_ids") if isinstance(obj, dict) else None
        if isinstance(parent_ids, list):
            for pid in parent_ids:
                if pid == BASELINE_SENTINEL:
                    continue
                if pid not in all_ids:
                    record_errors.append(
                        f"orphan parent_id {pid!r} (not a known id or "
                        f"sentinel {BASELINE_SENTINEL!r})"
                    )

        if record_errors:
            ok_overall = False
            lines.append(f"FAIL {path.name}: " + "; ".join(record_errors))
        else:
            lines.append(f"PASS {path.name}")

    total = len(records)
    failed = sum(1 for line in lines if line.startswith("FAIL"))
    lines.append(
        f"SUMMARY {total - failed}/{total} records valid "
        f"({failed} failed) in {ledger_dir}"
    )
    return ok_overall, lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", required=True, type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args(argv)

    ok, lines = validate(args.ledger_dir, args.schema)
    for line in lines:
        sys.stdout.write(line + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
