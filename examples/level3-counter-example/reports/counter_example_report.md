---
protocol_version: "0.5"
report_id: "20260518-230000-counter-example-meta"
campaign_id: "level3-counter-example-2026-05-18"
iterations_covered:
  - "20260518-090000-bbb000"
  - "20260518-100000-bbb001"
  - "20260518-110000-bbb002"
  - "20260518-130000-bbb003"
  - "20260518-150000-bbb004-invalidation"
  - "20260518-160000-bbb005-regrade"
  - "20260518-170000-bbb006-stack-rejected"
  - "20260518-190000-bbb007-factorial"
  - "20260518-220000-bbb008-promotion-request"
maturity_level: 3
campaign_outcome: "no_trustworthy_improvement_found"
---

# Counter-Example Report

**What this is:** A complete Level-3 campaign where, despite real signal in the data, **no candidate was promoted.** Per `PROTOCOL.md` §19, this is a legitimate campaign outcome. Per §22a, we owe adopters a worked example of what such an outcome looks like and what lessons it carries.

This report is the campaign's actual deliverable.

## What we tried

Improve a tiny MLP's validation NLL on a synthetic regression task. The campaign was at Level 3 maturity (`PROTOCOL.md` §24) — ablation discipline, Skeptic role, verifier-signed promotion packets. Cost tier `small` (3 candidate / 5 promotion seeds). Enforcement `mechanism: ci_enforced`. Val-exposure budget 50.

## What happened

| Iter | Branch | Candidate | Outcome | Lesson |
|---|---|---|---|---|
| 0 | baseline | — | baseline established (NLL 0.847) | — |
| 1 | loss_objective | ordinal_hybrid coef=0.9 | **failed** at preflight (loss diverged at step 12). Only smoke budget consumed. | Tiny-overfit catches divergence early; agent must not push coefficients past the documented stability range. |
| 2 | optimization | cosine_restarts | **failed** on guardrail (NLL improved -1.2%, but latency +1.8ms with upper CI +2.1ms vs Holm threshold +1.84ms) | Optimization changes can have hidden latency costs through CUDA kernel selection. |
| 3 | architecture | attention_pool | branch_winner (NLL -0.024) — **provisional** | Strong signal. |
| 4 | evaluator_audit | (refactor of metric_defs.py) | **invalidated** iter-3 — refactor changed rounding; behavioral-equivalence test caught it | Run behavioral-equivalence on every evaluator PR before merge, not just at next iteration's preflight. |
| 5 | architecture | attention_pool (re-grade after evaluator refresh) | branch_winner reaffirmed (NLL -0.022) | Effect is real and persists under canonical evaluator. |
| 6 | architecture+loss | attention_pool + ordinal_hybrid (stack) | **informative_failure** — Skeptic caught stack per §11.1.1; no experiment run | Agent's instinct to stack improvements is the most common protocol violation. |
| 7 | architecture+loss (factorial) | 2×2 grid, 12 runs | branch_winner reaffirmed for attention_pool | Attention pool drives 80% of combined gain; ordinal hybrid is a small secondary effect with no interaction. |
| 8 | architecture | promotion_request for attention_pool alone | **rejected** by verifier — val-exposure budget exhausted (52/50) | Real candidates can be blocked by procedural cost. Plan exposure budget to include re-grades + factorials. |

## Why no candidate was promoted

The attention_pool candidate is real. It's measurably better than baseline (NLL Δ -0.022, 95% CI [-0.028, -0.016]). The lesion test confirms the mechanism. The factorial confirms it dominates the alternative. The Skeptic clears it. **And yet the verifier rejects the promotion.**

**The reason:** val-exposure budget exhausted. The campaign incurred 52 queries against a budget of 50, primarily because:
- iter-5 re-grade was double-charged (baseline rerun + candidate rerun, 6 queries)
- iter-7 factorial was 12 queries (4 cells × 3 seeds)
- iter-8 lesion test was 2 more

The protocol does NOT let us deploy a candidate measured against a val set that has been so frequently queried that the §13.2.1 statistics are no longer reliable. Per §17.6, a holdout refresh is required first.

**This is the protocol working as intended.** The agent does not get to override the verifier on its own evidence; an external check exists specifically to prevent "we know it's good, let's ship" reasoning.

## Lessons (for the playbook)

- **Coefficient sensitivity:** ordinal_hybrid with `coef ≥ 0.9` is unstable on this task. Add to `known_failures.md`. Future sweeps grid-search 0.1–0.7 only.
- **Optimization-branch latency trap:** lr-schedule changes can affect inference latency through CUDA kernel selection. Always check latency variance alongside mean.
- **Attention pool is the dominant architecture branch.** Worth re-attempting under a fresh val (after holdout refresh).
- **Stack proposals are the agent's #1 instinct.** The Skeptic role earns its keep by intercepting them.
- **Evaluator refactors must run behavioral-equivalence BEFORE merge, not at next preflight.** Tightening this loop would have saved iter-4's cost.
- **Plan val-exposure budget to include re-grades + factorials, not just direct candidate runs.** Naive budgeting: candidates × seeds. Realistic: candidates × seeds + ablations × seeds + factorials × cells × seeds + (probability_of_refresh × all_above × 2).

## "Do not retry without new evidence"

- `ordinal_hybrid` with `coef ≥ 0.9` on this task. Pattern: training divergence within first 20 steps.
- `cosine_restarts` on this task when `inference_latency_ms` is a guardrail. Pattern: ~1.8ms latency increase, mostly from variance.

## What would unlock progress

1. **Holdout refresh** (highest priority). Per §17.6.3, either rotate splits or refresh from held-back pool. Costs human review per §3.1 — schedule with stakeholder.
2. **Tighter val-exposure planning.** Next campaign should declare exposure budget = (expected candidate runs + expected re-grades + expected factorial cells) × seeds, plus 20% buffer for unexpected reruns.
3. **Pre-merge behavioral-equivalence CI hook.** Catches evaluator drift at PR time, not at next iteration's preflight.

## Open questions

- Would `ordinal_hybrid` at `coef=0.3` (in the stable range) combined with attention pool produce a measurable improvement beyond attention pool alone? Iter-7's `coef=0.5` cell showed -0.003 NLL beyond attention pool, just barely past noise. A targeted future campaign with 5 seeds per cell might resolve it.
- The latency variance widening under cosine_restarts (iter-2) — is it specific to this attention model or general? Worth checking in a future architecture-comparison campaign.

## Campaign-end summary

- Total iterations: 9 (1 baseline + 8 candidates / events)
- Iterations with new candidate runs: 5 (iter-0, 2, 3, 5, 7)
- Iterations that caught a problem cheaply: 3 (iter-1 fail-fast, iter-4 invalidation, iter-6 stack-rejected)
- GPU hours total: 96
- LLM tokens total: 440k
- USD estimated: $2.20
- Wall clock: ~14 hours
- **Result: 0 promotions, 1 strong `branch_winner` blocked on procedure, 7 durable lessons.**

The campaign is a success in the protocol's terms even though no model shipped. The negative-result discipline turned a deliberate stress test into reusable knowledge.
