#!/usr/bin/env python3
"""Bump Open-AutoResearch current-version surfaces.

This is a maintainer tool for this repository, not a host-campaign migrator.
It mechanizes the boring current-version edits while preserving historical
provenance text unless a maintainer edits that text by hand.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

CURRENT_TEXT_FILES = [
    ".github/workflows/validate-examples.yml",
    ".github/workflows/validate-ledger.yml",
    "README.md",
    "docs/adoption-levels.md",
    "docs/architecture.md",
    "docs/dogfooding.md",
    "docs/faq.md",
    "docs/host-bootstrap-agents.md",
    "examples/README.md",
    "template/BOOTSTRAP_QUESTIONS.yaml",
    "template/README.md",
    "template/state/README.md",
]

CURRENT_TEXT_ROOTS = [
    "template/config",
    "template/scripts",
    "template/templates",
]

EXAMPLE_ROOT = "examples"

EXCLUDED_RELATIVE_PATHS = {
    "template/PROTOCOL_VERSION",
    "template/schema/experiment_record.schema.json",
    "template/schema/split_manifest.schema.json",
    "template/scripts/migrate_ledger_v04_to_v05.py",
}

SCHEMA_FILES = [
    "template/schema/experiment_record.schema.json",
    "template/schema/split_manifest.schema.json",
]


@dataclass
class BumpResult:
    changed: list[str]
    manual_followups: list[str]


def read_current_version(repo_root: Path) -> str:
    return (repo_root / "template" / "PROTOCOL_VERSION").read_text(encoding="utf-8").strip()


def is_text_artifact(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def rel_path(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def iter_current_text_paths(repo_root: Path, include_examples: bool) -> list[Path]:
    tracked = tracked_relative_paths(repo_root)
    paths: list[Path] = []
    for rel in CURRENT_TEXT_FILES:
        path = repo_root / rel
        if path.exists():
            paths.append(path)

    for rel in CURRENT_TEXT_ROOTS:
        root = repo_root / rel
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and is_text_artifact(path):
                paths.append(path)

    if include_examples:
        root = repo_root / EXAMPLE_ROOT
        if root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file() and is_text_artifact(path):
                    paths.append(path)

    filtered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        rel = rel_path(repo_root, path)
        if rel in EXCLUDED_RELATIVE_PATHS:
            continue
        if tracked is not None and rel not in tracked:
            continue
        if path not in seen:
            seen.add(path)
            filtered.append(path)
    return filtered


def tracked_relative_paths(repo_root: Path) -> set[str] | None:
    git_marker = repo_root / ".git"
    if not git_marker.exists():
        return None
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return {rel for rel in proc.stdout.split("\0") if rel}


def replace_current_tokens(text: str, from_version: str, to_version: str) -> str:
    replacements = [
        (f'protocol_version: "{from_version}"', f'protocol_version: "{to_version}"'),
        (f"protocol_version: '{from_version}'", f"protocol_version: '{to_version}'"),
        (f'"protocol_version": "{from_version}"', f'"protocol_version": "{to_version}"'),
        (f'"protocol_version":"{from_version}"', f'"protocol_version":"{to_version}"'),
        (f"AutoResearch++ v{from_version}", f"AutoResearch++ v{to_version}"),
        (f"AutoResearch++ Protocol v{from_version}", f"AutoResearch++ Protocol v{to_version}"),
        (f"Protocol {from_version}", f"Protocol {to_version}"),
        (f"PROTOCOL_VERSION              # contains {from_version}", f"PROTOCOL_VERSION              # contains {to_version}"),
        (f'PROTOCOL_VERSION              # contains "{from_version}"', f'PROTOCOL_VERSION              # contains "{to_version}"'),
        (f'PROTOCOL_VERSION = "{from_version}"', f'PROTOCOL_VERSION = "{to_version}"'),
        (f'EXPECTED_PROTOCOL_VERSION = "{from_version}"', f'EXPECTED_PROTOCOL_VERSION = "{to_version}"'),
        (f'return "{from_version}"', f'return "{to_version}"'),
        (f"Protocol version shipped:** `{from_version}`", f"Protocol version shipped:** `{to_version}`"),
        (f"`v{from_version}`", f"`v{to_version}`"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)

    text = re.sub(
        rf"(?<![A-Za-z0-9_.-])v{re.escape(from_version)}(?![0-9.])",
        f"v{to_version}",
        text,
    )
    return text


def update_protocol_text(text: str, from_version: str, to_version: str, release_date: str) -> str:
    marker = "\n## 0. Versioning policy"
    before, sep, after = text.partition(marker)
    before = re.sub(
        rf"^\*\*Version:\*\*\s*{re.escape(from_version)}\s*$",
        f"**Version:** {to_version}",
        before,
        flags=re.MULTILINE,
    )
    if from_version != to_version:
        before = re.sub(
            r"^\*\*Date:\*\*\s*[0-9]{4}-[0-9]{2}-[0-9]{2}\s*$",
            f"**Date:** {release_date}",
            before,
            flags=re.MULTILINE,
        )
    if sep:
        after = replace_current_tokens(after, from_version, to_version)
        return before + sep + after
    return before


def update_schema_text(text: str, from_version: str, to_version: str) -> str:
    text = replace_current_tokens(text, from_version, to_version)
    text = text.replace(f'\\"{from_version}\\"', f'\\"{to_version}\\"')

    def add_enum_version(match: re.Match[str]) -> str:
        body = match.group(1)
        if f'"{to_version}"' in body:
            return match.group(0)
        return body.rstrip() + f', "{to_version}"' + match.group(2)

    return re.sub(
        rf'("enum"\s*:\s*\[[^\]]*"{re.escape(from_version)}"[^\]]*)(\])',
        add_enum_version,
        text,
    )


def update_supported_versions_expression(text: str, from_version: str, to_version: str) -> str:
    if from_version == to_version:
        return text
    pattern = re.compile(r"^SUPPORTED_PROTOCOL_VERSIONS\s*=\s*\{([^}]+)\}", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return text

    body = match.group(1)
    string_versions = set(re.findall(r'"([0-9.]+)"', body))
    string_versions.add(from_version)
    tokens = [f'"{version}"' for version in sorted(string_versions, key=version_key)]
    if "PROTOCOL_VERSION" in body:
        tokens.append("PROTOCOL_VERSION")
    replacement = "SUPPORTED_PROTOCOL_VERSIONS = {" + ", ".join(tokens) + "}"
    return text[: match.start()] + replacement + text[match.end() :]


def version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return (9999,)


def canonical_record_bytes(entry: dict[str, Any]) -> bytes:
    return json.dumps(entry, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def iter_reference_objects(value: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "content_sha256" in value and ("ledger_id" in value or "path" in value):
            refs.append(value)
        for child in value.values():
            refs.extend(iter_reference_objects(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(iter_reference_objects(child))
    return refs


def campaign_root_for_request(path: Path) -> Path | None:
    parts = path.parts
    if "proposals" not in parts:
        return None
    proposal_index = parts.index("proposals")
    if proposal_index == 0:
        return None
    return Path(*parts[:proposal_index])


def refresh_promotion_request_hashes(repo_root: Path, request_path: Path) -> str:
    text = request_path.read_text(encoding="utf-8")
    data = json.loads(text)
    refs = data.get("references")
    if not isinstance(refs, dict):
        return text

    campaign_rel = campaign_root_for_request(request_path.relative_to(repo_root))
    if campaign_rel is None:
        return text
    campaign_root = repo_root / campaign_rel

    for ref in iter_reference_objects(refs):
        claimed = ref.get("content_sha256")
        if not isinstance(claimed, str):
            continue
        actual: str | None = None
        ledger_id = ref.get("ledger_id")
        path_ref = ref.get("path")
        if isinstance(ledger_id, str):
            ledger_path = campaign_root / "state" / "ledger" / f"{ledger_id}.json"
            if ledger_path.exists():
                entry = json.loads(ledger_path.read_text(encoding="utf-8"))
                actual = sha256_bytes(canonical_record_bytes(entry))
        elif isinstance(path_ref, str):
            candidate = (campaign_root / path_ref).resolve()
            try:
                candidate.relative_to(campaign_root.resolve())
            except ValueError:
                actual = None
            else:
                if candidate.exists():
                    actual = sha256_bytes(candidate.read_bytes())
        if actual and actual != claimed:
            text = text.replace(f'"content_sha256": "{claimed}"', f'"content_sha256": "{actual}"')
    return text


def write_or_record(path: Path, new_text: str, changed: list[str], repo_root: Path, write: bool) -> None:
    old_text = path.read_text(encoding="utf-8")
    if old_text == new_text:
        return
    changed.append(rel_path(repo_root, path))
    if write:
        path.write_text(new_text, encoding="utf-8", newline="")


def diff_for_change(path: Path, repo_root: Path, new_text: str) -> str:
    old = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new = new_text.splitlines(keepends=True)
    rel = rel_path(repo_root, path)
    return "".join(difflib.unified_diff(old, new, fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def run_bump(
    repo_root: Path,
    to_version: str,
    *,
    from_version: str | None = None,
    release_date: str | None = None,
    include_examples: bool = True,
    write: bool = True,
    show_diff: bool = False,
) -> BumpResult:
    repo_root = repo_root.resolve()
    from_version = from_version or read_current_version(repo_root)
    release_date = release_date or dt.date.today().isoformat()

    changed: list[str] = []
    manual_followups = [
        "Add or adjust CHANGELOG.md release notes.",
        "Add or adjust MIGRATION.md guidance when the bump changes downstream adoption.",
        "Review PROTOCOL.md changelog prose; historical entries are intentionally not rewritten.",
    ]

    planned_diffs: list[str] = []

    pv_path = repo_root / "template" / "PROTOCOL_VERSION"
    new_pv_text = f"{to_version}\n"
    if pv_path.exists():
        if show_diff and pv_path.read_text(encoding="utf-8") != new_pv_text:
            planned_diffs.append(diff_for_change(pv_path, repo_root, new_pv_text))
        write_or_record(pv_path, new_pv_text, changed, repo_root, write)

    protocol_path = repo_root / "PROTOCOL.md"
    if protocol_path.exists():
        new_text = update_protocol_text(
            protocol_path.read_text(encoding="utf-8"),
            from_version,
            to_version,
            release_date,
        )
        if show_diff and protocol_path.read_text(encoding="utf-8") != new_text:
            planned_diffs.append(diff_for_change(protocol_path, repo_root, new_text))
        write_or_record(protocol_path, new_text, changed, repo_root, write)

    for path in iter_current_text_paths(repo_root, include_examples):
        text = path.read_text(encoding="utf-8")
        new_text = replace_current_tokens(text, from_version, to_version)
        if path.as_posix().endswith("template/scripts/verifier/verify_request.py"):
            new_text = update_supported_versions_expression(new_text, from_version, to_version)
        if show_diff and text != new_text:
            planned_diffs.append(diff_for_change(path, repo_root, new_text))
        write_or_record(path, new_text, changed, repo_root, write)

    for rel in SCHEMA_FILES:
        path = repo_root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new_text = update_schema_text(text, from_version, to_version)
        if show_diff and text != new_text:
            planned_diffs.append(diff_for_change(path, repo_root, new_text))
        write_or_record(path, new_text, changed, repo_root, write)

    if include_examples:
        tracked = tracked_relative_paths(repo_root)
        for request_path in sorted((repo_root / EXAMPLE_ROOT).glob("*/proposals/*promotion-request.json")):
            if tracked is not None and rel_path(repo_root, request_path) not in tracked:
                continue
            new_text = refresh_promotion_request_hashes(repo_root, request_path)
            if show_diff and request_path.read_text(encoding="utf-8") != new_text:
                planned_diffs.append(diff_for_change(request_path, repo_root, new_text))
            write_or_record(request_path, new_text, changed, repo_root, write)

    if show_diff and planned_diffs:
        print("\n".join(planned_diffs), end="")

    return BumpResult(changed=sorted(set(changed)), manual_followups=manual_followups)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump Open-AutoResearch current-version surfaces from template/PROTOCOL_VERSION."
    )
    parser.add_argument("version", help="New protocol version, e.g. 0.7")
    parser.add_argument("--from-version", help="Version to replace; defaults to template/PROTOCOL_VERSION")
    parser.add_argument("--date", help="Release date for PROTOCOL.md header; defaults to today")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="Repository root")
    parser.add_argument("--check", action="store_true", help="Fail if the bump would change files; do not write")
    parser.add_argument("--dry-run", action="store_true", help="Print changed paths without writing")
    parser.add_argument("--diff", action="store_true", help="Print a unified diff for planned changes")
    parser.add_argument("--skip-examples", action="store_true", help="Do not restamp example campaign fixtures")
    args = parser.parse_args(argv)

    write = not args.check and not args.dry_run
    result = run_bump(
        Path(args.repo),
        args.version,
        from_version=args.from_version,
        release_date=args.date,
        include_examples=not args.skip_examples,
        write=write,
        show_diff=args.diff,
    )

    if result.changed:
        print("Changed paths:" if write else "Paths that would change:")
        for rel in result.changed:
            print(f"- {rel}")
    else:
        print("No version-stamp changes needed.")

    print("Manual follow-ups:")
    for item in result.manual_followups:
        print(f"- {item}")

    if args.check and result.changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
