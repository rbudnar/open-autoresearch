---
protocol_version: "0.4"
review_id: "20260518-210000-bbb009"
candidate_proposal_id: "20260518-130000-bbb003"
candidate_ledger_entries:
  - "20260518-160000-bbb005-regrade"
  - "20260518-190000-bbb007-factorial"
  - "20260518-220000-bbb008-promotion-request"
verdict: "no_objection"
skeptic_role_separation_level: "level_2"
mode: "adversarial"
---

# Skeptic Review: Attention pool encoder (iter-3 → iter-5 regrade → iter-7 factorial → iter-8 lesion)

**Operating mode:** `adversarial` at Level-2 separation from Implementation Worker. The Worker was Codex; the Skeptic (this review) is Claude in a fresh session.

## Checklist

### Hard checks

- [x] **Protected file changes:** PASS. `git diff` shows changes only in `models/encoders/attention_pool.py`, `models/encoder_factory.py`, `configs/experiments/bbb003.yaml`. No paths in `protected_paths.yaml` were modified by the candidate. The §3.1.1 CI-enforced mechanism (CODEOWNERS + branch protection on `main`) confirms this — the candidate's feature branch could not have bypassed the protection.

- [x] **Data leakage:** PASS. Data snapshot ID `data-snap-2026-05-15` matches baseline. No new data introduced. Stage-B used the separate proxy slice; Stage-C used val.

- [x] **Behavioral-equivalence test:** PASS as of iter-5 (after the iter-4 invalidation + golden refresh). The current goldens reflect the refactored `metric_defs.py`. Hash of `evaluation/` matches the manifest signed at iter-5.

- [x] **Cherry-picked seeds:** PASS. Iter-5 ran 3 seeds at small-tier; iter-7 factorial ran 3 seeds per cell. No seeds were discarded. Seed values: 42, 43, 44 (declared in the proposal).

- [x] **Stack masquerading as candidate:** PASS. The current promotion request is for `encoder_type=attention_pool` alone (single non-baseline switch). Iter-6's stack proposal was correctly intercepted and decomposed; the iter-7 factorial established the main effects, and this promotion is for the dominant effect only.

### Statistical / methodological checks

- [x] **Direction-aware decision rule:** PASS. validation_nll is `direction: minimize`; the rule used `upper_95_CI(Δ) ≤ −0.005`. iter-5's upper CI is -0.016, well past the threshold.

- [x] **Subgroup regressions:** PASS at the level we can check. No subgroups defined in `metrics.yaml`; subgroup analysis is out of scope at this configuration. Would be a real concern at Level 4+ where subgroups are typically enabled.

- [x] **Hidden cost increases:** PASS. Latency Δ = +1.3ms within 10% relative budget. Param count Δ negligible. Training cost +0.2 GPU-hours per seed — acceptable.

- [x] **Overfit to validation slices:** OBJECT (recorded but does not block this candidate per se). Cumulative val exposure = 52, BUDGET = 50. This violation is downstream of the candidate, not caused by it; the factorial and re-grade chewed through the budget. Verifier will catch this (see promotion-packet rule 6).

- [x] **Ablation type matches change type:** PASS. The change is a single-component swap (mean-pool → attention-pool). The lesion test (§16.1.1) replaces attention weights with uniform → reverts to baseline. Confirms the attention mechanism is the causal element.

### Literature / claims checks

- [x] **Unsupported literature claims:** PASS. The proposal's literature brief cites real papers; spot-check of two passed.
- [x] **Withdrawn / unreviewed sources flagged:** PASS.

### Operational / drift checks

- [x] **Nondeterminism accounted:** PASS. `deterministic_mode: false` declared in metadata; reruns within tolerance.
- [x] **Dependency drift:** PASS. Lockfile hash unchanged across iter-3 → iter-5 → iter-7 → iter-8.
- [x] **Infrastructure failures:** PASS. No `infra_failed` runs in the campaign.

## Specific concerns surfaced

1. **Val-exposure budget was sized for a no-refresh, no-factorial campaign.** The iter-4 invalidation forced an iter-5 re-grade (double-charged exposure); iter-7's factorial added 12 queries. The combination put us 2 over a 50-query budget. The lesson is not that the candidate is bad — it's that the campaign's exposure budget planning was naive. Recommend documenting this in `counter_example_report.md` and increasing exposure_budget on next campaign.

2. **Skeptic-Worker separation was only Level-2.** Both roles are LLMs; the only separation was a fresh session and a different model family (Codex Worker, Claude Skeptic). Level 3 separation (human or deterministic CI) was not available for this example. The verifier (`PROTOCOL.md` §10.5) is the Level-3 check.

3. **iter-2's cosine_restarts latency regression** was real and reproducible. Worth flagging in the playbook that optimization-branch changes can have hidden latency costs through CUDA kernel selection — non-obvious to a Director who only watches the primary metric.

## Verdict

**`no_objection`** — every hard check passed; the OBJECT on val-exposure is correctly downstream (it's the verifier's job to enforce that, not the Skeptic's to block on it). The candidate (attention_pool) is a real `branch_winner` at Level 3 with strong evidence:

- Primary: -0.022 NLL with tight CI [-0.028, -0.016] (post-evaluator-refresh).
- Causal mechanism: §16.1.1 lesion test confirms attention weights are the cause.
- Discrimination from ordinal_hybrid: §16.1.2 factorial established attention pool drives most of the gain; ordinal contributes a small secondary effect with no interaction.
- Guardrails: latency within budget.
- Subgroups: out of scope at this campaign's configuration.

**The Skeptic recommends the agent emit the promotion request.** The verifier will then decide whether to sign the packet — and in this case, will reject on val-exposure exhaustion. That is the protocol working as intended: independent checks at each gate.

## Override (none)

Not applicable.
