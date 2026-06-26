---
protocol_version: "0.5"
proposal_id: "20260518-110000-bbb002"
branch: "optimization"
parent_proposal_id: "baseline"
literature_brief: "literature/briefs/2026-05-18-cosine-restarts.md"
web_search_used: true
maturity_level: 3
---

# Experiment Proposal: Cosine restarts LR schedule

## Hypothesis

Because the baseline cosine schedule produces a smooth-but-shallow training loss curve, switching to cosine restarts should re-warm past local minima and improve NLL.

## Literature basis

Live mode. Cosine restarts is a well-trodden optimization-branch change with multiple peer-reviewed sources reporting modest gains on classification tasks. No instability concerns at this scale.

## Proposed change

```yaml
config:
  lr_schedule: cosine_restarts
  # restart_cycles: 3, base_lr: 1e-3 (same as baseline base_lr)
```

## Expected result

| Metric | Baseline | Target | Threshold |
|---|---|---|---|
| validation_nll | 0.847 | ≤ 0.835 | minimum_meaningful_delta=0.005 |
| accuracy | 0.78 | ≥ 0.78 | (no regression) |
| inference_latency_ms | 18.4 | ≤ 20.2 | max_regression_relative=0.10 (i.e., max Δ +1.84ms) |

## Outcome (recorded after the run)

**FAILED — guardrail regression.**

| Metric | Δ | 95% CI | Verdict |
|---|---|---|---|
| validation_nll | -0.010 | [-0.016, -0.004] | PASS (PROMOTE-ELIGIBLE on primary) |
| accuracy | +0.01 | [0.00, +0.02] | PASS |
| inference_latency_ms | +1.8 | [+1.5, +2.1] | **FAIL** (upper CI +2.1 > Holm-corrected threshold +1.84) |

**Why latency regressed:** Cosine restarts shift the model into different attention-activation patterns at each cycle's peak; some checkpoints land in slower CUDA kernels. The latency variance also widened (seed_std from 0.4ms baseline to 0.8ms).

**Lessons:**
- Optimization-branch changes can have surprising latency effects.
- §13.2.1 direction-aware decision rule with Holm-corrected guardrails worked exactly as designed: primary improved real, but the guardrail violation correctly blocked promotion.
- Latency variance should be tracked alongside mean.

**Status:** `failed` (real result, but guardrail violation prevents promotion eligibility).

**Carried forward:** consider whether `cosine_restarts` could be valuable on a task where latency isn't a guardrail. Add to playbook as `conditionally_promising`.
