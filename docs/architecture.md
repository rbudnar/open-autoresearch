# Architecture Notes

Open-AutoResearch is a protocol repository with reference verification
machinery. It is not an application runtime or installable framework.

## Repository Surfaces

- `PROTOCOL.md` is the normative protocol specification.
- `MIGRATION.md` explains how active protocol versions change.
- `template/` is the scaffold adopters copy into a host project as
  `autoresearch/`.
- `template/scripts/` contains reference Python implementations for verifier,
  ledger, behavioral-equivalence, and bootstrap checks.
- `template/schema/` contains machine-readable protocol contracts.
- `examples/` contains committed campaign source artifacts used as regression
  fixtures for the reference scripts.
- Derived example aggregates under `examples/**/state/` are regenerated from
  `state/ledger/*.json` and must stay ignored.
- `.github/workflows/` enforces protocol, drift, ledger, and example checks.
- `scripts/` contains repo-maintainer harness checks, not adopter runtime code.

## Ownership Boundaries

Protocol semantics usually require cross-surface review. Before changing a
rule, check whether `PROTOCOL.md`, `MIGRATION.md`, `template/`, `examples/`,
reference scripts, docs, and workflows must move together.

Reference Python is a portability aid, not the product boundary. Keep the
protocol language-neutral unless a script implements a specific verifier or
ledger contract.

## State Model

Protocol 0.5 uses immutable source records in `state/ledger/<id>.json`.
`experiment_ledger.jsonl`, `research_tree.json`, `val_exposure.json`, and
`INDEX.md` are derived views. Regenerate them for validation, but do not commit
them.

## Harness Layer

The repo harness is intentionally thin:

- `AGENTS.md` is the always-on maintainer entrypoint.
- `docs/README.md` routes task context.
- `docs/dogfooding.md` defines the HEB-style admission gate.
- `scripts/check_repo_harness.py` validates harness invariants.
- `scripts/quality_gate.py` runs the canonical local validation subset.
