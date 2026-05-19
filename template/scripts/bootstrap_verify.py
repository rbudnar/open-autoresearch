"""bootstrap_verify.py — end-of-bootstrap smoke test.

After an integrating agent walks AGENTS.md's 8-step workflow, run this script
against the host repo to confirm the install is complete and self-consistent.
It is NOT a research-time tool; it is a one-shot pass/fail check.

Checks performed (each is independent and reports its own pass/fail):

  1. ``autoresearch/`` directory exists in the host repo.
  2. All four config files exist as materialized ``.yaml`` (not just
     ``.yaml.example``): ``metrics.yaml``, ``enforcement.yaml``,
     ``protected_paths.yaml``, ``editable_paths.yaml``.
  3. None of the materialized config files contain ``<FILL_ME>`` anywhere.
     (Codex finding #6 in the agent-onboarding PR: leaving any placeholder
     unfilled silently breaks the loop.)
  4. ``autoresearch/bootstrap-answers.yaml`` exists with the required
     frontmatter (``protocol_version``, ``bootstrapped_at``,
     ``bootstrapped_by``, ``answers``).
  5. ``data/splits/MANIFEST.json`` exists with every §6.3.1 field
     populated (``snapshot_id``, ``val_set_version``, ``train``/``val``/
     ``test`` each with ``path``+``sha256``+``size_bytes``, ``frozen_at``,
     ``frozen_by``).
  6. ``evaluation/fixtures/`` exists with at least 3 fixture JSON files,
     unless ``bootstrap-answers.yaml`` has ``partial: true`` (a fewer-than-3
     install is allowed only if the agent explicitly recorded the gap).
  7. Each fixture JSON has the required schema fields (``fixture_id``,
     ``input``, ``golden_outputs``).
  8. ``protocol_version`` is ``"0.4"`` everywhere it appears.

What it does NOT check:
  - That the host evaluator round-trips the fixtures cleanly. That requires
    importing the host's code, which this script intentionally avoids
    (keeps the script dependency-free apart from PyYAML). To do the
    round-trip check, run ``behavioral_equivalence.py`` directly with
    ``--evaluator <module.path>:<fn>`` after this passes.
  - The contents of materialized configs beyond placeholder absence. The
    questionnaire's drift checker enforces template-side correctness; this
    script enforces host-side completeness.

Exit codes:
    0 = all checks pass
    1 = one or more checks failed (printed report)
    2 = invocation error (host root doesn't exist, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]


REQUIRED_CONFIG_FILES = [
    "metrics.yaml",
    "enforcement.yaml",
    "protected_paths.yaml",
    "editable_paths.yaml",
]

REQUIRED_ANSWER_KEYS = ["protocol_version", "bootstrapped_at", "bootstrapped_by", "answers"]

REQUIRED_MANIFEST_TOP_KEYS = [
    "snapshot_id",
    "val_set_version",
    "train",
    "val",
    "test",
    "frozen_at",
    "frozen_by",
]

REQUIRED_MANIFEST_SPLIT_KEYS = ["path", "sha256", "size_bytes"]

REQUIRED_FIXTURE_KEYS = ["fixture_id", "input", "golden_outputs"]

EXPECTED_PROTOCOL_VERSION = "0.4"

MIN_FIXTURES = 3


def report(passed: bool, name: str, detail: str = "") -> tuple[bool, str]:
    """Format a check result line."""
    mark = "PASS" if passed else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line = f"{line} — {detail}"
    return passed, line


def check_autoresearch_dir(host_root: Path) -> tuple[bool, str]:
    """Check #1."""
    p = host_root / "autoresearch"
    if p.is_dir():
        return report(True, "autoresearch/ directory exists")
    return report(False, "autoresearch/ directory exists", f"missing: {p}")


def check_config_files_materialized(host_root: Path) -> list[tuple[bool, str]]:
    """Check #2: all four config files copied from .example to .yaml."""
    results: list[tuple[bool, str]] = []
    config_dir = host_root / "autoresearch" / "config"
    for f in REQUIRED_CONFIG_FILES:
        p = config_dir / f
        if p.is_file():
            results.append(report(True, f"config materialized: {f}"))
        else:
            results.append(
                report(False, f"config materialized: {f}", f"missing: {p}")
            )
    return results


def check_no_fill_me(host_root: Path) -> list[tuple[bool, str]]:
    """Check #3: no <FILL_ME> in any materialized config."""
    results: list[tuple[bool, str]] = []
    config_dir = host_root / "autoresearch" / "config"
    for f in REQUIRED_CONFIG_FILES:
        p = config_dir / f
        if not p.is_file():
            continue  # already reported as a missing-file failure
        text = p.read_text()
        if "<FILL_ME>" in text:
            n = text.count("<FILL_ME>")
            results.append(
                report(False, f"no <FILL_ME> in {f}", f"{n} placeholder(s) remain")
            )
        else:
            results.append(report(True, f"no <FILL_ME> in {f}"))
    return results


def check_bootstrap_answers(host_root: Path) -> tuple[bool, str]:
    """Check #4: bootstrap-answers.yaml exists with required frontmatter."""
    p = host_root / "autoresearch" / "bootstrap-answers.yaml"
    if not p.is_file():
        return report(False, "bootstrap-answers.yaml exists", f"missing: {p}")
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        return report(False, "bootstrap-answers.yaml exists", f"YAML parse error: {e}")
    if not isinstance(data, dict):
        return report(
            False,
            "bootstrap-answers.yaml schema",
            f"top-level must be a mapping, got {type(data).__name__}",
        )
    missing = [k for k in REQUIRED_ANSWER_KEYS if k not in data]
    if missing:
        return report(
            False,
            "bootstrap-answers.yaml schema",
            f"missing required keys: {missing}",
        )
    return report(True, "bootstrap-answers.yaml exists with required frontmatter")


def check_manifest(host_root: Path) -> list[tuple[bool, str]]:
    """Check #5: data/splits/MANIFEST.json exists with §6.3.1 fields."""
    results: list[tuple[bool, str]] = []
    p = host_root / "data" / "splits" / "MANIFEST.json"
    if not p.is_file():
        results.append(report(False, "MANIFEST.json exists", f"missing: {p}"))
        return results
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        results.append(report(False, "MANIFEST.json parses", str(e)))
        return results
    if not isinstance(data, dict):
        results.append(
            report(
                False,
                "MANIFEST.json schema",
                f"top-level must be a mapping, got {type(data).__name__}",
            )
        )
        return results
    results.append(report(True, "MANIFEST.json exists and parses"))
    missing = [k for k in REQUIRED_MANIFEST_TOP_KEYS if k not in data]
    if missing:
        results.append(
            report(False, "MANIFEST.json top-level fields", f"missing: {missing}")
        )
    else:
        results.append(report(True, "MANIFEST.json top-level fields"))
    for split in ("train", "val", "test"):
        split_data = data.get(split)
        if not isinstance(split_data, dict):
            results.append(
                report(
                    False,
                    f"MANIFEST.json {split} schema",
                    f"expected mapping, got {type(split_data).__name__}",
                )
            )
            continue
        missing = [k for k in REQUIRED_MANIFEST_SPLIT_KEYS if k not in split_data]
        if missing:
            results.append(
                report(
                    False,
                    f"MANIFEST.json {split} schema",
                    f"missing required keys: {missing}",
                )
            )
        else:
            results.append(report(True, f"MANIFEST.json {split} schema"))
    return results


def check_fixtures(host_root: Path, allow_partial: bool) -> list[tuple[bool, str]]:
    """Checks #6 and #7."""
    results: list[tuple[bool, str]] = []
    fixtures_dir = host_root / "evaluation" / "fixtures"
    if not fixtures_dir.is_dir():
        results.append(
            report(False, "evaluation/fixtures/ exists", f"missing: {fixtures_dir}")
        )
        return results
    files = sorted(fixtures_dir.glob("*.json"))
    n = len(files)
    if n == 0:
        results.append(
            report(False, "fixtures present", "no *.json files in evaluation/fixtures/")
        )
        return results
    if n < MIN_FIXTURES and not allow_partial:
        results.append(
            report(
                False,
                f"≥{MIN_FIXTURES} fixtures (or partial flag)",
                f"found {n}; record `partial: true` in bootstrap-answers.yaml "
                f"or add more fixtures",
            )
        )
    else:
        suffix = " (partial bootstrap)" if n < MIN_FIXTURES else ""
        results.append(
            report(True, f"fixture count ≥{MIN_FIXTURES}{suffix}", f"{n} fixture(s)")
        )
    for fp in files:
        try:
            data = json.loads(fp.read_text())
        except json.JSONDecodeError as e:
            results.append(report(False, f"fixture parses: {fp.name}", str(e)))
            continue
        if not isinstance(data, dict):
            results.append(
                report(
                    False,
                    f"fixture schema: {fp.name}",
                    f"top-level must be a mapping, got {type(data).__name__}",
                )
            )
            continue
        missing = [k for k in REQUIRED_FIXTURE_KEYS if k not in data]
        if missing:
            results.append(
                report(
                    False,
                    f"fixture schema: {fp.name}",
                    f"missing required keys: {missing}",
                )
            )
        else:
            results.append(report(True, f"fixture schema: {fp.name}"))
    return results


def check_protocol_version(host_root: Path) -> list[tuple[bool, str]]:
    """Check #8: protocol_version is "0.4" everywhere it appears."""
    results: list[tuple[bool, str]] = []
    config_dir = host_root / "autoresearch" / "config"
    candidates = [
        config_dir / "metrics.yaml",
        config_dir / "enforcement.yaml",
        config_dir / "protected_paths.yaml",
        config_dir / "editable_paths.yaml",
        host_root / "autoresearch" / "bootstrap-answers.yaml",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            data = yaml.safe_load(p.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        version = data.get("protocol_version")
        rel = p.relative_to(host_root)
        if version == EXPECTED_PROTOCOL_VERSION:
            results.append(report(True, f"protocol_version=0.4 in {rel}"))
        elif version is None:
            results.append(
                report(False, f"protocol_version present in {rel}", "missing")
            )
        else:
            results.append(
                report(
                    False,
                    f"protocol_version=0.4 in {rel}",
                    f"found {version!r}",
                )
            )
    return results


def maybe_partial(host_root: Path) -> bool:
    """Read bootstrap-answers.yaml for `partial: true` (best-effort)."""
    p = host_root / "autoresearch" / "bootstrap-answers.yaml"
    if not p.is_file():
        return False
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("partial", False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "End-of-bootstrap smoke test for the host repo. Exits 0 on all "
            "checks pass, 1 on any failure, 2 on invocation error."
        ),
    )
    parser.add_argument(
        "host_root",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to the host repo root (default: cwd).",
    )
    args = parser.parse_args()
    host_root = args.host_root.resolve()
    if not host_root.is_dir():
        print(f"error: host root {host_root} does not exist")
        return 2

    print(f"bootstrap_verify: checking {host_root}")
    print()
    all_results: list[tuple[bool, str]] = []

    all_results.append(check_autoresearch_dir(host_root))
    all_results.extend(check_config_files_materialized(host_root))
    all_results.extend(check_no_fill_me(host_root))
    all_results.append(check_bootstrap_answers(host_root))
    all_results.extend(check_manifest(host_root))
    all_results.extend(check_fixtures(host_root, allow_partial=maybe_partial(host_root)))
    all_results.extend(check_protocol_version(host_root))

    n_pass = sum(1 for ok, _ in all_results if ok)
    n_fail = len(all_results) - n_pass

    for _, line in all_results:
        print(line)

    print()
    print(f"summary: {n_pass} passed / {n_fail} failed")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
