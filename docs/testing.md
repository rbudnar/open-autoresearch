# Testing And Validation

The reference verifier scripts need PyYAML. In a fresh environment, install it
before running the local gate:

```bash
python -m pip install pyyaml
```

The canonical local quality gate is:

```bash
python scripts/quality_gate.py
```

Run it after repo-harness, protocol-version, template, example, verifier, or CI
routing changes. It runs the repo harness check, committed PR/base whitespace
checks when a diff range is available, staged and working-tree `git diff
--check`, reference script parse/help checks, example protocol-version checks,
the PR Agent Inbox node tests, and the Level-3 counter-example verifier
rejection path.

## Focused Checks

- Repo harness only: `python scripts/check_repo_harness.py`
- Protocol bump dry run: `python scripts/bump_protocol_version.py <new-version> --dry-run`
- Minimal harness metrics: `python scripts/harness_metrics.py --baseline docs/harness-metrics-baseline.json`
- Reference script parse check: `python scripts/quality_gate.py --skip-verifier`
- PR Agent Inbox tests: `node --test scripts/pr-agent-inbox.test.mjs`
- Level-3 verifier regression: `python scripts/quality_gate.py --only-verifier`
- Full scaffold unit discovery: `python -m unittest discover -s template/scripts/tests -p "test_*.py"`
- Generate a local weekly report: `python scripts/weekly_quality_report.py --skip-full-scaffold-tests`

## CI Mapping

- `.github/workflows/protect-protocol.yml` runs the repo harness check and
  protocol-version consistency checks for protected surfaces.
- `.github/workflows/check-drift.yml` checks questionnaire/config drift.
- `.github/workflows/validate-examples.yml` checks reference script parsing,
  help output, and the Level-3 rejected verifier path.
- `.github/workflows/validate-ledger.yml` checks example ledger records and the
  reference script unit suites.
- `.github/workflows/pr-agent-inbox-signal.yml` is a permissionless hosted
  no-op for review and review-comment events. Its completed run asks the
  default-branch-owned publisher to re-read current GitHub state; no PR code or
  producer artifacts cross that boundary.
- `.github/workflows/pr-agent-inbox.yml` updates the inbox only from exact PR
  lifecycle events, an authorized exact `/agent-inbox refresh` comment, a
  default-branch manual dispatch, or completed runs from the four validation
  workflows and the signal workflow. It has no schedule, status, or check-run
  trigger. A blank manual dispatch performs a draft-inclusive, default-base
  sweep and refuses more than 100 open PRs rather than publishing a partial
  result.
- `.github/workflows/weekly-quality-report.yml` runs every Monday, uploads
  JSON/Markdown report artifacts, comments on a standing report issue, opens or
  updates a problem issue when checks fail, and then fails the workflow when
  problems were found.

## Platform Notes

The CI suites are Linux-oriented. On this Windows machine, full unittest
discovery currently exposes portability failures around temporary git identity,
POSIX path expectations, chmod/unreadable-file assumptions, and cp1252 console
encoding. Treat those as separate portability work; do not use them to weaken
the repo harness gate.

GitHub can suppress or delay fork review workflows, and Actions has no
review-thread trigger. Native GitHub review gates remain authoritative. The
inbox converges through an admitted signal run, the exact authorized refresh
comment, a PR-specific manual dispatch, the bounded blank dispatch, or the next
admitted event; it does not claim instantaneous convergence for every fork
review or thread change.
