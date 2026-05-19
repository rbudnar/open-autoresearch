# Contributing to open-autoresearch

Thanks for considering a contribution. This repo's value comes from rigor, so contributions are gated by an explicit RFC flow rather than ad-hoc PRs against `PROTOCOL.md`.

## The artifact hierarchy

| Artifact | Editable by | Review required |
|---|---|---|
| `PROTOCOL.md` | Maintainers only via RFC | Two CODEOWNERS + RFC link in commit message |
| `template/scripts/**` | Maintainers + reviewed contributors | CODEOWNERS approval |
| `template/config/*.example.yaml` | Maintainers + reviewed contributors | CODEOWNERS approval |
| `template/templates/*.md` | Maintainers + reviewed contributors | CODEOWNERS approval |
| `examples/**` | Contributors | One CODEOWNERS approval; validate-examples CI green |
| `docs/**` | Contributors | One maintainer review |
| `README.md`, `MIGRATION.md`, `CHANGELOG.md` | Contributors | One maintainer review |

CI enforces this via `.github/workflows/protect-protocol.yml` per `PROTOCOL.md` §3.1.1. The repo dogfoods its own protocol.

## Proposing a protocol change

Protocol changes require an RFC because `PROTOCOL.md` is the centerpiece artifact. The RFC flow:

1. **Open a GitHub Discussion** under "Protocol RFCs" with: motivation, the specific change(s) you want, why this can't be solved with `docs/` or a module-level update, and at minimum two named alternatives you considered.
2. **Discuss for at least 7 days.** Maintainers and the community will push back, ask for examples, suggest scope reductions.
3. **Reach consensus** with at least one CODEOWNER. Disagreement past 14 days escalates to a "request for benevolent dictator decision."
4. **Open a PR** linking the discussion. The PR includes:
   - The `PROTOCOL.md` diff.
   - A new ADR file under `docs/adr/` (template below).
   - An entry in `MIGRATION.md` if the change is breaking.
   - Updated artifacts in `examples/` if any example becomes invalid.
   - Updated reference scripts in `template/scripts/` if behavior changes.
5. **Two CODEOWNER approvals** required to merge.

## Versioning

The protocol uses semver per `PROTOCOL.md` §0:

- **Major** (1.0 → 2.0): breaking changes. Old artifacts may not load. Requires a `migrate_to_vX.Y.py` script template under `template/scripts/`.
- **Minor** (0.4 → 0.5): additive — new optional fields, sections, examples. Old artifacts continue to validate.
- **Patch** (0.4.0 → 0.4.1): typos, link fixes, wording. No semantic change.

The repo version tracks the protocol version. A protocol patch may ship without a repo release if no scaffolding changed.

## Deprecation

When a section, field, or pattern is deprecated:

1. Add a `**Deprecated in vX.Y:**` line under the relevant subsection in `PROTOCOL.md`.
2. Add an explicit removal target (e.g., "to be removed in v0.6").
3. Update affected `template/` files to emit a warning when the deprecated field is used.
4. Add a `MIGRATION.md` entry describing the replacement.

Deprecation requires the same RFC flow as a regular protocol change.

## Reference-implementation contributions

The reference Python scripts in `template/scripts/` are *examples* — `PROTOCOL.md` §10.5 is the authoritative spec. We welcome:

- **Ports to other languages** (Go, Rust, Bash). Ship as separate repos; link to them from `docs/related-work.md`.
- **Hardening of the existing Python scripts** (better error messages, more validation, edge case handling).
- **Optional features** (richer signing schemes, additional fixture types, integration tests).

For language ports, do NOT include them in this repo. Maintain them externally so the language-neutral framing of `PROTOCOL.md` stays clean.

## Example campaign contributions

We welcome additional example campaigns for `examples/`, especially:

- A real-data Level-3 campaign on a small public benchmark.
- Campaigns that exercise specific failure modes (data drift, infra preemption, multi-agent contention).
- Campaigns demonstrating uncommon configurations (mixed-precision evaluator, distributed training).

Every example must:

1. Pass `template/scripts/verifier/verify_request.py` (or document the expected rejection reason).
2. Include a README explaining what it teaches.
3. Reference specific `PROTOCOL.md` sections it exercises.

## Code style

- Python: black formatting, mypy strict on `template/scripts/` (no untyped defs, no implicit Any).
- Markdown: GitHub-flavored, line wrap not enforced.
- YAML: 2-space indent.

Run `black template/scripts/` and `mypy template/scripts/` before submitting a PR that touches Python.

## ADR template

```markdown
# ADR-NNNN: <title>

**Status:** Proposed | Accepted | Superseded by ADR-NNNN
**Date:** YYYY-MM-DD
**RFC discussion:** <link>

## Context
What problem are we solving?

## Decision
What we decided.

## Alternatives considered
- Alternative A: <why rejected>
- Alternative B: <why rejected>

## Consequences
- Positive: ...
- Negative: ...
- Migration: ...
```

## Code of conduct

Be technical, be specific, be kind. Disagreement is welcome; bad-faith argument is not. Maintainers may close discussions or PRs that violate this without explanation.

## Maintainers

See `CODEOWNERS` for the current maintainer list.
