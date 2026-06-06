#!/usr/bin/env python3
"""regenerate_state.py — rebuild the derived aggregates from the record set.

The derived files are pure functions of ``state/ledger/*.json`` plus the
single-writer ``state/campaign.json``. They are git-ignored; this script
rebuilds them idempotently and writes each atomically (temp file + os.replace),
never relying on mtime for staleness.

Outputs (all under state/):
  - experiment_ledger.jsonl  records sorted by id, one canonical line each
  - research_tree.json       topology (parent_ids) + node content (records'
                             node_title/node_lessons) + campaign metadata
  - val_exposure.json        derived counter ONLY (queries); no hand prose
  - INDEX.md                 human/agent-facing digest table

Usage
-----
    python3 regenerate_state.py --state-dir state/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from _ledger_common import _canonical_record_bytes, resolve_val_queries
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _ledger_common import _canonical_record_bytes, resolve_val_queries

BASELINE_SENTINEL = "baseline"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def load_records(ledger_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not ledger_dir.is_dir():
        return records
    for path in sorted(ledger_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            records.append(obj)
    # Sort by id for deterministic output.
    records.sort(key=lambda r: str(r.get("id", "")))
    return records


def load_campaign(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "campaign.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj if isinstance(obj, dict) else {}


def build_ledger_jsonl(records: list[dict[str, Any]]) -> bytes:
    """One canonical line per record, sorted by id, trailing newline per line."""
    parts: list[bytes] = []
    for rec in records:
        parts.append(_canonical_record_bytes(rec))
        parts.append(b"\n")
    return b"".join(parts)


def build_val_exposure(
    records: list[dict[str, Any]], campaign: dict[str, Any]
) -> dict[str, Any]:
    """Derived counter ONLY. No notes / last_incremented_by_iteration (F-rule)."""
    total = sum(resolve_val_queries(rec) for rec in records)
    out: dict[str, Any] = {
        "protocol_version": campaign.get("protocol_version", _detect_pv(records)),
        "val_set_version": campaign.get("val_set_version", 1),
        "queries": total,
    }
    return out


def _detect_pv(records: list[dict[str, Any]]) -> str:
    for rec in records:
        pv = rec.get("protocol_version")
        if isinstance(pv, str):
            return pv
    return "0.5"


def build_research_tree(
    records: list[dict[str, Any]], campaign: dict[str, Any]
) -> dict[str, Any]:
    """Tree = topology (parent_ids) + node content (record fields) + campaign meta.

    Node content prefers curated node_title/node_lessons, falling back to the
    record's branch/hypothesis and lessons so the tree is always populated.
    """
    nodes: dict[str, Any] = {}
    children: dict[str, list[str]] = {}
    roots: list[str] = []

    for rec in records:
        rid = rec.get("id")
        if not isinstance(rid, str):
            continue
        title = rec.get("node_title")
        if not isinstance(title, str):
            title = rec.get("branch", "")
        lessons = rec.get("node_lessons")
        if not isinstance(lessons, list):
            lessons = rec.get("lessons", []) if isinstance(rec.get("lessons"), list) else []
        nodes[rid] = {
            "id": rid,
            "title": title,
            "branch": rec.get("branch", ""),
            "status": rec.get("status", ""),
            "hypothesis": rec.get("hypothesis", ""),
            "parent_ids": list(rec.get("parent_ids", []) or []),
            "lessons": list(lessons),
        }
        children.setdefault(rid, [])

    for rec in records:
        rid = rec.get("id")
        if not isinstance(rid, str):
            continue
        parents = rec.get("parent_ids", []) or []
        real_parents = [p for p in parents if p != BASELINE_SENTINEL and p in nodes]
        if not real_parents:
            roots.append(rid)
        for p in real_parents:
            children.setdefault(p, []).append(rid)

    for rid in children:
        children[rid] = sorted(set(children[rid]))

    tree: dict[str, Any] = {
        "protocol_version": campaign.get("protocol_version", _detect_pv(records)),
        "campaign_id": campaign.get("campaign_id"),
        "host_branch": campaign.get("host_branch"),
        "scratch_branch": campaign.get("scratch_branch"),
        "maturity_level": campaign.get("maturity_level"),
        "branch_policy": campaign.get("branch_policy"),
        "root": campaign.get("root"),
        "roots": sorted(roots),
        "nodes": {rid: nodes[rid] for rid in sorted(nodes)},
        "children": {rid: children[rid] for rid in sorted(children)},
    }
    return tree


def build_index_md(
    records: list[dict[str, Any]], campaign: dict[str, Any], val_queries: int
) -> str:
    lines: list[str] = []
    cid = campaign.get("campaign_id")
    lines.append("# Experiment Ledger Index (derived — do not edit)")
    lines.append("")
    if cid:
        lines.append(f"**Campaign:** `{cid}`")
    lines.append(f"**Records:** {len(records)}")
    lines.append(f"**Validation queries (derived):** {val_queries}")
    lines.append("")
    lines.append("| id | branch | status | hypothesis |")
    lines.append("|---|---|---|---|")
    for rec in records:
        rid = str(rec.get("id", ""))
        branch = str(rec.get("branch", "")).replace("|", "\\|")
        status = str(rec.get("status", "")).replace("|", "\\|")
        hyp = str(rec.get("hypothesis", "")).replace("|", "\\|")
        if len(hyp) > 80:
            hyp = hyp[:77] + "..."
        lines.append(f"| `{rid}` | {branch} | {status} | {hyp} |")
    lines.append("")
    return "\n".join(lines)


def regenerate(state_dir: Path) -> dict[str, int]:
    ledger_dir = state_dir / "ledger"
    records = load_records(ledger_dir)
    campaign = load_campaign(state_dir)

    ledger_bytes = build_ledger_jsonl(records)
    val_exposure = build_val_exposure(records, campaign)
    tree = build_research_tree(records, campaign)
    index_md = build_index_md(records, campaign, val_exposure["queries"])

    atomic_write_bytes(state_dir / "experiment_ledger.jsonl", ledger_bytes)
    # Derived JSON written deterministically: sorted keys, pretty, trailing nl.
    atomic_write_text(
        state_dir / "val_exposure.json",
        json.dumps(val_exposure, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    atomic_write_text(
        state_dir / "research_tree.json",
        json.dumps(tree, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    atomic_write_text(state_dir / "INDEX.md", index_md)

    stats = {
        "records": len(records),
        "tree_nodes": len(tree["nodes"]),
        "val_query_sum": val_exposure["queries"],
    }
    return stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    stats = regenerate(args.state_dir)
    sys.stdout.write(
        f"regenerated: records={stats['records']} "
        f"tree_nodes={stats['tree_nodes']} "
        f"val_query_sum={stats['val_query_sum']}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
