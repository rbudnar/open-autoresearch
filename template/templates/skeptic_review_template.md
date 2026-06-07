---
protocol_version: "0.5"
review_id: "<YYYYMMDD-HHMMSS-6hex>"
candidate_proposal_id: "<id>"
candidate_ledger_entries:
  - "<id>"
verdict: "<no_objection | objected | objected_but_overridden_by_human>"
skeptic_role_separation_level: "<level_0 | level_1 | level_2 | level_3>"
mode: "<adversarial | checklist_only>"
---

# Skeptic Review: <candidate>

**Operating mode:** `<mode>` — `adversarial` requires Level 2+ separation from the Implementation Worker (§5.0). If only Level 0 separation was available (same session, same model), this review operates from the fixed checklist below and is labeled `checklist_only`; promotion is blocked from "production-facing" but may proceed for "internal" with the label visible.

## Checklist (§5.7, §21.4)

For each item: **PASS / OBJECT / N/A**, plus a short note. Any OBJECT prevents the promotion request from being emitted (or causes the verifier to reject if already emitted).

### Hard checks

- [ ] **Protected file changes:** No modifications to paths listed in `protected_paths.yaml`? (Confirm against `git diff` and against the §3.1.1 enforcement mechanism's output, if any.)
- [ ] **Data leakage:** No held-out examples in training? Data snapshot ID matches the baseline's?
- [ ] **Behavioral-equivalence test:** §17.1.1 fixtures still pass at the declared tolerance? Hash of `evaluation/` unchanged or changed only by an approved refactor?
- [ ] **Cherry-picked seeds:** Seed count meets cost_tier `min_seeds_for_promotion`? No seeds discarded mid-campaign?
- [ ] **Stack masquerading as candidate:** Only ONE non-baseline config switch (§11.1.1)? Or is the candidate actually a stack that should require factorial ablation (§16.1.2)?

### Statistical / methodological checks

- [ ] **Direction-aware decision rule:** §13.2.1 applied with the correct CI bound for each metric's direction?
- [ ] **Subgroup regressions:** Per-subgroup deltas examined; no group falls below `subgroup_min_delta`?
- [ ] **Hidden cost increases:** Inference latency, memory, parameter count, training cost all within declared guardrails?
- [ ] **Overfit to validation slices:** Multiple repeated experiments on the same val? Val-set exposure budget (§17.6) accounted?
- [ ] **Ablation type matches change type:** Per §16.1 decision tree — correct ablation for single-swap vs additive vs algorithmic vs stack?

### Literature / claims checks

- [ ] **Unsupported literature claims:** Every cited finding traces to a real source (no fabrication, per §17.3)?
- [ ] **Withdrawn / unreviewed sources flagged:** Preprints from the current quarter clearly marked as such?

### Operational / drift checks

- [ ] **Nondeterminism accounted:** §17.5.1 metadata captured; reruns within declared tolerance?
- [ ] **Dependency drift:** No unannounced lockfile bump between baseline and candidate? Container digest matches?
- [ ] **Infrastructure failures:** No `infra_failed` runs silently treated as `failed`?

## Specific concerns surfaced

(Free-form prose. Anything the skeptic noticed that the checklist didn't cover. Examples of the kind of thing that belongs here:)

- "The candidate's improvement appears driven by a longer training schedule, not the proposed architecture change. Suggest an ablation holding training budget constant."
- "Iteration 5's apparent win disappears in iteration 6's seed rerun. Either iteration 5 was lucky or there's a seed-dependent interaction. Recommend `quarantine` not `branch_winner`."
- "The literature brief cited [Source] for the proposed loss; on close reading [Source] applies to a different model family and the cited finding doesn't transfer."

## Verdict

- **no_objection** — every check passed. Skeptic clears the candidate to proceed to a promotion request.
- **objected** — at least one OBJECT above; promotion request is blocked. Reasons must be itemized.
- **objected_but_overridden_by_human** — a human reviewer (per §3.1) explicitly overrode an OBJECT. The override is documented here with the reviewer's signature and reasoning. This is rare and visible in dashboards.

## Override (if applicable)

```yaml
override:
  reviewer: "<human name>"
  timestamp: "<ISO-8601>"
  reasoning: |
    <Why the OBJECT was overridden. Specific to this candidate, not a general
    waiver.>
```

## Reproducibility

This review can be re-run by any reviewer with access to the referenced ledger entries. The skeptic's reasoning is in this file; the evidence is in the ledger. The verifier (§10.5) re-reads this file's `verdict` field and rejects the promotion request if `verdict != "no_objection"` (or `verdict != "objected_but_overridden_by_human"` with a valid override).
