---
protocol_version: "0.4"
ablation_id: "20260518-190000-bbb007-factorial-report"
candidate_proposal_id: "iter06-stack-rejected (decomposed into factorial)"
ledger_entry_id: "20260518-190000-bbb007-factorial"
change_type: "stack"
maturity_level: 3
---

# Ablation Report: Attention pool × Ordinal hybrid factorial

## Candidate summary

A stack was proposed in iter-6 combining `encoder_type=attention_pool` with `loss_type=ordinal_ce_hybrid`. The Skeptic intercepted it per §11.1.1. Per §16.1.2, before either component of the stack can be promoted, a factorial ablation is required to attribute the effect.

## Change type

`stack` — exactly two non-baseline switches.

## Factorial design

2 × 2 grid:

| | loss=cross_entropy | loss=ordinal_ce_hybrid |
|---|---|---|
| **encoder=baseline_mean_pool** | cell (BB) | cell (BO) |
| **encoder=attention_pool** | cell (AB) | cell (AO) |

3 seeds per cell × 4 cells = 12 runs. Cost: 36.4 GPU-hours (~2× a single candidate).

## Cell results (mean of 3 seeds)

| Cell | validation_nll | seed_std | latency_ms |
|---|---|---|---|
| (BB) mean_pool + ce            | 0.847 | 0.011 | 18.4 |
| (BO) mean_pool + ordinal       | 0.838 | 0.012 | 18.5 |
| (AB) attention_pool + ce       | 0.825 | 0.010 | 19.7 |
| (AO) attention_pool + ordinal  | 0.822 | 0.011 | 19.8 |

## Main effects

| Effect | Δ | 95% CI | Interpretation |
|---|---|---|---|
| attention_pool vs mean_pool | **-0.019** | [-0.024, -0.014] | Dominant — ~80% of the combined gain |
| ordinal_hybrid vs ce        | **-0.006** | [-0.012, -0.000] | Small — just-significant secondary effect |

## Interaction

| Interaction | Δ | 95% CI | Interpretation |
|---|---|---|---|
| encoder × loss | +0.001 | [-0.005, +0.007] | No detectable interaction (CI straddles 0) |

## What caused the improvement?

**Attention pooling.** It is responsible for ~80% of the combined effect; ordinal hybrid loss accounts for the remainder. They do not interact in a measurable way at this seed count, so the combined effect is approximately additive.

## What did not matter?

The interaction. A combined "stack" proposal would have suggested that the components must be co-deployed; the factorial shows they can be evaluated independently.

## Remaining uncertainty

- The ordinal_hybrid main effect (-0.006, 95% CI [-0.012, -0.000]) just barely clears zero on its lower bound. At a tighter cost-tier seed count (e.g., 5 seeds) the CI would tighten; with the current 3 seeds we cannot strongly distinguish "real small effect" from "no effect."
- The factorial used only the canonical loss coefficient (0.5); the iter-1 fail-fast demonstrated coefficient sensitivity, so the ordinal effect could be sensitive to coefficient choice in ways this grid did not explore.

## Promotion recommendation

**Promote attention_pool alone.** Ordinal_hybrid is `promising` but does not yet meet promotion criteria; carry as a future-campaign candidate.

This recommendation feeds into iter-8's `promotion_request`. (Spoiler: that request is rejected by the verifier on val-exposure exhaustion. See `reports/iter08-promotion-packet.json`.)

## Cost note for the playbook

The factorial cost (36.4 GPU-hours, 12 val queries) is significant. A future campaign that anticipates a stack should plan its val-exposure budget and compute budget assuming a factorial up front — not after the agent proposes the stack. This is the lesson worth carrying forward more than the specific result.
