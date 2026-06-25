# Repository Instructions

This repo maintains the Open-AutoResearch protocol, template scaffold, examples,
and reference verifier scripts. Treat it as a protocol repository with executable
supporting checks, not as a generic docs site.

## First Reads

- Start with `README.md` for the repo map and current protocol version.
- Use `docs/README.md` as the task router for repo-maintainer docs.
- Read `docs/dogfooding.md` before making protocol, template, example, or
  roadmap changes.
- Use `docs/testing.md` for validation commands and platform notes.
- Use `docs/runtime-safety.md` before changing scripts, workflows, generated
  artifacts, package execution, or verifier trust behavior.
- For host-repo bootstrapping work, use `docs/host-bootstrap-agents.md`.
- For loop-driving agents inside an adopted host project, use `PROTOCOL.md`.

## Work Modes

- **Repo maintainer mode:** editing this repository's protocol, template,
  examples, docs, CI, or scripts. Follow this file plus `docs/dogfooding.md`.
- **Host bootstrap mode:** copying `template/` into another repository. Follow
  `docs/host-bootstrap-agents.md`; do not treat that guide as repo-maintainer
  guidance.
- **Campaign mode:** running an autoresearch campaign in a host project. Follow
  `PROTOCOL.md`; this repo only supplies the scaffold and reference contracts.

## Editing Rules

- Keep `AGENTS.md` as the always-on entrypoint. Move detailed workflows behind
  routed docs instead of expanding this file indefinitely.
- Do not copy protocol sections, bootstrap checklists, literature surveys, or
  template reference material into always-on guidance.
- Protocol semantic changes must consider `PROTOCOL.md`, `MIGRATION.md`,
  `template/`, `examples/`, verifier behavior, and docs together. If only one
  surface changes, explain why the others are unaffected.
- Template/schema/script changes must preserve the language-neutral protocol
  framing. Reference Python remains a reference implementation, not the product.
- Example changes are test-suite changes. Regenerate derived state locally when
  needed, but do not commit derived aggregates.
- Roadmap work should use one parent tracker for coordination and child issues
  only where implementation, risk, or validation differs.
- Imported HEB-style harness ideas must be adapted to this repo. Do not copy a
  whole harness module when a smaller route, check, or doc rule handles the
  observed problem.

## Admission Gate

Any durable repo-harness addition should identify:

- Evidence: the local drift, repeated miss, ambiguity, or review burden.
- Smaller control: why an existing doc, route, or check is not enough.
- Validation: the command, CI check, review step, or artifact that proves it.
- Retirement: when the rule should be weakened, deleted, or revisited.

Reject changes that only make the repo feel more comprehensive without improving
agent routing, protocol consistency, verifier trust, or contributor review.

## Checks

Run the harness check after repo-guidance, protocol-version, template, example,
or workflow edits:

```bash
python scripts/quality_gate.py
```

Use `python scripts/check_repo_harness.py` when you only need the fast
repo-harness invariant check.

For reference-script changes, also run the relevant Python tests under
`template/scripts/tests/` and the help/parse checks from
`.github/workflows/validate-examples.yml`.

For verifier or example changes, run the Level-3 counter-example verifier path
described in `examples/README.md`.
