# HEB Harness Bootstrap Plan

status: active
owner: human
created: 2026-06-25
updated: 2026-06-25
source: Harness Engineering Bootstrap 0.1.0
next_action: run final local validation, then start ship-pr review flow
validation_command: python scripts/quality_gate.py
stop_condition: bootstrap PR passes local gates, spec-alignment review, and ship-pr checks
supersedes: none
superseded_by: none
retirement_or_revisit: retire after the bootstrap PR merges and docs/harness-version.json records accepted controls on main

## Bootstrapper Evidence

Official package path attempted:

```bash
npm exec --yes --package "github:rbudnar/harness-engineering-bootstrap#v0.1.0" -- harness-bootstrap init --repo <repo> --json
```

Result: failed before execution because the `v0.1.0` tag does not contain
`package.json`.

Installable package-bin path run:

```bash
npm exec --yes --package "github:rbudnar/harness-engineering-bootstrap#main" -- harness-bootstrap init -- --repo <repo> --json
```

Direct checkout fallback run:

```bash
node <heb-checkout>/scripts/harness-bootstrap-plan.mjs init --repo <repo> --json
```

Both successful runs emitted a first-time bootstrap plan with planner version
`0.1.0` and target version `0.1.0`.

## Accepted Core Work

- Thin always-on entrypoint: root `AGENTS.md`.
- Task router: `docs/README.md`.
- Architecture orientation: `docs/architecture.md`.
- Decision memory: existing `docs/adr/` files remain the decision source.
- Testing and validation docs: `docs/testing.md`.
- CI/CD routing: workflow notes in `docs/testing.md`, with protected paths in
  `.github/workflows/protect-protocol.yml`.
- Human guide: existing `CONTRIBUTING.md`.
- Quality gate: `scripts/quality_gate.py`.
- Harness validation: `scripts/check_repo_harness.py` wired into CI.
- Minimal local metrics baseline: `scripts/harness_metrics.py` and
  `docs/harness-metrics-baseline.json`.
- Weekly quality report: `scripts/weekly_quality_report.py` and
  `.github/workflows/weekly-quality-report.yml`.
- Bootstrap metadata: `docs/harness-version.json`.

## Rejected Or Deferred Modules

The bootstrapper rejected or deferred these modules because this repo has no
local trigger yet: data contracts, repo contracts, internal data-store docs,
PR workflow metrics, long-running handoff/task contracts, URL context map,
evidence packs, health report, and code-search adapter.

Runtime-safety guidance was accepted because the repo has CI, verifier scripts,
package execution examples, and generated validation artifacts.

## Validation

Required before closing this bootstrap PR:

```bash
python scripts/quality_gate.py
python scripts/harness_metrics.py --baseline docs/harness-metrics-baseline.json
python scripts/weekly_quality_report.py --skip-full-scaffold-tests
```

Known separate portability work: full Windows unittest discovery currently
fails on temp git identity, POSIX path, chmod/unreadable-file, and cp1252
encoding assumptions. That is not part of this bootstrap closure.

## Stop And Retirement

Stop if the official bootstrapper output changes, if repo drift invalidates the
survey, or if a reviewer rejects the accepted/rejected module split.

Retire this active plan after the bootstrap PR merges and `docs/harness-version.json`
records the accepted controls and validation evidence on main. Revisit sooner
if the official bootstrapper output changes or a reviewer rejects the module
split.
