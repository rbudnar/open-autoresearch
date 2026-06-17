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
DEFAULT_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schema"
    / ("experiment_record.schema.json")
)


def load_records(ledger_dir: Path) -> list[tuple[Path, Any]]:
    """Return [(path, parsed_or_None)] for every *.json in ledger_dir, sorted."""
    records: list[tuple[Path, Any]] = []
    for path in sorted(ledger_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                records.append((path, json.load(f)))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # UnicodeDecodeError (a ValueError, not an OSError) covers a non-UTF8
            # shard — report it as a malformed record rather than crashing.
            records.append((path, None))
    return records


def validate(ledger_dir: Path, schema_path: Path) -> tuple[bool, list[str]]:
    try:
        schema = load_schema(schema_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return False, [f"FAIL schema not loadable: {schema_path}: {exc}"]
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
            # The filename stem MUST equal the internal id: the shard path is the
            # addressable name of the record, and regenerate_state / the verifier
            # key shards by id. A stem!=id mismatch means the file could be loaded
            # under one name but rehashed/referenced under another.
            if path.stem != rid:
                record_errors.append(
                    f"filename stem {path.stem!r} != internal id {rid!r}"
                )

        # parent_ids resolution.
        parent_ids = obj.get("parent_ids") if isinstance(obj, dict) else None
        if isinstance(parent_ids, list):
            for pid in parent_ids:
                if not isinstance(pid, str):
                    record_errors.append(
                        f"parent_id {pid!r} is not a string"
                    )
                    continue
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

    # parent_ids CYCLE detection. A cyclic parent graph is not a valid DAG: it
    # has no roots, so regenerate_state would emit roots:[] and the lineage is
    # uninterpretable. Build the id -> parent_ids adjacency (real ids only, drop
    # the baseline sentinel) and DFS for a back edge.
    graph: dict[str, list[str]] = {}
    for path, obj in records:
        if isinstance(obj, dict):
            rid = obj.get("id")
            if isinstance(rid, str):
                parents = obj.get("parent_ids") or []
                graph[rid] = [
                    p
                    for p in parents
                    if isinstance(p, str) and p != BASELINE_SENTINEL and p in all_ids
                ]

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {rid: WHITE for rid in graph}
    cycle_nodes: list[str] = []

    def _visit(node: str, stack: list[str]) -> bool:
        color[node] = GRAY
        stack.append(node)
        for parent in graph.get(node, []):
            if color.get(parent) == GRAY:
                idx = stack.index(parent)
                cycle_nodes.extend(stack[idx:] + [parent])
                return True
            if color.get(parent) == WHITE and _visit(parent, stack):
                return True
        stack.pop()
        color[node] = BLACK
        return False

    for rid in sorted(graph):
        if color[rid] == WHITE and _visit(rid, []):
            break

    if cycle_nodes:
        ok_overall = False
        lines.append("FAIL parent_ids cycle detected: " + " -> ".join(cycle_nodes))

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
