# Adoption levels — concrete starter file checklists

`PROTOCOL.md` §24 defines five maturity levels. This doc maps each level to the concrete files your host project needs and what changes between levels.

## Decision tree

```text
Do you have an existing autoresearch/ directory?
├─ No: start at Level 1.
├─ Yes, but no Skeptic or ablation:                stay at Level 1 or 2.
├─ Yes, with Skeptic AND ablation AND verifier:    Level 3.
├─ Plus all 7 roles with Level-2 separation:       Level 4.
└─ Plus self-improving search policy:              Level 5.
```

Do not skip levels. The §24 promotion ceiling is the only thing that catches "we feel good about this, let's ship" reasoning before it ships.

## Level 1 — Safe autoresearch (exploration mode)

**Promotion ceiling:** `level1_branch_winner`. Cannot reach `promoted`.

**Starter files** (copy from `template/` and fill in):

- `autoresearch/PROTOCOL_VERSION` = `0.5`
- `autoresearch/config/metrics.yaml` — cost tier, primary metric (with direction/aggregation/eval_dtype), guardrails, val_set_exposure_budget, budgets
- `autoresearch/config/enforcement.yaml` — pick a §3.1.1 mechanism (or `none` and accept the in-band-only label)
- `autoresearch/config/editable_paths.yaml` + `protected_paths.yaml`
- `autoresearch/state/` — empty; agent fills during the campaign
- `autoresearch/scripts/behavioral_equivalence.py` — copy as-is from template
- `autoresearch/templates/proposal_template.md`, `result_report_template.md`
- `data/splits/MANIFEST.json` — split content hashes (§6.3.1)
- `evaluation/fixtures/` — at least 3-5 golden fixtures (§17.1.1)
- `evaluation/metric_defs.py` — your locked metric code

**Adoption time:** ~30 minutes on a clean host project, per §1.5 acceptance criterion.

**You'll iterate on:** proposals, reports, ledger entries, the playbook. Everything else is set at bootstrap and stays put.

## Level 2 — Literature-informed

Adds the Literature Scout role.

**Additional starter files:**

- `autoresearch/literature/canon.bib` — at minimum, your domain's canonical references (replace the `canon.bib.example`)
- `autoresearch/literature/briefs/` — populated by the Scout, not by hand
- `autoresearch/templates/literature_review_template.md`

**Promotion ceiling:** still `level2_branch_winner`. Literature backing strengthens candidates but doesn't substitute for ablation.

**Adoption time over Level 1:** ~1 hour (mostly building the canon).

## Level 3 — Tree-search autoresearch (first level that can `promote`)

Adds ablation discipline, Skeptic role, verifier-signed promotion packets.

**Additional starter files:**

- `autoresearch/scripts/verifier/verify_request.py` (copy from template)
- `autoresearch/scripts/verifier/sign_packet.py` (copy from template)
- `autoresearch/templates/promotion_request_template.md`, `promotion_packet_template.md`, `skeptic_review_template.md`
- A **non-agent verifier identity**: a CI job, a deterministic verification script run by a human, or a designated reviewer. The verifier MUST have access to a signing key the agent does not. Without this, you can't actually reach Level 3 — you can run the protocol's Level-3 mechanics but every packet will carry `enforcement: in_band_only`, `not_deployable: true`.
- Skeptic role configured with Level-2 separation from the Implementation Worker (different model family preferred, fresh session minimum).

**Promotion ceiling:** `promoted` / `low_evidence_promoted` (the latter when seed counts are reduced or enforcement is in-band-only).

**Adoption time over Level 2:** ~3-6 hours, mostly CI / verifier setup.

## Level 4 — Multi-agent campaign

Adds the remaining roles (Domain Scout, Experiment Runner, Reflection Analyst), factorial ablation infrastructure, counter-example campaign reporting.

**Additional starter files:**

- `autoresearch/templates/counter_example_report_template.md`
- Operational infrastructure: per-iteration git worktrees, queue-based Ledger Writer, container digests (§17.5)
- Optional: subgroup definitions in `metrics.yaml`

**Promotion ceiling:** still `promoted`. Level 4 adds rigor, not new labels.

**Adoption time over Level 3:** variable — depends heavily on your existing CI/infra. Can be days if you have nothing; hours if you have a robust ML platform already.

## Level 5 — Meta-improving research process

The agent may propose improvements to its own search strategy. Evaluator boundary still §3.1.1-enforced; protocol changes still require human review.

**Additional starter files:** TBD by the protocol's future direction. v0.5 does not prescribe Level-5 file structure — adoption at Level 5 should be coordinated with the protocol maintainers (see `CONTRIBUTING.md`).

Do not jump to Level 5 before Levels 1-3 are reliable on your project.

## Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Adopt at Level 3 without a verifier | Every `promotion_request` produces `enforcement: in_band_only`, `not_deployable: true` | Set up CI signing or accept the label honestly |
| Set `val_set_exposure_budget` too tight | Verifier rejects promotions on exposure exhaustion | Plan budget to include re-grades + factorials |
| Run Skeptic in the same session as the Implementation Worker | Level-0 separation; promotion blocked for production | Use different sessions; ideally different model families |
| Skip §17.1.1 golden fixtures | Evaluator drift goes undetected | Write 3-5 fixtures at bootstrap — even minimal coverage helps |
| Use v0.3 metrics.yaml at v0.4 | Direction missing on guardrails; behavioral-equivalence tolerances too tight | See `MIGRATION.md` v0.3 → v0.4 |
| Treat `level1_branch_winner` as deployable | Ships a result without ablation evidence | Read the frontmatter — `not_deployable: true` always for L1/L2 |
