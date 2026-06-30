#!/usr/bin/env python3
"""Check Open-AutoResearch's repo-local harness invariants.

This is intentionally small and stdlib-only. It is not a protocol verifier; it
guards the repo-facing harness surfaces that agents use before editing this
repository.
"""

from __future__ import annotations

import argparse
import subprocess
import re
import sys
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

TEXT_ARTIFACT_SUFFIXES = {
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

REQUIRED_SURFACES = [
    ".gitattributes",
    "AGENTS.md",
    "CODEOWNERS",
    "docs/README.md",
    "docs/architecture.md",
    "docs/dogfooding.md",
    "docs/harness-metrics-baseline.json",
    "docs/harness-version.json",
    "docs/host-bootstrap-agents.md",
    "docs/runtime-safety.md",
    "docs/testing.md",
    "scripts/check_repo_harness.py",
    "scripts/harness_metrics.py",
    "scripts/quality_gate.py",
    "scripts/weekly_quality_report.py",
    "scripts/pr-agent-inbox.mjs",
    "scripts/pr-agent-inbox.test.mjs",
    "scripts/tests/test_harness_metrics.py",
    "scripts/tests/test_quality_gate.py",
    "scripts/tests/test_weekly_quality_report.py",
    ".github/workflows/protect-protocol.yml",
    ".github/workflows/pr-agent-inbox.yml",
    ".github/workflows/weekly-quality-report.yml",
]


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


failures: list[str] = []
warnings: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def require_file(path: str) -> None:
    if not exists(path):
        fail(f"{path} is missing")


def require_contains(path: str, snippet: str, reason: str) -> None:
    if not exists(path):
        fail(f"{path} is missing; cannot verify {reason}")
        return
    if snippet not in read(path):
        fail(f"{path} must contain {snippet!r} ({reason})")


def is_text_artifact(path: Path) -> bool:
    return path.suffix.lower() in TEXT_ARTIFACT_SUFFIXES


def tracked_paths_under(path: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", path],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(f"git ls-files failed for {path}: {result.stderr.strip()}")
        return []
    return [REPO_ROOT / rel for rel in result.stdout.split("\0") if rel]


def extract_protocol_version() -> str | None:
    match = re.search(r"^\*\*Version:\*\*\s*([0-9.]+)\s*$", read("PROTOCOL.md"), re.MULTILINE)
    if not match:
        fail("PROTOCOL.md is missing a '**Version:** X.Y' header")
        return None
    return match.group(1)


def check_required_surfaces() -> None:
    for path in REQUIRED_SURFACES:
        require_file(path)


def check_agents_routing() -> None:
    if not exists("AGENTS.md"):
        return

    text = read("AGENTS.md")
    line_count = len(text.rstrip("\n").splitlines()) if text else 0
    byte_count = len(text.encode("utf-8"))

    if line_count > 120:
        fail(f"AGENTS.md has {line_count} lines; route details behind docs instead")
    if byte_count > 7000:
        fail(f"AGENTS.md has {byte_count} bytes; route details behind docs instead")

    for snippet, reason in [
        ("docs/dogfooding.md", "repo-maintainer dogfooding route"),
        ("docs/README.md", "repo-maintainer docs router"),
        ("docs/testing.md", "validation route"),
        ("docs/runtime-safety.md", "runtime-safety route"),
        ("docs/host-bootstrap-agents.md", "host bootstrap route"),
        ("PROTOCOL.md", "campaign/protocol route"),
        ("python scripts/quality_gate.py", "canonical quality gate"),
    ]:
        require_contains("AGENTS.md", snippet, reason)

    forbidden = [
        ("**1. Ask for the host repo path", "host bootstrap checklist belongs in docs/host-bootstrap-agents.md"),
        ("Commit: `chore(autoresearch): scaffold template", "commit-by-commit host workflow belongs in routed docs"),
    ]
    for snippet, reason in forbidden:
        if snippet in text:
            fail(f"AGENTS.md includes {snippet!r}; {reason}")


def check_dogfooding_anchors() -> None:
    anchors = [
        ("Evidence:", "admission gate evidence field"),
        ("Smaller control:", "admission gate smaller-control field"),
        ("Validation:", "admission gate validation field"),
        ("Retirement or revisit:", "admission gate retirement field"),
        ("Cross-Surface Sync", "protocol/template/example sync model"),
        ("Roadmap Hygiene", "roadmap decomposition model"),
        ("Version And Ledger Drift", "Protocol 0.5 drift guard"),
    ]
    for snippet, reason in anchors:
        require_contains("docs/dogfooding.md", snippet, reason)


def check_router_docs() -> None:
    required = [
        ("docs/README.md", "python scripts/quality_gate.py", "docs router quality gate"),
        ("docs/README.md", "docs/architecture.md", "architecture route"),
        ("docs/README.md", "docs/testing.md", "testing route"),
        ("docs/README.md", "docs/runtime-safety.md", "runtime-safety route"),
        ("docs/architecture.md", "PROTOCOL.md", "normative protocol surface"),
        ("docs/testing.md", "python scripts/quality_gate.py", "canonical local quality gate"),
        ("docs/runtime-safety.md", "harness-bootstrap init", "HEB bootstrap command note"),
        ("docs/testing.md", "weekly_quality_report.py", "weekly quality report route"),
        (
            "docs/testing.md",
            "python scripts/harness_metrics.py --baseline docs/harness-metrics-baseline.json",
            "minimal local metrics route",
        ),
    ]
    for path, snippet, reason in required:
        require_contains(path, snippet, reason)


def check_harness_metadata() -> None:
    path = "docs/harness-version.json"
    if not exists(path):
        fail(f"{path} is missing")
        return
    try:
        metadata = json.loads(read(path))
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")
        return
    if metadata.get("templateVersion") != "0.1.0":
        fail(f"{path} templateVersion must be 0.1.0")
    if not metadata.get("sourceRelease"):
        fail(f"{path} must record sourceRelease for future update planning")
    if "scripts/quality_gate.py" not in "\n".join(metadata.get("acceptedControls", [])):
        fail(f"{path} must record scripts/quality_gate.py as an accepted control")
    if "scripts/harness_metrics.py" not in "\n".join(metadata.get("acceptedControls", [])):
        fail(f"{path} must record scripts/harness_metrics.py as an accepted control")


def check_metrics_baseline() -> None:
    path = "docs/harness-metrics-baseline.json"
    if not exists(path):
        fail(f"{path} is missing")
        return
    try:
        baseline = json.loads(read(path))
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")
        return
    if baseline.get("kind") != "open-autoresearch-harness-metrics-baseline":
        fail(f"{path} has unexpected kind")
    if baseline.get("measurementCommand") != "python scripts/harness_metrics.py --baseline docs/harness-metrics-baseline.json":
        fail(f"{path} must record the canonical metrics command")
    metrics = baseline.get("baseline", {})
    for key in [
        "alwaysOnInstruction",
        "requiredFiles",
        "brokenInternalLinks",
        "validator",
        "activeDecisionCount",
        "contractCount",
    ]:
        if key not in metrics:
            fail(f"{path} baseline is missing {key!r}")


def check_active_plan_headers() -> None:
    plan_dir = REPO_ROOT / "docs" / "plans" / "active"
    if not plan_dir.exists():
        return
    for path in sorted(plan_dir.glob("*.md")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for key in [
            "status",
            "owner",
            "created",
            "updated",
            "next_action",
            "validation_command",
            "stop_condition",
            "supersedes",
            "superseded_by",
            "retirement_or_revisit",
        ]:
            if not re.search(rf"^{re.escape(key)}:\s+\S", text, re.MULTILINE):
                fail(f"{rel} header must include {key}:")


def check_version_consistency() -> None:
    protocol_version = extract_protocol_version()
    if protocol_version is None:
        return

    template_version = read("template/PROTOCOL_VERSION").strip()
    if template_version != protocol_version:
        fail(
            "template/PROTOCOL_VERSION "
            f"({template_version}) does not match PROTOCOL.md ({protocol_version})"
        )

    expected_snippets = [
        ("README.md", f"AutoResearch++ v{protocol_version}", "README centerpiece version"),
        ("README.md", f"Protocol version shipped:** `{protocol_version}`", "README shipped version"),
        ("examples/README.md", f"AutoResearch++ v{protocol_version}", "examples README version"),
        (
            "docs/host-bootstrap-agents.md",
            f'protocol_version: "{protocol_version}"',
            "host bootstrap current protocol stamp",
        ),
    ]
    for path, snippet, reason in expected_snippets:
        require_contains(path, snippet, reason)

    require_contains(
        "docs/faq.md",
        f"The protocol is `v{protocol_version}`",
        "FAQ current protocol version",
    )

    for path in sorted(tracked_paths_under("examples")):
        if not path.is_file() or not is_text_artifact(path):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        matches = [
            *re.findall(r'protocol_version:\s*["\']?([0-9.]+)', text),
            *re.findall(r'"protocol_version"\s*:\s*"([0-9.]+)"', text),
        ]
        stale_versions = sorted({version for version in matches if version != protocol_version})
        if stale_versions:
            fail(
                f"{rel} has example artifact protocol_version "
                f"{', '.join(stale_versions)}; expected {protocol_version}"
            )

    active_doc_drift = [
        ("docs/host-bootstrap-agents.md", "v0.4 closes it structurally"),
        ("docs/host-bootstrap-agents.md", "below the v0.4 default"),
    ]
    for path, snippet in active_doc_drift:
        if exists(path) and snippet in read(path):
            fail(
                f"{path} still describes active bootstrap behavior with "
                f"stale Protocol 0.4 wording: {snippet!r}"
            )


def check_ledger_rotation_drift() -> None:
    forbidden_snippets = [
        ("PROTOCOL.md", "ledger rotation interval"),
        ("PROTOCOL.md", "**rotated per §17.5.4**"),
        ("PROTOCOL.md", "ledger_rotation_iterations"),
        ("PROTOCOL.md", "ledger rotation (§17.5.4)"),
        ("PROTOCOL.md", "ledger rotates per §17.5.4"),
        ("PROTOCOL.md", "experiment ledger (with rotation"),
        ("PROTOCOL.md", "ledger + playbook with rotation"),
        ("template/config/metrics.yaml.example", "ledger_rotation_iterations"),
        ("template/config/metrics.yaml.example", "ledger rotation config"),
        ("examples/level1-success/config/metrics.yaml", "ledger_rotation_iterations"),
        ("examples/level3-counter-example/config/metrics.yaml", "ledger_rotation_iterations"),
    ]
    for path, snippet in forbidden_snippets:
        if exists(path) and snippet in read(path):
            fail(f"{path} still contains active stale ledger-rotation guidance: {snippet!r}")


def check_migration_guidance_drift() -> None:
    forbidden_snippets = [
        (
            "MIGRATION.md",
            "Path-based hashes (e.g. a `skeptic_review` reference by file path) do NOT change.",
        ),
    ]
    for path, snippet in forbidden_snippets:
        if exists(path) and snippet in read(path):
            fail(f"{path} still contains stale migration guidance: {snippet!r}")


def check_ci_wiring() -> None:
    workflow = ".github/workflows/protect-protocol.yml"
    if not exists(workflow):
        warn(f"{workflow} is missing; repo-harness check is not wired into CI")
        return
    text = read(workflow)
    for snippet in [
        "python scripts/quality_gate.py",
        "scripts/check_repo_harness.py",
        "scripts/harness_metrics.py",
        "scripts/quality_gate.py",
        "scripts/weekly_quality_report.py",
        "scripts/pr-agent-inbox.mjs",
        "scripts/pr-agent-inbox.test.mjs",
        "docs/harness-metrics-baseline.json",
        "weekly-quality-report.yml",
        "pr-agent-inbox.yml",
        "docs/README.md",
        "docs/architecture.md",
        "docs/dogfooding.md",
        "docs/harness-version.json",
        "docs/host-bootstrap-agents.md",
        "docs/runtime-safety.md",
        "docs/testing.md",
        "docs/faq.md",
        "AGENTS.md",
    ]:
        if snippet not in text:
            fail(f"{workflow} must reference {snippet!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Open-AutoResearch repo harness invariants.")
    parser.add_argument("--skip-metrics", action="store_true", help="Skip metrics baseline shape checks.")
    args = parser.parse_args(argv)

    check_required_surfaces()
    check_agents_routing()
    check_dogfooding_anchors()
    check_router_docs()
    check_harness_metadata()
    check_active_plan_headers()
    if not args.skip_metrics:
        check_metrics_baseline()
    check_version_consistency()
    check_ledger_rotation_drift()
    check_migration_guidance_drift()
    check_ci_wiring()

    for warning in warnings:
        print(f"WARN: {warning}")
    if failures:
        print("FAIL: repo harness check failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("OK: repo harness check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
