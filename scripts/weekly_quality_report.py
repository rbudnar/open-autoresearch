#!/usr/bin/env python3
"""Generate a weekly Open-AutoResearch quality report.

The command exits zero after writing the report so scheduled workflows can
upload artifacts and create/comment issues before a later workflow step fails
on detected problems.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CheckSpec:
    id: str
    name: str
    command: list[str]
    display: str


DEFAULT_CHECKS = [
    CheckSpec(
        id="quality-gate",
        name="Quality gate",
        command=[sys.executable, "scripts/quality_gate.py"],
        display="python scripts/quality_gate.py",
    ),
    CheckSpec(
        id="repo-harness",
        name="Repo harness invariants",
        command=[sys.executable, "scripts/check_repo_harness.py"],
        display="python scripts/check_repo_harness.py",
    ),
    CheckSpec(
        id="harness-metrics",
        name="Harness metrics baseline",
        command=[sys.executable, "scripts/harness_metrics.py", "--baseline", "docs/harness-metrics-baseline.json"],
        display="python scripts/harness_metrics.py --baseline docs/harness-metrics-baseline.json",
    ),
    CheckSpec(
        id="weekly-quality-report-tests",
        name="Weekly quality report tests",
        command=[sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_*.py"],
        display='python -m unittest discover -s scripts/tests -p "test_*.py"',
    ),
    CheckSpec(
        id="full-scaffold-tests",
        name="Full scaffold tests",
        command=[
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "template/scripts/tests",
            "-p",
            "test_*.py",
        ],
        display='python -m unittest discover -s template/scripts/tests -p "test_*.py"',
    ),
]


def default_output_dir(env: dict[str, str] | None = None) -> str:
    if env is None:
        env = os.environ
    if env.get("GITHUB_ACTIONS") == "true":
        return ".harness"
    return str(Path(tempfile.gettempdir()) / "open-autoresearch-weekly-quality-report")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a weekly quality report.")
    parser.add_argument("--repo", default=str(REPO_ROOT), help="Repository to check.")
    parser.add_argument("--output-dir", default=default_output_dir(), help="Directory for JSON/Markdown reports.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Report date, YYYY-MM-DD.")
    parser.add_argument(
        "--skip-full-scaffold-tests",
        action="store_true",
        help="Skip full template/scripts unittest discovery.",
    )
    return parser.parse_args(argv)


def run_check(spec: CheckSpec, repo: Path) -> dict[str, object]:
    started = time.perf_counter()
    proc = subprocess.run(
        spec.command,
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "id": spec.id,
        "name": spec.name,
        "command": spec.display,
        "exitCode": proc.returncode,
        "durationMs": duration_ms,
        "passed": proc.returncode == 0,
        "stdoutTail": tail(proc.stdout),
        "stderrTail": tail(proc.stderr),
    }


def build_report(
    check_results: list[dict[str, object]],
    report_date: str,
    repository: str | None = None,
    run_url: str | None = None,
    commit: str | None = None,
) -> dict[str, object]:
    failed = [check for check in check_results if not check["passed"]]
    return {
        "kind": "open-autoresearch-weekly-quality-report",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": report_date,
        "repository": repository,
        "commit": commit,
        "run_url": run_url,
        "summary": {
            "hasProblems": bool(failed),
            "failedCheckCount": len(failed),
        },
        "checks": check_results,
    }


def render_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    status = "Problems detected" if summary["hasProblems"] else "No problems detected"
    lines = [
        "# Weekly Quality Report",
        "",
        f"Status: {status}",
        f"Date: {report['date']}",
    ]
    if report.get("repository"):
        lines.append(f"Repository: {report['repository']}")
    if report.get("commit"):
        lines.append(f"Commit: {report['commit']}")
    if report.get("run_url"):
        lines.append(f"Workflow run: {report['run_url']}")

    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Status | Duration | Command |",
            "|---|---:|---:|---|",
        ]
    )
    for check in report["checks"]:
        check_status = "ok" if check["passed"] else f"failed ({check['exitCode']})"
        lines.append(
            f"| {escape_cell(check['name'])} | {check_status} | "
            f"{format_duration(check['durationMs'])} | `{escape_cell(check['command'])}` |"
        )

    failed = [check for check in report["checks"] if not check["passed"]]
    if failed:
        lines.extend(["", "## Failed Check Output", ""])
        for check in failed:
            lines.extend([f"### {check['name']}", ""])
            if check["stderrTail"]:
                lines.extend(["```text", str(check["stderrTail"]), "```", ""])
            if check["stdoutTail"]:
                lines.extend(["```text", str(check["stdoutTail"]), "```", ""])
            if not check["stderrTail"] and not check["stdoutTail"]:
                lines.extend(["- No output captured.", ""])

    lines.extend(["", "## Next Action", ""])
    if summary["hasProblems"]:
        lines.append("- Inspect the failed checks and open or update the quality problem issue.")
    else:
        lines.append("- No action needed.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, object], repo: Path, output_dir: str) -> tuple[Path, Path]:
    out = Path(output_dir)
    if not out.is_absolute():
        out = repo / out
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "weekly-quality-report.json"
    md_path = out / "weekly-quality-report.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def write_github_outputs(report: dict[str, object], json_path: Path, md_path: Path, repo: Path) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"has_problems={'true' if report['summary']['hasProblems'] else 'false'}\n")
        handle.write(f"report_json={slash(json_path.relative_to(repo))}\n")
        handle.write(f"report_md={slash(md_path.relative_to(repo))}\n")


def github_run_url(env: dict[str, str] | None = None) -> str | None:
    env = env or os.environ
    server = env.get("GITHUB_SERVER_URL")
    repo = env.get("GITHUB_REPOSITORY")
    run_id = env.get("GITHUB_RUN_ID")
    if not server or not repo or not run_id:
        return None
    return f"{server}/{repo}/actions/runs/{run_id}"


def tail(text: str, max_lines: int = 40) -> str:
    lines = [line for line in text.rstrip().splitlines() if line]
    return "\n".join(lines[-max_lines:])


def format_duration(duration_ms: object) -> str:
    if not isinstance(duration_ms, int | float):
        return "unknown"
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    return f"{duration_ms / 1000:.1f}s"


def escape_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def slash(path: Path) -> str:
    return str(path).replace("\\", "/")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).resolve()
    checks = [check for check in DEFAULT_CHECKS if check.id != "full-scaffold-tests" or not args.skip_full_scaffold_tests]
    results = [run_check(check, repo) for check in checks]
    report = build_report(
        results,
        args.date,
        repository=os.environ.get("GITHUB_REPOSITORY"),
        run_url=github_run_url(),
        commit=os.environ.get("GITHUB_SHA"),
    )
    json_path, md_path = write_report(report, repo, args.output_dir)
    write_github_outputs(report, json_path, md_path, repo)
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
