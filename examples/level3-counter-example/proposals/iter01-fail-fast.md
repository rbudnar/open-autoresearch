---
protocol_version: "0.4"
proposal_id: "20260518-100000-bbb001"
branch: "loss_objective"
parent_proposal_id: "baseline"
literature_brief: "literature/briefs/2026-05-18-ordinal-coef-sweep.md"
web_search_used: true
maturity_level: 3
---

# Experiment Proposal: Ordinal hybrid loss, aggressive coefficient

## Hypothesis

Because the default ordinal hybrid coefficient (0.5) gave a small but real NLL improvement in prior campaigns, pushing the coefficient to 0.9 should produce a larger improvement.

## Literature basis

Live mode. Literature brief (2026-05-18) cited two preprints suggesting aggressive ordinal weighting can yield 2× the improvement of the canonical 0.5 setting, with the caveat that both papers report training instabilities at coefficients ≥ 0.85.

## Proposed change

Set `loss_type: ordinal_ce_hybrid_aggressive` with `coef=0.9` in the loss config.

## Single non-baseline switch

```yaml
config:
  loss_type: ordinal_ce_hybrid_aggressive
  loss_coef: 0.9
# all other switches pinned to baseline
```

## Expected result

NLL Δ ≈ -0.018 (estimating 2× the 0.5 setting's effect).

## Evaluation plan

- **Smoke (Stage A):** 100 steps with tiny-overfit test. ESPECIALLY important here given the literature's flag on instability above 0.85.
- **Proxy (Stage B):** 5% train.
- **Full (Stage C):** 5 seeds (Level-3 promotion count).

## Risks

- **High:** training instability per literature. Stage-A tiny-overfit test is the safety net.
- Latency: should be neutral (loss change only).

## Outcome (recorded after the run)

**FAILED at Stage A (preflight).** The tiny-overfit test caught loss divergence at step 12: gradient norm spiked to NaN. Per §17.1.1 preflight, the full Stage-C budget was NOT consumed — only ~6 GPU-minutes total.

**Lessons:**
- The literature's flag on coefficient ≥ 0.85 was accurate.
- The fail-fast pattern (§12.1 Stage A, §17.1.1 preflight) earned its keep: 1 minute of compute caught a problem that would have wasted 9+ GPU-hours of Stage-C runs.
- Add `coef ≥ 0.9 unstable on this task` to `known_failures.md`.

**Status:** `failed` (not `invalid` — the candidate was honestly tested at preflight; the protocol caught it before any wasted compute).
