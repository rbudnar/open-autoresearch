# Changelog

The repo's version tracks the shipped protocol version. Each protocol bump triggers a new repo release. The detailed protocol-level changelog lives in `PROTOCOL.md` §0; this file summarizes repo-level releases.

## Unreleased

- Initial public release in preparation.
- **Provenance (content-addressed, Level 1).** Experiment records now carry `source_commit` + `source_branch` + `resolvable_from_main` instead of requiring resolvable `git_sha_before`/`git_sha_after`. The commit is a non-authoritative breadcrumb; auditability is the structured record. `git_sha_*` are demoted to deprecated-optional (legacy records stay valid; `log_experiment.py` no longer emits them but still accepts the old `--git-sha-*` flags as aliases). Protocol stays 0.5 (back-compat). Design + roadmap: `docs/proposals/2026-06-13-provenance-redesign.md`, decision `docs/adr/0001-content-addressed-provenance.md`. Origin: ActivityEncoder PR #93 dangling-commit blocker. Levels 2-3 (run-time code/data/env capture + reproduce tool) are future work.
  Provenance presence is enforced by a schema `anyOf` (full triple OR the legacy `git_sha_*` pair — no provenance-less/partial records), and the in-repo example campaigns are migrated to the new triple (content-addressed references recomputed in lock-step) so the whole repo models one shape.

## v0.4.0 — 2026-05-18

**Protocol shipped:** AutoResearch++ v0.4 (final pre-1.0 candidate)

Initial public release. Ships:

- `PROTOCOL.md` (1700+ lines, 26 sections)
- `template/autoresearch/` scaffolding (configs, markdown templates)
- `template/scripts/` reference Python tooling (behavioral-equivalence, promotion verifier)
- Two complete example campaigns: `examples/level1-success/` and `examples/level3-counter-example/`
- Documentation: adoption levels, threat model, related work, FAQ
- Dogfooded CI: `CODEOWNERS` + `.github/workflows/protect-protocol.yml` + `.github/workflows/validate-examples.yml`

### Protocol highlights (v0.4)

- Direction-aware statistical decision rule (§13.2.1) — handles both maximize and minimize metrics correctly.
- Tolerance-based behavioral-equivalence check (§17.1.1) — `rtol`/`atol` declared per metric, per dtype.
- Out-of-band enforcement requirement (§3.1.1) — honesty disclaimer when host runs `mechanism: none`.
- Promotion request / promotion packet split (§10.5) — agent emits a request; non-agent verifier signs the packet.
- Namespaced result labels (`level1_branch_winner`, `level2_branch_winner`, `branch_winner`) so external readers can tell evidence quality at a glance.
- Validation-set exposure budget (§17.6) — every read of held-out val is accounted for.
- LLM / tool-call / compute budgets (§17.7) — per-level caps for L1–L5.

### Pre-v0.4 history

Earlier protocol versions (v0.1 / v0.2 / v0.3) were internal drafts. Their changelog and rationale are preserved in `PROTOCOL.md` §0 (changelog) and `MIGRATION.md`.

---

This file follows [Keep a Changelog](https://keepachangelog.com/) loosely. Semver follows the protocol per `PROTOCOL.md` §0.
