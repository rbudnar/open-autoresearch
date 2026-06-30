#!/usr/bin/env python3
"""regenerate_state.py — rebuild the derived aggregates from the record set.

The derived files are pure functions of ``state/ledger/*.json`` plus the
single-writer ``state/campaign.json``. They are git-ignored; this script
rebuilds them idempotently and writes each atomically (temp file + os.replace),
never relying on mtime for staleness.

Outputs (all under state/):
  - experiment_ledger.jsonl  records sorted by id, one canonical line each
  - research_tree.json       topology (parent_ids) + node content/state +
                             operational views + campaign metadata
  - val_exposure.json        derived: queries (+ exposure_budget and
                             holdout_refresh_due when metrics.yaml is present);
                             no hand prose
  - INDEX.md                 human/agent-facing digest table

Usage
-----
    python3 regenerate_state.py --state-dir state/
"""

from __future__ import annotations

import argparse
import heapq
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from _ledger_common import (
        LIFECYCLE_STATUSES,
        NODE_TYPES,
        PROMOTION_STATUSES,
        _canonical_record_bytes,
        resolve_val_queries,
    )
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _ledger_common import (
        LIFECYCLE_STATUSES,
        NODE_TYPES,
        PROMOTION_STATUSES,
        _canonical_record_bytes,
        resolve_val_queries,
    )

BASELINE_SENTINEL = "baseline"
_LIFECYCLE_SET = set(LIFECYCLE_STATUSES)
_PROMOTION_SET = set(PROMOTION_STATUSES)
_NODE_TYPE_SET = set(NODE_TYPES)
_FRONTIER_LIFECYCLE = {"proposed", "pending"}
_CLOSED_LIFECYCLE = {"blocked", "pruned", "merged"}
_PROMOTION_CANDIDATE_STATUSES = {
    "level1_branch_winner",
    "level2_branch_winner",
    "branch_winner",
    "promotion_candidate",
}


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".tmp-", suffix=path.name
    )
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
        try:
            with path.open("r", encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # Mirror validate_ledger.load_records: a malformed/non-UTF8/unreadable
            # shard is skipped (with a warning) rather than crashing the
            # regeneration. validate_ledger.py is the surface that FAILS on such a
            # shard.
            sys.stderr.write(
                f"WARNING: skipping malformed ledger shard {path.name}: {exc}\n"
            )
            continue
        if isinstance(obj, dict):
            records.append(obj)
    # Sort by id for deterministic output.
    records.sort(key=lambda r: str(r.get("id", "")))
    return records


def load_campaign(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "campaign.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Consistent with load_records' skip-with-warning: an unreadable,
        # non-UTF-8, or malformed campaign.json degrades to no campaign metadata
        # rather than crashing the regeneration with a traceback.
        sys.stderr.write(
            f"WARNING: campaign.json not readable/parseable ({exc}); "
            f"proceeding with no campaign metadata\n"
        )
        return {}
    return obj if isinstance(obj, dict) else {}


def host_root_from_state_dir(state_dir: Path) -> Path:
    """Resolve the host repo root from the state dir.

    Project-level data splits live at ``<host>/data/splits`` (PROTOCOL §6.3.1),
    which is NOT the state dir's parent: in a real install the state dir is
    ``<host>/autoresearch/state`` (the vendored scaffold sits under
    ``autoresearch/``), so the host root is two levels up. The flat example layout
    (``<root>/state``, no ``autoresearch/`` wrapper) puts it one level up. The
    ``autoresearch`` directory name is the documented, deterministic marker (config
    under ``autoresearch/`` is read the same way at ``state_dir.parent/config``).

    ``state_dir`` is resolved to an absolute path first so the documented relative
    invocation (``--state-dir state/`` run from ``<host>/autoresearch``) sees the
    real ``autoresearch`` parent rather than ``Path('state').parent == '.'``.
    """
    state_dir = state_dir.resolve()
    if state_dir.parent.name == "autoresearch":
        return state_dir.parent.parent
    return state_dir.parent


def read_manifest_val_set_version(state_dir: Path) -> "int | str | None":
    """The split MANIFEST (``data/splits/MANIFEST.json``, §6.3.1) is the source of
    truth for ``val_set_version`` (PROTOCOL §17.6.3): a holdout refresh bumps it
    there. Prefer it over ``campaign.json`` so derived exposure state reflects the
    refresh instead of a stale runtime mirror. Returns None when there is no
    manifest / no usable value, so callers use ``campaign.json`` (back-compat).
    """
    manifest_path = (
        host_root_from_state_dir(state_dir) / "data" / "splits" / "MANIFEST.json"
    )
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # A non-UTF-8 MANIFEST.json raises UnicodeDecodeError during read_text;
        # treat it like an unreadable/malformed manifest (no usable value).
        return None
    if isinstance(data, dict):
        vsv = data.get("val_set_version")
        if isinstance(vsv, bool):
            return None
        if isinstance(vsv, int):
            return vsv
        # Align with the schema's non-empty requirement: a blank string label is
        # not a usable val_set_version, fall back to campaign.json.
        if isinstance(vsv, str) and vsv.strip():
            return vsv
    return None


def build_ledger_jsonl(records: list[dict[str, Any]]) -> bytes:
    """One canonical line per record, sorted by id, trailing newline per line."""
    parts: list[bytes] = []
    for rec in records:
        parts.append(_canonical_record_bytes(rec))
        parts.append(b"\n")
    return b"".join(parts)


def read_exposure_budget(state_dir: Path) -> int | None:
    """Read the top-level ``val_set_exposure_budget`` (§17.6) from metrics.yaml.

    Stdlib-only (no PyYAML dependency, matching the rest of the ledger tools):
    scans the sibling ``config/metrics.yaml`` (else ``metrics.yaml.example``) for
    the first top-level (unindented) ``val_set_exposure_budget: <int>`` line.
    Returns ``None`` if no metrics file exists, the key is absent, or its value
    is not an integer (e.g. an unfilled ``<FILL_ME>`` placeholder).
    """
    config_dir = state_dir.parent / "config"
    for name in ("metrics.yaml", "metrics.yaml.example"):
        path = config_dir / name
        if not path.is_file():
            continue
        # An unreadable (OSError) or non-UTF-8 (UnicodeDecodeError) metrics file
        # yields no budget rather than crashing regeneration with a traceback.
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        for raw in text.splitlines():
            # Top-level key only: no leading whitespace, no comment line.
            if raw.startswith("val_set_exposure_budget:"):
                value = raw.split(":", 1)[1].split("#", 1)[0].strip()
                try:
                    return int(value)
                except ValueError:
                    return None
        return None
    return None


def build_val_exposure(
    records: list[dict[str, Any]],
    campaign: dict[str, Any],
    exposure_budget: int | None = None,
    manifest_val_set_version: "int | str | None" = None,
) -> dict[str, Any]:
    """Derived val-exposure aggregate (PROTOCOL §17.6).

    Derived fields: ``queries`` (sum of per-record val-query inputs), and — when
    a budget is available from metrics.yaml — ``exposure_budget`` and the boolean
    ``holdout_refresh_due`` (queries >= exposure_budget). No hand prose / no
    ``notes`` / ``last_incremented_by_iteration`` (F-rule: derived only).

    ``val_set_version`` prefers the split MANIFEST (§6.3.1 source of truth) when
    the caller resolves one, falling back to ``campaign.json`` for back-compat.
    """
    total = sum(resolve_val_queries(rec) for rec in records)
    val_set_version = (
        manifest_val_set_version
        if manifest_val_set_version is not None
        else campaign.get("val_set_version", 1)
    )
    out: dict[str, Any] = {
        "protocol_version": campaign.get("protocol_version", _detect_pv(records)),
        "val_set_version": val_set_version,
        "queries": total,
    }
    if exposure_budget is not None:
        out["exposure_budget"] = exposure_budget
        out["holdout_refresh_due"] = total >= exposure_budget
    return out


def _detect_pv(records: list[dict[str, Any]]) -> str:
    for rec in records:
        pv = rec.get("protocol_version")
        if isinstance(pv, str):
            return pv
    return "0.5"


def _record_lifecycle(rec: dict[str, Any]) -> str:
    raw = rec.get("lifecycle_status")
    if isinstance(raw, str) and raw in _LIFECYCLE_SET:
        return raw
    # A ledger record without an explicit lifecycle state is a completed
    # historical observation. Keep legacy status labels as evidence/promotion
    # labels, not lifecycle.
    return "completed"


def _record_promotion_status(rec: dict[str, Any]) -> str:
    raw = rec.get("promotion_status")
    if isinstance(raw, str) and raw in _PROMOTION_SET:
        return raw
    legacy_status = rec.get("status")
    if isinstance(legacy_status, str) and legacy_status in _PROMOTION_SET:
        return legacy_status
    return "none"


def _record_node_type(rec: dict[str, Any]) -> str:
    raw = rec.get("node_type")
    if isinstance(raw, str) and raw in _NODE_TYPE_SET:
        return raw
    if rec.get("status") == "baseline" or rec.get("branch") == "baseline":
        return "baseline"
    return "candidate"


def _record_frontier_eligible(rec: dict[str, Any], lifecycle: str) -> bool:
    raw = rec.get("frontier_eligible")
    if isinstance(raw, bool):
        return raw and lifecycle not in _CLOSED_LIFECYCLE
    return lifecycle in _FRONTIER_LIFECYCLE


def _maturity_bucket(rec: dict[str, Any], promotion_status: str) -> str:
    maturity = rec.get("maturity_level")
    if isinstance(maturity, int) and not isinstance(maturity, bool):
        if maturity <= 1:
            return "level1"
        if maturity == 2:
            return "level2"
        return "level3_plus"
    if promotion_status == "level1_branch_winner":
        return "level1"
    if promotion_status == "level2_branch_winner":
        return "level2"
    if promotion_status in {
        "branch_winner",
        "promotion_candidate",
        "promoted",
        "low_evidence_promoted",
    }:
        return "level3_plus"
    return "unknown"


def _lineage_order(
    nodes: dict[str, Any],
    children: dict[str, list[str]],
    parents_by_id: dict[str, list[str]],
) -> list[str]:
    """Return deterministic parent-before-child order, tolerating bad DAGs."""
    incoming = {rid: len(parents_by_id.get(rid, [])) for rid in nodes}
    ready = [rid for rid, count in incoming.items() if count == 0]
    heapq.heapify(ready)
    queued = set(ready)
    order: list[str] = []
    seen: set[str] = set()

    while ready:
        rid = heapq.heappop(ready)
        queued.discard(rid)
        if rid in seen:
            continue
        seen.add(rid)
        order.append(rid)
        for child in children.get(rid, []):
            incoming[child] = max(0, incoming.get(child, 0) - 1)
            if incoming[child] == 0 and child not in seen and child not in queued:
                heapq.heappush(ready, child)
                queued.add(child)

    # validate_ledger rejects cycles, but regenerate_state should remain a
    # tolerant reader and still emit a deterministic aggregate for inspection.
    for rid in sorted(nodes):
        if rid not in seen:
            order.append(rid)
    return order


def build_research_tree(
    records: list[dict[str, Any]], campaign: dict[str, Any]
) -> dict[str, Any]:
    """Tree = topology + record node fields + operational derived views.

    Node content prefers curated node_title/node_lessons, falling back to the
    record's branch/hypothesis and lessons so the tree is always populated.
    """
    nodes: dict[str, Any] = {}
    children: dict[str, list[str]] = {}
    parents_by_id: dict[str, list[str]] = {}
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
            lessons = (
                rec.get("lessons", []) if isinstance(rec.get("lessons"), list) else []
            )
        parents = rec.get("parent_ids")
        parents = parents if isinstance(parents, list) else []
        parent_ids = [p for p in parents if isinstance(p, str)]
        lifecycle = _record_lifecycle(rec)
        promotion_status = _record_promotion_status(rec)
        node_type = _record_node_type(rec)
        frontier_eligible = _record_frontier_eligible(rec, lifecycle)
        blocked_by = rec.get("blocked_by")
        blocked_by = (
            [b for b in blocked_by if isinstance(b, str)]
            if isinstance(blocked_by, list)
            else []
        )
        nodes[rid] = {
            "id": rid,
            "title": title,
            "branch": rec.get("branch", ""),
            "status": rec.get("status", ""),
            "lifecycle_status": lifecycle,
            "promotion_status": promotion_status,
            "frontier_eligible": frontier_eligible,
            "node_type": node_type,
            "hypothesis": rec.get("hypothesis", ""),
            "parent_ids": parent_ids,
            "lessons": list(lessons),
        }
        if blocked_by:
            nodes[rid]["blocked_by"] = blocked_by
        if isinstance(rec.get("pruned_reason"), str):
            nodes[rid]["pruned_reason"] = rec["pruned_reason"]
        if isinstance(rec.get("merged_into"), str):
            nodes[rid]["merged_into"] = rec["merged_into"]
        children.setdefault(rid, [])

    for rec in records:
        rid = rec.get("id")
        if not isinstance(rid, str):
            continue
        parents = rec.get("parent_ids")
        parents = parents if isinstance(parents, list) else []
        real_parents = [
            p
            for p in parents
            if isinstance(p, str) and p != BASELINE_SENTINEL and p in nodes
        ]
        parents_by_id[rid] = sorted(set(real_parents))
        if not real_parents:
            roots.append(rid)
        for p in real_parents:
            children.setdefault(p, []).append(rid)

    for rid in children:
        children[rid] = sorted(set(children[rid]))

    lineage_order = _lineage_order(nodes, children, parents_by_id)
    records_by_id = {
        rec["id"]: rec
        for rec in records
        if isinstance(rec.get("id"), str)
    }
    promotion_candidates_by_maturity = {
        "level1": [],
        "level2": [],
        "level3_plus": [],
        "unknown": [],
    }
    for rid in lineage_order:
        node = nodes[rid]
        lifecycle = str(node.get("lifecycle_status", "completed"))
        promotion_status = str(node.get("promotion_status", "none"))
        if (
            lifecycle not in _CLOSED_LIFECYCLE
            and promotion_status in _PROMOTION_CANDIDATE_STATUSES
        ):
            promotion_candidates_by_maturity[
                _maturity_bucket(records_by_id.get(rid, {}), promotion_status)
            ].append(rid)

    views: dict[str, Any] = {
        "lineage_order": lineage_order,
        "frontier": [
            rid for rid in lineage_order if nodes[rid].get("frontier_eligible") is True
        ],
        "blocked": [
            {"id": rid, "blocked_by": nodes[rid].get("blocked_by", [])}
            for rid in lineage_order
            if nodes[rid].get("lifecycle_status") == "blocked"
        ],
        "pruned": [
            {"id": rid, "reason": nodes[rid].get("pruned_reason", "")}
            for rid in lineage_order
            if nodes[rid].get("lifecycle_status") == "pruned"
        ],
        "promotion_candidates_by_maturity": promotion_candidates_by_maturity,
        "merged": [
            {"id": rid, "merged_into": nodes[rid].get("merged_into", "")}
            for rid in lineage_order
            if nodes[rid].get("lifecycle_status") == "merged"
        ],
    }

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
        "views": views,
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
    exposure_budget = read_exposure_budget(state_dir)
    manifest_vsv = read_manifest_val_set_version(state_dir)
    val_exposure = build_val_exposure(records, campaign, exposure_budget, manifest_vsv)
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
