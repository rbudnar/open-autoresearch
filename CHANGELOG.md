# Changelog

The repo's version tracks the shipped protocol version. Each protocol bump triggers a new repo release. The detailed protocol-level changelog lives in `PROTOCOL.md` §0; this file summarizes repo-level releases.

## Unreleased

- Initial public release in preparation.
- **Coordinator/executor boundary (§5.8 / §21.2).** The protocol now defines a one-hypothesis handoff from Research Director to Implementation Worker: approved proposal, frozen hypothesis, one switch or explicit stack label, editable/protected paths, budget cap, evaluator commands, expected artifacts, and achieved separation level. Result reports now have a matching executor-return shape for changed files, commands, metrics, artifacts, boundary deviations, and ledger-ready fields. This is backward-compatible guidance and does not add a scheduler, orchestrator, Python runner, or required host runtime. Decision: `docs/adr/0006-coordinator-executor-boundary.md`.
- **Propagated branch insights (§14.1 / §14.4 / §15).** Experiment records now accept optional `branch_insights[]` entries that separate raw observations from interpreted branch constraints, trace each propagated lesson to source/review ledger ids, and identify affected parent/root nodes. `regenerate_state.py` derives `research_tree.json.views.branch_insights` indexes by source record, affected parent, validated constraint, and invalidated idea. `validate_ledger.py`, `log_experiment.py`, and the promotion verifier validate the optional fields when present. Protocol stays 0.5; existing records require no migration. Decision: `docs/adr/0005-propagated-branch-insights.md`.
- **Operational research tree fields (§14.1 / §15).** Experiment records now accept optional lifecycle/frontier fields (`lifecycle_status`, `promotion_status`, `frontier_eligible`, `blocked_by`, `pruned_reason`, `merged_into`, `node_type`). `regenerate_state.py` derives `research_tree.json.views` for lineage order, active frontier, blocked/pruned/merged nodes, and promotion candidates by maturity. `validate_ledger.py` and the promotion verifier check the optional fields when present. Protocol stays 0.5; existing records require no migration. Decision: `docs/adr/0004-operational-research-tree.md`.
- **Provenance (content-addressed, Level 1).** Experiment records now carry `source_commit` + `source_branch` + `resolvable_from_main` instead of requiring resolvable `git_sha_before`/`git_sha_after`. The commit is a non-authoritative breadcrumb; auditability is the structured record. `git_sha_*` are demoted to deprecated-optional (legacy records stay valid; `log_experiment.py` no longer emits them but still accepts the old `--git-sha-*` flags as aliases). Protocol stays 0.5 (back-compat). Design + roadmap: `docs/proposals/2026-06-13-provenance-redesign.md`, decision `docs/adr/0001-content-addressed-provenance.md`. Origin: ActivityEncoder PR #93 dangling-commit blocker. Levels 2-3 (run-time code/data/env capture + reproduce tool) are future work.
  Provenance presence is enforced by a schema `anyOf` (full triple OR the legacy `git_sha_*` pair — no provenance-less/partial records), and the in-repo example campaigns are migrated to the new triple (content-addressed references recomputed in lock-step) so the whole repo models one shape.
- **Declarative data splits + comparison-set identity (§6.3.1).** `data/splits/MANIFEST.json` gains a second `mode` alongside the current frozen files: `mode: declarative` pins a deterministic split rule (`split_key`, ratio/cutoff, temporal OOS window) + `seed` + `dataset_fingerprint` whose identity is `(source, version, date_window)` (required) with optional `row_count` + `schema_hash` strengtheners — Guard B from the provenance redesign promoted into §6.3.1 — for datasets that grow and make frozen parquet stale immediately. A growing/forward-moving dataset is identified by its **date range alone** (a continuously-appended source cannot pin a stable `row_count`); `row_count`/`schema_hash` are added only when a campaign pins a fixed snapshot (they fail closed when present-but-degenerate and fold into the rule-11 comparison identity). **Frozen stays the recommended default** (immutable, agent-can't-regenerate); declarative is first-class but weaker, so the threat model + §6.3.1 recommend frozen or a non-agent materialization for deployment-grade. Closes the latent "same comparison set" gap: experiment records carry an OPTIONAL `data_fingerprint` split identity, and a new non-failing verifier rule `11_comparison_set_identity` sets a `cross_dataset` warning on the packet when a baseline/candidate pair's splits diverge — **warn, not gate**; the implementer chooses the evidence tier and a divergent split is never silently treated as comparable. Protocol stays 0.5 (back-compat: manifest `anyOf` includes the frozen form; the record identity field is optional, not via anyOf, so existing records stay valid). No data migration — records are zero-touch — but existing frozen manifests need a one-line `mode: frozen` add (a manifest with no `mode` now fails closed, by design); see `MIGRATION.md`. Design + roadmap: `docs/proposals/2026-06-16-dynamic-splits.md`, decision `docs/adr/0002-declarative-data-splits.md`. Origin: OutcomePredictor PR #1021 growing-dataset blocker.

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
