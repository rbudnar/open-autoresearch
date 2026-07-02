---
protocol_version: "0.5"
report_id: "20260518-233000-frontier-allocation"
campaign_id: "level3-counter-example-2026-05-18"
maturity_level: 3
decision_type: "frontier_allocation"
---

# Frontier Allocation Snapshot After Verifier Rejection

This report records the Research Director's section 8 decision after the
iter-8 promotion request was rejected for validation-exposure exhaustion.

## Frontier decision

```yaml
frontier_decision:
  next_branch_choice: "none"
  action: "request_holdout_refresh"
  budget_reason: >
    The campaign has 0 validation-query headroom after the verifier reports
    52/50 exposure. Another full-validation run would spend the scarce
    resource that promotion evidence requires. The only budget-respecting
    path is to refresh the holdout or end the campaign.
  reserve_budget_for_promotion: false
  defer_reason: >
    attention_pool remains the best branch_winner, but promotion evidence
    cannot be completed until section 17.6.3 refreshes the holdout.
  frontier_rank_snapshot:
    - node_id: "20260518-160000-bbb005-regrade"
      branch: "architecture"
      evidence: "branch_winner; strong NLL improvement; ablation-supported"
      next_step: "verifier"
      expected_cost:
        val_queries: 0
        gpu_hours: 0.0
        wall_clock_hours: 0.0
        llm_tokens: 0
        tool_calls: 0
      remaining_headroom:
        val_queries: -2
        gpu_hours: 4.0
        wall_clock_hours: 6.0
        llm_tokens: 19560000
        tool_calls: 9400
      decision: "deferred"
      reason: "blocked on holdout refresh, not on candidate quality"
    - node_id: "20260518-190000-bbb007-factorial"
      branch: "architecture+loss_objective_factorial"
      evidence: "small ordinal_hybrid effect; no interaction beyond attention_pool"
      next_step: "none"
      expected_cost:
        val_queries: 15
        gpu_hours: 15.0
        wall_clock_hours: 10.0
        llm_tokens: 500000
        tool_calls: 200
      remaining_headroom:
        val_queries: -2
        gpu_hours: 4.0
        wall_clock_hours: 6.0
        llm_tokens: 19560000
        tool_calls: 9400
      decision: "stopped"
      reason: "not worth further validation exposure before the dominant branch can promote"
    - node_id: "20260518-110000-bbb002"
      branch: "optimization"
      evidence: "failed guardrail; latency regression"
      next_step: "none"
      expected_cost:
        val_queries: 3
        gpu_hours: 3.0
        wall_clock_hours: 1.0
        llm_tokens: 200000
        tool_calls: 80
      remaining_headroom:
        val_queries: -2
        gpu_hours: 4.0
        wall_clock_hours: 6.0
        llm_tokens: 19560000
        tool_calls: 9400
      decision: "pruned"
      reason: "reviewed negative result plus guardrail regression"
  stop_reason: >
    If holdout refresh is not approved, stop the campaign and publish the
    counter-example report with attention_pool recorded as a blocked
    branch_winner rather than spending more validation budget.
```

## Rationale

The attention_pool branch is not stopped because its evidence is weak. It is
deferred because the campaign failed to reserve enough validation exposure for
promotion evidence. The frontier policy therefore selects a governance action
(`request_holdout_refresh`) instead of another implementation run.

This is the expected behavior for a Level-3 campaign: negative and blocked
states are first-class planning outcomes, but they only update derived
`research_tree` views after the corresponding ledger lifecycle fields are
recorded. Budget exhaustion is allowed to be the reason a promising branch does
not proceed.
