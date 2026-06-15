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
        _canonical_record_bytes,
        load_schema,
        sanitize_slug,
        validate_against_schema,
    )
except ImportError:  # pragma: no cover - path shim for direct invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _ledger_common import (
        _canonical_record_bytes,
        load_schema,
        sanitize_slug,
        validate_against_schema,
    )

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA = _SCRIPT_DIR.parent / "schema" / "experiment_record.schema.json"
DEFAULT_PROTOCOL_VERSION_FILE = _SCRIPT_DIR.parent / "PROTOCOL_VERSION"


def read_protocol_version(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
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
        parsed = json.loads(args.metrics_json)
        if not isinstance(parsed, dict):
            raise SystemExit("--metrics-json must be a JSON object")
        metrics = parsed

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
        record["val_queries_incurred_by_this_run"] = args.val_queries
    if args.node_title:
        record["node_title"] = args.node_title
    if args.node_lesson:
        record["node_lessons"] = list(args.node_lesson)
    return record


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
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    record = build_record(args, now)

    schema = load_schema(args.schema)
    errors = validate_against_schema(record, schema)
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
