#!/usr/bin/env python3
"""Collect small repo-harness metrics for Open-AutoResearch."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_repo_harness import REQUIRED_SURFACES

REQUIRED_FILES = list(REQUIRED_SURFACES)


def collect_metrics(repo: Path = REPO_ROOT, include_validator: bool = True) -> dict[str, object]:
    agents = read_text(repo / "AGENTS.md")
    markdown_files = markdown_files_for_scan(repo)
    broken_links = find_broken_internal_links(repo, markdown_files)
    required_missing = [path for path in REQUIRED_FILES if not (repo / path).exists()]

    return {
        "kind": "open-autoresearch-harness-metrics",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "alwaysOnInstruction": {
                "path": "AGENTS.md",
                "lineCount": len(agents.rstrip("\n").splitlines()) if agents else 0,
                "byteCount": len(agents.encode("utf-8")),
            },
            "requiredFiles": {
                "count": len(REQUIRED_FILES),
                "missing": required_missing,
            },
            "brokenInternalLinks": {
                "count": len(broken_links),
                "items": broken_links[:25],
            },
            "validator": validator_result(repo, include_validator),
            "activeDecisionCount": count_active_decisions(repo),
            "contractCount": count_contract_docs(repo),
        },
    }


def validate_baseline(baseline_path: Path, metrics: dict[str, object] | None = None) -> list[str]:
    failures: list[str] = []
    if not baseline_path.exists():
        return [f"{baseline_path} is missing"]
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{baseline_path} is not valid JSON: {exc}"]
    for key in ["kind", "created", "measurementCommand", "baseline"]:
        if key not in baseline:
            failures.append(f"{baseline_path} is missing {key!r}")
    baseline_metrics = baseline.get("baseline", {})
    for key in [
        "alwaysOnInstruction",
        "requiredFiles",
        "brokenInternalLinks",
        "validator",
        "activeDecisionCount",
        "contractCount",
    ]:
        if key not in baseline_metrics:
            failures.append(f"{baseline_path} baseline is missing {key!r}")
    if metrics:
        current = metrics.get("metrics", {})
        missing = current.get("requiredFiles", {}).get("missing", [])
        if missing:
            failures.append("current harness metrics report missing required files: " + ", ".join(missing))
        broken_links = current.get("brokenInternalLinks", {}).get("items", [])
        if broken_links:
            failures.append(f"current harness metrics report {len(broken_links)} broken internal links")
        validator = current.get("validator", {})
        if validator.get("passed") is not True:
            failures.append("current harness validator did not pass")
    return failures


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def markdown_files_for_scan(repo: Path) -> list[Path]:
    resolved_repo = repo.resolve()
    git_files = git_tracked_markdown_files(resolved_repo)
    if git_files is not None:
        return git_files

    files: list[Path] = []
    for path in resolved_repo.rglob("*.md"):
        relative_parts = path.relative_to(resolved_repo).parts
        if ".git" in relative_parts or ".worktrees" in relative_parts:
            continue
        files.append(path)
    return sorted(files)


def git_tracked_markdown_files(repo: Path) -> list[Path] | None:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return None
    files = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        if Path(rel).suffix != ".md":
            continue
        files.append(repo / rel)
    return sorted(files)


def find_broken_internal_links(repo: Path, markdown_files: list[Path]) -> list[dict[str, object]]:
    broken: list[dict[str, object]] = []
    pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
    for path in markdown_files:
        text = read_text(path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in pattern.finditer(line):
                href = match.group(1).strip()
                if should_skip_href(href):
                    continue
                target = href.split("#", 1)[0]
                if not target:
                    continue
                target_path = (path.parent / target).resolve()
                try:
                    target_path.relative_to(repo.resolve())
                except ValueError:
                    continue
                if not target_path.exists():
                    broken.append(
                        {
                            "path": path.relative_to(repo).as_posix(),
                            "line": line_number,
                            "href": href,
                        }
                    )
    return broken


def should_skip_href(href: str) -> bool:
    lowered = href.lower()
    return (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("mailto:")
        or lowered.startswith("#")
        or lowered.startswith("file:")
    )


def validator_result(repo: Path, include_validator: bool) -> dict[str, object]:
    command = [sys.executable, "scripts/check_repo_harness.py", "--skip-metrics"]
    display = "python scripts/check_repo_harness.py --skip-metrics"
    if not include_validator:
        return {"command": display, "passed": None, "skipped": True}
    try:
        proc = subprocess.run(
            command,
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": display,
            "passed": False,
            "exitCode": None,
            "timedOut": True,
            "outputTail": tail(exc.stdout or ""),
        }
    return {
        "command": display,
        "passed": proc.returncode == 0,
        "exitCode": proc.returncode,
        "outputTail": tail(proc.stdout),
    }


def tail(text: str, max_lines: int = 20) -> str:
    lines = [line for line in text.rstrip().splitlines() if line]
    return "\n".join(lines[-max_lines:])


def count_active_decisions(repo: Path) -> int:
    adr_dir = repo / "docs" / "adr"
    if not adr_dir.exists():
        return 0
    count = 0
    for path in adr_dir.glob("*.md"):
        text = read_text(path)
        if re.search(r"^[-*]\s+Status:\s+(Accepted|Active)\s*$", text, re.MULTILINE):
            count += 1
    return count


def count_contract_docs(repo: Path) -> int:
    count = 0
    for rel in ["docs/data-contracts", "docs/repo-contracts"]:
        path = repo / rel
        if path.exists():
            count += len(list(path.rglob("*.md")))
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect repo-harness metrics.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--baseline", help="Validate the baseline artifact shape.")
    parser.add_argument("--no-validator", action="store_true", help="Do not run the repo harness validator.")
    args = parser.parse_args(argv)

    metrics = collect_metrics(include_validator=not args.no_validator)
    failures = validate_baseline(REPO_ROOT / args.baseline, metrics) if args.baseline else []
    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        values = metrics["metrics"]
        print("Open-AutoResearch harness metrics")
        print(f"- AGENTS.md lines: {values['alwaysOnInstruction']['lineCount']}")
        print(f"- AGENTS.md bytes: {values['alwaysOnInstruction']['byteCount']}")
        print(f"- required files missing: {len(values['requiredFiles']['missing'])}")
        print(f"- broken internal links: {values['brokenInternalLinks']['count']}")
        print(f"- harness validator passed: {values['validator']['passed']}")
        print(f"- active decisions: {values['activeDecisionCount']}")
        print(f"- contract docs: {values['contractCount']}")

    if failures:
        print("FAIL: harness metrics baseline is invalid", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
