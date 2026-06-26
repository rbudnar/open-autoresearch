#!/usr/bin/env python3
"""Run Open-AutoResearch's local repo quality gate.

This is the maintainer-side gate for this repository. It intentionally mirrors
the CI-shaped checks that are safe and useful to run before review.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

REFERENCE_SCRIPTS = [
    "template/scripts/behavioral_equivalence.py",
    "template/scripts/verifier/verify_request.py",
    "template/scripts/verifier/sign_packet.py",
    "template/scripts/_ledger_common.py",
    "template/scripts/log_experiment.py",
    "template/scripts/regenerate_state.py",
    "template/scripts/validate_ledger.py",
    "template/scripts/migrate_ledger_v04_to_v05.py",
]

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


def run(args: list[str], cwd: Path | None = None, expect: int = 0) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(args)}")
    proc = subprocess.run(
        args,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.returncode != expect:
        raise SystemExit(f"command exited {proc.returncode}, expected {expect}: {' '.join(args)}")
    return proc


def git_capture(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def check_git_diff() -> None:
    if (REPO_ROOT / ".git").exists() or (REPO_ROOT / ".git").is_file():
        pr_range = github_pr_diff_range()
        if pr_range:
            run(["git", "diff", "--check", *pr_range])
        elif git_capture(["rev-parse", "--verify", "origin/main"]):
            proc = subprocess.run(
                ["git", "diff", "--quiet", "origin/main...HEAD"],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if proc.returncode == 1:
                run(["git", "diff", "--check", "origin/main...HEAD"])
        run(["git", "diff", "--check"])


def github_pr_diff_range() -> list[str]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return []
    path = Path(event_path)
    if not path.exists():
        return []
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return []
    base = pull_request.get("base", {}).get("sha")
    head = pull_request.get("head", {}).get("sha")
    if isinstance(base, str) and isinstance(head, str):
        return [base, head]
    return []


def check_repo_harness() -> None:
    run([sys.executable, "scripts/check_repo_harness.py"])


def check_harness_metrics() -> None:
    run([sys.executable, "scripts/harness_metrics.py", "--baseline", "docs/harness-metrics-baseline.json"])


def check_script_parse() -> None:
    for rel in REFERENCE_SCRIPTS:
        ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
    print(f"OK: parsed {len(REFERENCE_SCRIPTS)} reference scripts")


def check_script_help() -> None:
    for rel in REFERENCE_SCRIPTS:
        if rel == "template/scripts/_ledger_common.py":
            continue
        run([sys.executable, rel, "--help"])
    print("OK: --help works on reference entrypoints")


def check_example_versions() -> None:
    protocol_version = (REPO_ROOT / "template/PROTOCOL_VERSION").read_text(encoding="utf-8").strip()
    bad: list[str] = []
    for path in sorted((REPO_ROOT / "examples").rglob("*")):
        if not path.is_file() or not is_text_artifact(path):
            continue
        text = path.read_text(encoding="utf-8")
        if f'protocol_version: "0.4"' in text or f'"protocol_version":"0.4"' in text:
            bad.append(path.relative_to(REPO_ROOT).as_posix())
        if '"protocol_version"' in text or "protocol_version:" in text:
            for token in ['"protocol_version":"', '"protocol_version": "', "protocol_version: \""]:
                start = 0
                while True:
                    index = text.find(token, start)
                    if index < 0:
                        break
                    value_start = index + len(token)
                    value_end = text.find('"', value_start)
                    if value_end > value_start:
                        value = text[value_start:value_end]
                        if value != protocol_version:
                            bad.append(f"{path.relative_to(REPO_ROOT).as_posix()} ({value})")
                    start = value_start
    if bad:
        raise SystemExit("stale example protocol versions:\n- " + "\n- ".join(sorted(set(bad))))
    print(f"OK: example artifact protocol_version stamps match {protocol_version}")


def is_text_artifact(path: Path) -> bool:
    return path.suffix.lower() in TEXT_ARTIFACT_SUFFIXES


def check_example_ledgers() -> None:
    ledger_dirs = sorted((REPO_ROOT / "examples").glob("*/state/ledger"))
    if not ledger_dirs:
        raise SystemExit("no examples/*/state/ledger directories found")
    for ledger_dir in ledger_dirs:
        run(
            [
                sys.executable,
                "template/scripts/validate_ledger.py",
                "--ledger-dir",
                str(ledger_dir.relative_to(REPO_ROOT)),
            ]
        )
    print(f"OK: validated {len(ledger_dirs)} example ledger directories")


def check_repo_script_tests() -> None:
    tests_dir = REPO_ROOT / "scripts" / "tests"
    if not tests_dir.exists():
        return
    run([sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_*.py"])


def check_verifier_rejection() -> None:
    example = REPO_ROOT / "examples" / "level3-counter-example"
    with tempfile.TemporaryDirectory(prefix="oar-quality-gate-") as out_dir:
        run([sys.executable, "../../template/scripts/regenerate_state.py", "--state-dir", "state/"], cwd=example)
        proc = run(
            [
                sys.executable,
                "../../template/scripts/verifier/verify_request.py",
                "--request",
                "proposals/iter08-promotion-request.json",
                "--ledger",
                "state/ledger/",
                "--metrics",
                "config/metrics.yaml",
                "--enforcement",
                "config/enforcement.yaml",
                "--out-dir",
                out_dir,
                "--verifier-identity",
                "local-quality-gate",
                "--unsigned",
            ],
            cwd=example,
            expect=1,
        )
        packet = Path(out_dir) / "20260518-220000-bbb008-promotion-packet.json"
        data = json.loads(packet.read_text(encoding="utf-8"))
        reasons = " ".join(data.get("rejection_reasons", []))
        if data.get("status") != "rejected" or data.get("not_deployable") is not True:
            raise SystemExit(f"unexpected verifier packet status: {data}")
        if "val exposure" not in reasons.lower():
            raise SystemExit(f"expected val-exposure rejection, got: {reasons}")
        if "status=rejected" not in proc.stdout:
            raise SystemExit("verifier output did not report status=rejected")
    print("OK: Level-3 counter-example verifier rejection preserved")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Open-AutoResearch's local quality gate.")
    parser.add_argument("--skip-verifier", action="store_true", help="Skip the Level-3 verifier regression.")
    parser.add_argument("--only-verifier", action="store_true", help="Run only the Level-3 verifier regression.")
    args = parser.parse_args()

    if args.only_verifier:
        check_verifier_rejection()
        return 0

    check_repo_harness()
    check_harness_metrics()
    check_git_diff()
    check_script_parse()
    check_script_help()
    check_repo_script_tests()
    check_example_versions()
    check_example_ledgers()
    if not args.skip_verifier:
        check_verifier_rejection()
    print("OK: quality gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
