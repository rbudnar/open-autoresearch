#!/usr/bin/env python3
"""migrate_ledger_v04_to_v05.py — split a v0.4 jsonl ledger into v0.5 shards.

Steps:
  1. Read every line of an existing state/experiment_ledger.jsonl with plain
     json.load (Python >= 3.7 preserves field/insertion order), preserving ALL
     fields (no allow-list).
  2. Stamp protocol_version -> "0.5".
  3. Write one state/ledger/<id>.json per record (pretty, field-preserving).
     Refuse to clobber existing shards unless --force.
  4. Reconcile val-exposure: if a prior committed state/val_exposure.json exists,
     set the per-record val-query inputs so the derived counter REPRODUCES the
     prior committed value, then assert equality (fail loudly otherwise).
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
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            if not isinstance(obj, dict):
                raise SystemExit(f"ledger line is not an object: {stripped[:80]!r}")
            records.append(obj)
    return records


def reconcile_val_exposure(
    records: list[dict[str, Any]], prior_committed: int | None
) -> None:
    """Set per-record val-query inputs so the derived counter == prior committed.

    If the per-record sum already equals the prior committed value (or there is
    no prior committed value), nothing changes. Otherwise the *difference* is
    folded into the last record's ``val_queries_incurred_by_this_run`` so the
    documented committed counter is reproduced. Asserts equality at the end.
    """
    if prior_committed is None:
        return
    current_sum = sum(resolve_val_queries(r) for r in records)
    if current_sum == prior_committed:
        return
    if not records:
        raise SystemExit(
            f"cannot reconcile val exposure to {prior_committed} with no records"
        )
    delta = prior_committed - current_sum
    last = records[-1]
    base = resolve_val_queries(last)
    last["val_queries_incurred_by_this_run"] = base + delta

    new_sum = sum(resolve_val_queries(r) for r in records)
    if new_sum != prior_committed:
        raise SystemExit(
            f"val-exposure reconciliation FAILED: derived={new_sum} != "
            f"prior committed={prior_committed}"
        )


def build_campaign(state_dir: Path) -> dict[str, Any]:
    """Build an initial campaign.json from any existing research_tree.json meta."""
    tree_path = state_dir / "research_tree.json"
    campaign: dict[str, Any] = {"protocol_version": NEW_PROTOCOL_VERSION}
    if tree_path.exists():
        try:
            with tree_path.open("r", encoding="utf-8") as f:
                tree = json.load(f)
        except (json.JSONDecodeError, OSError):
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
        except (json.JSONDecodeError, OSError):
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
