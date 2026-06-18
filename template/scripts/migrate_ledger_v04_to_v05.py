#!/usr/bin/env python3
"""migrate_ledger_v04_to_v05.py — split a v0.4 jsonl ledger into v0.5 shards.

Steps:
  1. Read every line of an existing state/experiment_ledger.jsonl with plain
     json.load (Python >= 3.7 preserves field/insertion order), preserving ALL
     fields (no allow-list).
  2. Stamp protocol_version -> "0.5".
  3. Write one state/ledger/<id>.json per record (pretty, field-preserving).
     Refuse to clobber existing shards unless --force.
  4. Verify val-exposure: if a prior committed state/val_exposure.json exists,
     assert that the honest per-record val-query sum REPRODUCES the prior
     committed counter. This is a read-only safety valve — it NEVER mutates a
     record. On mismatch it aborts and tells the operator to reconcile the
     per-record inputs by hand.
  5. Build an initial state/campaign.json from any existing research_tree.json
     metadata.
  6. Regenerate all derived aggregates.

Idempotent: re-running with --force reproduces identical shards + aggregates.

Usage
-----
    python3 migrate_ledger_v04_to_v05.py --state-dir state/ [--force]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from _ledger_common import resolve_val_queries
    from regenerate_state import regenerate
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _ledger_common import resolve_val_queries
    from regenerate_state import regenerate

NEW_PROTOCOL_VERSION = "0.5"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    # encoding="utf-8", errors="strict": a non-UTF-8 file raises
    # UnicodeDecodeError during `for line in f` (iteration-time decode), NOT at
    # json.loads. Wrap the open AND the iteration so both an unreadable file
    # (OSError) and a non-UTF-8 one (UnicodeDecodeError) become a clean
    # SystemExit, never a traceback. The inner json.JSONDecodeError guard keeps
    # its line-level diagnostic.
    try:
        with path.open("r", encoding="utf-8", errors="strict") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError as e:
                    raise SystemExit(
                        f"ledger line is not valid JSON: {stripped[:80]!r} ({e})"
                    )
                if not isinstance(obj, dict):
                    raise SystemExit(f"ledger line is not an object: {stripped[:80]!r}")
                records.append(obj)
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemExit(f"ledger file {path} not readable/decodable: {exc}")
    return records


def reconcile_val_exposure(
    records: list[dict[str, Any]], prior_committed: int | None
) -> None:
    """Verify the honest per-record val-query sum reproduces the prior counter.

    This is a *read-only* safety valve: it NEVER mutates a record. If the honest
    per-record sum of ``resolve_val_queries`` already equals the prior committed
    counter (or there is no prior committed counter), it returns silently.

    If they DISAGREE, it raises ``SystemExit`` with a clear message telling the
    operator to reconcile the per-record inputs by hand. The old behavior — fold
    the entire ``prior - sum`` delta into the last record's
    ``val_queries_incurred_by_this_run`` — silently corrupted that record's
    exposure accounting (and made the closing equality check pass by
    construction so it never fired). A migration must preserve the honest
    per-record exposure inputs, not paper over a discrepancy.
    """
    if prior_committed is None:
        return
    current_sum = sum(resolve_val_queries(r) for r in records)
    if current_sum == prior_committed:
        return
    raise SystemExit(
        "val-exposure reconciliation FAILED: the honest per-record sum of "
        f"resolve_val_queries ({current_sum}) does not match the prior "
        f"committed state/val_exposure.json counter ({prior_committed}). The "
        "migrator will NOT silently fold the difference into any record. "
        "Reconcile the per-record val_queries_incurred_by_this_run (or "
        "metrics.validation_set_queries) inputs by hand so they honestly sum "
        f"to {prior_committed}, then re-run the migration."
    )


def build_campaign(state_dir: Path) -> dict[str, Any]:
    """Build an initial campaign.json from any existing research_tree.json meta."""
    tree_path = state_dir / "research_tree.json"
    campaign: dict[str, Any] = {"protocol_version": NEW_PROTOCOL_VERSION}
    if tree_path.exists():
        try:
            with tree_path.open("r", encoding="utf-8") as f:
                tree = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # A non-UTF-8 (UnicodeDecodeError) research_tree.json is as benign
            # here as an unreadable/malformed one — fall back to no metadata.
            tree = {}
        if isinstance(tree, dict):
            for key in (
                "campaign_id",
                "host_branch",
                "scratch_branch",
                "maturity_level",
                "branch_policy",
                "root",
                "val_set_version",
            ):
                if key in tree:
                    campaign[key] = tree[key]
    return campaign


def migrate(state_dir: Path, force: bool) -> dict[str, Any]:
    ledger_jsonl = state_dir / "experiment_ledger.jsonl"
    if not ledger_jsonl.exists():
        raise SystemExit(f"no source ledger to migrate: {ledger_jsonl}")

    records = read_jsonl(ledger_jsonl)
    for rec in records:
        rec["protocol_version"] = NEW_PROTOCOL_VERSION

    # Reconcile val exposure against any prior committed counter.
    prior_committed: int | None = None
    val_path = state_dir / "val_exposure.json"
    if val_path.exists():
        try:
            with val_path.open("r", encoding="utf-8") as f:
                prior = json.load(f)
            if isinstance(prior, dict) and isinstance(prior.get("queries"), int):
                prior_committed = prior["queries"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # A non-UTF-8 prior val_exposure.json is treated like a malformed or
            # unreadable one: no usable prior counter to reconcile against.
            prior_committed = None
    reconcile_val_exposure(records, prior_committed)

    # Build campaign.json BEFORE we overwrite research_tree.json on regenerate.
    campaign = build_campaign(state_dir)

    ledger_dir = state_dir / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)

    for rec in records:
        rid = rec.get("id")
        if not isinstance(rid, str):
            raise SystemExit(f"record missing string id: {rec!r}")
        # The legacy v0.4 id becomes a shard filename. An id with path separators
        # or `..` (e.g. `../escaped`) would write OUTSIDE state/ledger/ and then
        # be invisible to regenerate()'s `state/ledger/*.json` reload — a silent
        # record drop. Require a single safe path component.
        if rid in ("", ".", "..") or Path(rid).name != rid:
            raise SystemExit(
                f"record id is not a safe shard filename (no path separators "
                f"or '..'): {rid!r}"
            )
        shard = ledger_dir / f"{rid}.json"
        if shard.exists() and not force:
            raise SystemExit(
                f"REFUSING to clobber existing shard {shard} (pass --force)"
            )
        shard.write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    campaign_path = state_dir / "campaign.json"
    if not campaign_path.exists() or force:
        campaign_path.write_text(
            json.dumps(campaign, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    stats = regenerate(state_dir)

    # Final assertion: regenerated counter reproduces the prior committed value.
    if prior_committed is not None and stats["val_query_sum"] != prior_committed:
        raise SystemExit(
            f"post-regenerate val counter {stats['val_query_sum']} != prior "
            f"committed {prior_committed}"
        )
    stats["shards"] = len(records)
    return stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    stats = migrate(args.state_dir, args.force)
    sys.stdout.write(
        f"migrated: shards={stats['shards']} records={stats['records']} "
        f"tree_nodes={stats['tree_nodes']} val_query_sum={stats['val_query_sum']}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
