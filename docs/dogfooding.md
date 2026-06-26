# Dogfooding Open-AutoResearch

This repository dogfoods its own protocol and borrows selectively from
Harness Engineering Bootstrap. Success means agents can work here with the
right context and mechanical checks, without turning the repo into a heavy
runtime or a grab bag of optional process.

## Always-On Context

`AGENTS.md` is the repo-maintainer entrypoint. It should route agents to the
right source of truth, not duplicate it.

Keep detailed workflows behind routed files:

- `docs/host-bootstrap-agents.md` for one-shot host-repo bootstrap.
- `docs/README.md` for repo-maintainer task routing.
- `docs/architecture.md` for repository surface and boundary orientation.
- `docs/testing.md` for validation commands and CI mapping.
- `docs/runtime-safety.md` for execution-surface guidance.
- `PROTOCOL.md` for campaign behavior and protocol semantics.
- `CONTRIBUTING.md` for human contribution and RFC policy.
- `examples/` for campaign artifacts that double as test fixtures.

Provider-specific adapters may be added only when a provider surface cannot load
`AGENTS.md` directly. They must point back to `AGENTS.md` and stay thin.

## Change Admission

Use the HEB-style gate for durable repo-harness additions:

- **Evidence:** name the local drift, repeated miss, route ambiguity, stale doc,
  review burden, or consistency failure.
- **Smaller control:** explain why an existing route, doc edit, issue comment,
  or current check is insufficient.
- **Validation:** name the command, CI check, artifact, review step, or example
  that will show whether the change works.
- **Retirement or revisit:** say when the rule should be weakened, deleted, or
  reconsidered.

Reject additions that merely make Open-AutoResearch more comprehensive. A
useful harness change improves agent routing, protocol consistency, verifier
trust, template/example synchronization, or roadmap hygiene.

## Cross-Surface Sync

Treat protocol work as cross-surface by default. Before calling a change done,
check whether it affects:

- `PROTOCOL.md` semantics or section references.
- `MIGRATION.md` and versioning policy.
- `template/PROTOCOL_VERSION`, schemas, config examples, or templates.
- `template/scripts/**`, especially verifier or ledger behavior.
- `examples/**` source records, reports, or expected verifier outcomes.
- `README.md`, `examples/README.md`, `template/README.md`, and related docs.
- `.github/workflows/**` and `CODEOWNERS`.
- `docs/harness-version.json` and active `docs/plans/` artifacts when the
  repo harness itself changes.
- `docs/harness-metrics-baseline.json` when metrics, validation, docs routing,
  or CI-reporting surfaces change.

If one of those surfaces does not need a change, say why in the PR summary.

## Version And Ledger Drift

Protocol 0.5 uses sharded immutable ledger records under `state/ledger/`.
Derived files such as `experiment_ledger.jsonl`, `research_tree.json`,
`val_exposure.json`, and `INDEX.md` are regenerated, not committed.

Do not reintroduce Protocol 0.4 active guidance such as `ledger_rotation` config
or instructions to rotate the ledger. Historical migration notes may mention
v0.4, but active quickstarts, templates, and examples should describe v0.5.

## Roadmap Hygiene

Broad roadmap work should use:

- one parent tracker for coordination;
- child issues when implementation, risk, dependency, or validation differs;
- explicit dependencies instead of hidden sequencing assumptions;
- acceptance criteria that name the expected artifact or decision.

For HEB-related work, keep the two directions distinct:

- importing HEB-style harness discipline into this repo;
- evaluating Open-AutoResearch as a campaign protocol for HEB.

## Review Posture

When review finds repeated issues in one defect family, stop point-fixing and
add a compact rule, check, or regression fixture for the underlying model.

Prefer tightening, routing, or validating existing guidance before adding new
always-on instructions. The best outcome may be deleting stale guidance or
marking a proposed addition as not worth its context cost.

## Quality Gate

Run:

```bash
python scripts/quality_gate.py
```

Use `python scripts/check_repo_harness.py` for the fast invariant subset. The
full quality gate adds the minimal harness metrics baseline, reference-script
parse/help checks, and the Level-3 counter-example verifier regression.
