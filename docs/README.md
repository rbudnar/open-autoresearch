# Docs Router

Use this file to choose the smallest useful context for Open-AutoResearch work.
Do not read the entire docs tree by default.

## Repo Maintenance

- Start with `AGENTS.md`, then `docs/dogfooding.md`.
- Use `docs/architecture.md` for repository surfaces and ownership boundaries.
- Use `docs/testing.md` for the canonical quality gate and CI-shaped checks.
- Use `docs/runtime-safety.md` before changing scripts, CI, generated state,
  package execution, or other execution surfaces.
- Use `docs/harness-version.json` to see the accepted HEB bootstrap metadata.
- Use `docs/harness-metrics-baseline.json` for the initial local harness
  metrics baseline.

## Protocol And Template Work

- Protocol semantics: `PROTOCOL.md`, then `MIGRATION.md` for version changes.
- Foundational literature and citation status: `docs/references.md`, then
  `docs/related-work.md` for narrative positioning.
- Template scaffold: `template/README.md`, `template/config/`,
  `template/schema/`, and `template/scripts/`.
- Example campaigns: `examples/README.md`, then the local example README.
- Threat model and adoption levels: `docs/threat-model.md` and
  `docs/adoption-levels.md`.

## Review And Planning

- Human contribution policy: `CONTRIBUTING.md`.
- Active repo-harness plan: `docs/plans/active/2026-06-25-open-autoresearch-harness-bootstrap.md`.
- Architecture decisions: `docs/adr/`.
- Proposals that are not yet protocol law: `docs/proposals/`.

## Canonical Quality Gate

Run the local gate before calling repo-harness, protocol-version, template,
example, verifier, or CI-routing edits done:

```bash
python scripts/quality_gate.py
```

See `docs/testing.md` for focused alternatives and known platform notes.
