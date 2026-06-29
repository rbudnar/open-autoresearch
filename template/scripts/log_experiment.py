#!/usr/bin/env python3
"""log_experiment.py — write one immutable experiment record.

Stdlib only. Auto-fills:
  - protocol_version  (from template/PROTOCOL_VERSION)
  - id                (UTC YYYYMMDD-HHMMSS + secrets.token_hex(3) + sanitized slug)
  - timestamp         (UTC ISO-8601)
  - source_commit / source_branch / resolvable_from_main (content-addressed
    provenance Level-1: a NON-AUTHORITATIVE breadcrumb of the commit + branch
    HEAD pointed at, plus whether it is reachable from main. Never a
    reproducibility promise; see docs/proposals/2026-06-13-provenance-redesign.md.)

The deprecated --git-sha-before / --git-sha-after flags are still accepted for
back-compat with host scripts; when given they populate source_commit. New
records never emit git_sha_*.

Back-compat is asymmetric by design: WRITER back-compat (the old flags) is
preserved, but READER back-compat is not — new records carry only the triple, so
consumers that read record["git_sha_after"] must migrate to record["source_commit"]
(and use .get() defensively for mixed old/new ledgers).

Validates the assembled record against the JSON Schema using the stdlib
structural validator (no pip 'jsonschema'). REFUSES to overwrite an existing
state/ledger/<id>.json. Optionally regenerates aggregates with --regenerate.

Usage
-----
    python3 log_experiment.py --state-dir state/ \\
        --branch loss_objective \\
        --hypothesis "ordinal loss improves NLL" \\
        --status promising \\
        --parent 20260518-100000-aaa001 \\
        --slug "ordinal loss!" \\
        [--metrics-json '{"validation_nll":0.83}'] \\
        [--val-queries 3] \\
        [--regenerate]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from _ledger_common import (
        LIFECYCLE_STATUSES,
        NODE_TYPES,
        PROMOTION_STATUSES,
        _canonical_record_bytes,
        load_schema,
        sanitize_slug,
        validate_against_schema,
        validate_tree_fields,
    )
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _ledger_common import (
        LIFECYCLE_STATUSES,
        NODE_TYPES,
        PROMOTION_STATUSES,
        _canonical_record_bytes,
        load_schema,
        sanitize_slug,
        validate_against_schema,
        validate_tree_fields,
    )

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA = _SCRIPT_DIR.parent / "schema" / "experiment_record.schema.json"
DEFAULT_PROTOCOL_VERSION_FILE = _SCRIPT_DIR.parent / "PROTOCOL_VERSION"


def _parse_json_object_arg(raw: str, flag: str) -> dict[str, Any]:
    """Parse a CLI JSON-object flag, failing with a clean ``SystemExit`` (not a
    raw ``JSONDecodeError`` traceback) on malformed input, so all of
    ``--metrics-json`` / ``--dataset-fingerprint`` / ``--membership-hash`` give
    the same friendly error for both malformed-JSON and valid-but-non-object."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag} must be valid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise SystemExit(f"{flag} must be a JSON object")
    return parsed


def read_protocol_version(path: Path) -> str:
    if path.exists():
        # An unreadable (OSError) or non-UTF-8 (UnicodeDecodeError)
        # --protocol-version-file is a clean CONFIG ERROR, never a traceback,
        # matching the rest of this script's file-read contract.
        try:
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise SystemExit(
                f"CONFIG ERROR: --protocol-version-file {path} not "
                f"readable/decodable: {exc}"
            )
    return "0.5"


def _git(repo_dir: Path, *args: str) -> str | None:
    """Run a git command from ``repo_dir``; return stripped stdout, or None on
    failure (non-zero exit, git absent/unreadable, or timeout)."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def git_head_sha(repo_dir: Path) -> str:
    """HEAD of the git worktree CONTAINING ``repo_dir`` (git discovers it by
    walking up from ``repo_dir``), or "unknown" if ``repo_dir`` is inside no
    worktree. Running from a copied scaffold subdir (e.g. ``<host>/autoresearch``,
    the documented layout) therefore records the host repo's commit — not
    "unknown" — while a path outside any repo fails closed."""
    return _git(repo_dir, "rev-parse", "HEAD") or "unknown"


def git_current_branch(repo_dir: Path) -> str:
    """Branch of the worktree containing ``repo_dir`` (see :func:`git_head_sha`);
    "unknown" outside any worktree or on a detached HEAD."""
    branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    # Detached HEAD (CI checkouts, bisect, etc.) yields the literal "HEAD" —
    # that is not a branch, so report it honestly as unknown.
    if not branch or branch == "HEAD":
        return "unknown"
    return branch


def is_resolvable_from_main(repo_dir: Path, sha: str) -> bool:
    """True if ``sha`` is an ancestor of ANY existing main ref.

    Content-addressed-provenance Level-1: the commit pointer is a breadcrumb, so
    we never *resolve* commits to gate validity — we only RECORD whether it is
    reachable from main so unauditability is visible. Checks every candidate ref
    (so a stale ``origin/main`` does not mask a local ``main`` that contains the
    commit) and fails closed to False when no main ref exists, the commit is on
    no main ref, git is unavailable, or ``repo_dir`` is inside no worktree (the
    honest default for off-main/ephemeral-branch experiments)."""
    if not sha or sha == "unknown":
        return False
    for ref in ("origin/main", "main"):
        if _git(repo_dir, "rev-parse", "--verify", "--quiet", ref) is None:
            continue
        # merge-base --is-ancestor exits 0 (-> "") when sha is an ancestor of
        # this ref. Keep scanning the remaining refs on a miss; only conclude
        # False after every existing main ref has been ruled out.
        if _git(repo_dir, "merge-base", "--is-ancestor", sha, ref) is not None:
            return True
    return False


def make_id(now: dt.datetime, slug: str) -> str:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    hexpart = secrets.token_hex(3)
    base = f"{stamp}-{hexpart}"
    clean = sanitize_slug(slug)
    return f"{base}-{clean}" if clean else base


def build_record(args: argparse.Namespace, now: dt.datetime) -> dict[str, Any]:
    protocol_version = read_protocol_version(Path(args.protocol_version_file))
    repo_dir = Path(args.repo_dir)
    # Precedence: explicit --source-commit, then the deprecated --git-sha-*
    # aliases (back-compat for host scripts), then git HEAD.
    source_commit = (
        args.source_commit
        or args.git_sha_after
        or args.git_sha_before
        or git_head_sha(repo_dir)
    )
    source_branch = args.source_branch or git_current_branch(repo_dir)
    resolvable_from_main = is_resolvable_from_main(repo_dir, source_commit)

    record_id = make_id(now, args.slug or args.branch or "")

    metrics: dict[str, Any] = {}
    if args.metrics_json:
        metrics = _parse_json_object_arg(args.metrics_json, "--metrics-json")

    # Insertion order mirrors PROTOCOL §14.1 for canonical-byte stability.
    record: dict[str, Any] = {
        "protocol_version": protocol_version,
        "id": record_id,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": args.branch,
        "hypothesis": args.hypothesis,
        "parent_ids": list(args.parent or []),
        "source_commit": source_commit,
        "source_branch": source_branch,
        "resolvable_from_main": resolvable_from_main,
        "status": args.status,
        "metrics": metrics,
    }
    if args.val_queries is not None:
        # Non-negative at the write boundary: a negative count would later cancel
        # ledger-derived exposure in the §17.6 anti-spoof sum.
        if args.val_queries < 0:
            raise SystemExit(
                f"CONFIG ERROR: --val-queries must be non-negative (got "
                f"{args.val_queries})"
            )
        record["val_queries_incurred_by_this_run"] = args.val_queries
    if args.node_title:
        record["node_title"] = args.node_title
    if args.node_lesson:
        record["node_lessons"] = list(args.node_lesson)
    if args.lifecycle_status:
        record["lifecycle_status"] = args.lifecycle_status
    if args.promotion_status:
        record["promotion_status"] = args.promotion_status
    if args.frontier_eligible is not None:
        record["frontier_eligible"] = args.frontier_eligible
    if args.blocked_by:
        record["blocked_by"] = list(args.blocked_by)
    if args.pruned_reason:
        record["pruned_reason"] = args.pruned_reason
    if args.merged_into:
        record["merged_into"] = args.merged_into
    if args.node_type:
        record["node_type"] = args.node_type
    data_fingerprint = _build_data_fingerprint(args)
    if data_fingerprint:
        record["data_fingerprint"] = data_fingerprint
    return record


def _build_data_fingerprint(args: argparse.Namespace) -> "dict[str, Any] | None":
    """Assemble the OPTIONAL split/dataset identity (§6.3.1 / §14.1).

    Same optional pattern as the provenance breadcrumb: emit ``data_fingerprint``
    only when the caller supplies at least one identity flag. Depth is
    project-chosen — the strongest form carries per-split ``membership_sha256``
    (byte-level proof), the lighter form carries
    ``dataset_fingerprint``/``split_spec_hash``/``seed``. Both are accepted by
    the schema (data_fingerprint is optional and NOT in any anyOf).
    """
    fp: dict[str, Any] = {}
    if args.split_mode:
        fp["mode"] = args.split_mode
    if args.dataset_fingerprint:
        fp["dataset_fingerprint"] = _parse_json_object_arg(
            args.dataset_fingerprint, "--dataset-fingerprint"
        )
    if args.split_spec_hash:
        fp["split_spec_hash"] = args.split_spec_hash
    if args.split_seed is not None:
        fp["seed"] = args.split_seed
    if args.split_val_set_version:
        fp["val_set_version"] = args.split_val_set_version
    if args.membership_hash:
        fp["membership_sha256"] = _parse_json_object_arg(
            args.membership_hash, "--membership-hash"
        )
    return fp or None


def write_record(state_dir: Path, record: dict[str, Any]) -> Path:
    ledger_dir = state_dir / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    out_path = ledger_dir / f"{record['id']}.json"
    if out_path.exists():
        raise SystemExit(f"REFUSING to overwrite existing record: {out_path}")
    # Pretty per-file form for human readability; the canonical compact form is
    # only the jsonl line + hash basis.
    out_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out_path


def load_existing_record_ids(state_dir: Path) -> set[str]:
    """Best-effort id set for lifecycle cross-field validation before write."""
    ledger_dir = state_dir / "ledger"
    ids: set[str] = set()
    if not ledger_dir.is_dir():
        return ids
    for path in ledger_dir.glob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("id"), str):
            ids.add(obj["id"])
    return ids


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--parent", action="append", default=[])
    parser.add_argument("--slug", default="")
    parser.add_argument("--metrics-json", default="")
    parser.add_argument("--val-queries", type=int, default=None)
    parser.add_argument("--node-title", default="")
    parser.add_argument("--node-lesson", action="append", default=[])
    parser.add_argument(
        "--lifecycle-status",
        default="",
        choices=("", *LIFECYCLE_STATUSES),
        help="Optional tree lifecycle state for derived research_tree views.",
    )
    parser.add_argument(
        "--promotion-status",
        default="",
        choices=("", *PROMOTION_STATUSES),
        help="Optional promotion/evidence status separate from lifecycle state.",
    )
    frontier_group = parser.add_mutually_exclusive_group()
    frontier_group.add_argument(
        "--frontier-eligible",
        dest="frontier_eligible",
        action="store_true",
        help="Mark this node as eligible for the derived active frontier view.",
    )
    frontier_group.add_argument(
        "--not-frontier-eligible",
        dest="frontier_eligible",
        action="store_false",
        help="Mark this node as ineligible for the derived active frontier view.",
    )
    parser.set_defaults(frontier_eligible=None)
    parser.add_argument(
        "--blocked-by",
        action="append",
        default=[],
        help="Optional blocker marker for lifecycle_status=blocked.",
    )
    parser.add_argument(
        "--pruned-reason",
        default="",
        help="Optional short reason for lifecycle_status=pruned.",
    )
    parser.add_argument(
        "--merged-into",
        default="",
        help="Optional target record id for lifecycle_status=merged.",
    )
    parser.add_argument(
        "--node-type",
        default="",
        choices=("", *NODE_TYPES),
        help="Optional tree node kind for derived research_tree views.",
    )
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument(
        "--protocol-version-file",
        type=Path,
        default=DEFAULT_PROTOCOL_VERSION_FILE,
    )
    parser.add_argument("--repo-dir", type=Path, default=Path("."))
    parser.add_argument(
        "--source-commit",
        default="",
        help="Override the breadcrumb commit (default: git rev-parse HEAD).",
    )
    parser.add_argument(
        "--source-branch",
        default="",
        help="Override the branch label (default: git current branch).",
    )
    # DEPRECATED back-compat aliases (host scripts): populate source_commit.
    parser.add_argument("--git-sha-before", default="", help=argparse.SUPPRESS)
    parser.add_argument("--git-sha-after", default="", help=argparse.SUPPRESS)
    # OPTIONAL split/dataset identity (§6.3.1 / §14.1). Emitted as
    # `data_fingerprint` only when at least one is provided; same opt-in pattern
    # as the provenance breadcrumb. Lets a baseline/candidate pair record WHICH
    # split they used so the verifier's rule 11 can flag cross_dataset.
    parser.add_argument(
        "--split-mode",
        default="",
        choices=["", "frozen", "declarative"],
        help="Which §6.3.1 split mode produced this run's data.",
    )
    parser.add_argument(
        "--dataset-fingerprint",
        default="",
        help=(
            "JSON object. Identity (source, version, date_window) is what makes "
            "the fingerprint comparable (verifier rule 11); row_count + schema_hash "
            "are optional strengtheners (omit for a growing dataset identified by "
            "date range). Written into the record as-is — log_experiment does NOT "
            "validate the shape (the record schema is intentionally permissive); "
            "completeness is enforced downstream: bootstrap_verify for the split "
            "MANIFEST, and rule 11 (which degrades to a cross_dataset warning on a "
            "missing/degenerate identity). Lighter same-set proof (assumes "
            "deterministic materialization)."
        ),
    )
    parser.add_argument(
        "--split-spec-hash",
        default="",
        help="Hash of the split rule/spec used to materialize the partition.",
    )
    parser.add_argument(
        "--split-seed",
        type=int,
        default=None,
        help="Seed used to materialize a declarative split.",
    )
    parser.add_argument(
        "--split-val-set-version",
        default="",
        help="val_set_version this run evaluated against (§17.6).",
    )
    parser.add_argument(
        "--membership-hash",
        default="",
        help=(
            "JSON object of per-split sorted-id sha256 "
            '(e.g. {"train": "...", "val": "...", "test": "..."}). Strongest '
            "byte-level same-set proof."
        ),
    )
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    record = build_record(args, now)

    try:
        schema = load_schema(args.schema)
    except (ValueError, OSError) as exc:
        # load_schema raises a clean, typed ValueError on any open/read/decode
        # failure (OSError/UnicodeDecodeError/json.JSONDecodeError). Convert it to
        # a clean nonzero exit with a message rather than a raw traceback.
        sys.stderr.write(f"CONFIG ERROR: {exc}\n")
        return 2
    errors = validate_against_schema(record, schema)
    tree_errors = validate_tree_fields(
        record, load_existing_record_ids(args.state_dir) | {record["id"]}
    )
    errors.extend(tree_errors)
    if errors:
        sys.stderr.write("SCHEMA VALIDATION FAILED:\n")
        for e in errors:
            sys.stderr.write(f"  - {e}\n")
        return 2

    out_path = write_record(args.state_dir, record)
    sys.stdout.write(f"Wrote {out_path}\n")
    # Confirm canonical bytes are computable (catches non-serializable input).
    _ = _canonical_record_bytes(record)

    if args.regenerate:
        try:
            from regenerate_state import regenerate
        except ImportError:  # pragma: no cover
            sys.path.insert(0, str(_SCRIPT_DIR))
            from regenerate_state import regenerate
        stats = regenerate(args.state_dir)
        sys.stdout.write(
            f"regenerated: records={stats['records']} "
            f"tree_nodes={stats['tree_nodes']} "
            f"val_query_sum={stats['val_query_sum']}\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
