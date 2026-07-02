---
protocol_version: "0.5"
proposal_id: "<YYYYMMDD-HHMMSS-6hex-slug>"
branch: "<architecture | loss_objective | data_sampling | features | optimization | calibration | systems_efficiency>"
parent_proposal_id: "<id or baseline>"
literature_brief: "<path or null>"
web_search_used: <true | false>
maturity_level: <1 | 2 | 3 | 4 | 5>
# Optional literature-grounding fields:
# literature_status: "<live_search | canon_only | not_literature_verified>"
# source_ideas:
#   - "<paper/repo/canon key that motivated this proposal, or null>"
# novelty_check: "<why this is not just re-running an already rejected sibling idea>"
# implementation_precedent: "<paper/code evidence this change is plausible, or null>"
# citation_risk: "<peer_reviewed | technical_report | arxiv_preprint | prototype | withdrawn | unknown>"
# Optional Level 3+ frontier-allocation fields (§8):
# next_branch_choice: "<selected frontier node/proposal id, or null>"
# budget_reason: "<why this branch is worth the next unit of budget now>"
# reserve_budget_for_promotion: <true | false>
# These are shorthand mirrors of the `frontier_decision` block below; if both
# are present, they must match the detailed block.
---

# Experiment Proposal: <short name>

## Hypothesis

Because <observed failure>, changing <mechanism> should improve <metric/subgroup> by ≥ <expected_delta> without worsening <guardrails> beyond <regression_tolerance>.

## Literature basis

- <source 1> [<peer-reviewed | preprint | blog | repo | speculation>]: <relevant finding>

If `web_search_used: false`, this section pulls only from `canon.bib` and the host project's own docs; tag the brief `mode: offline` and avoid novelty claims. If the optional `literature_status` field is present, use `canon_only` for canon-backed offline work or `not_literature_verified` when neither live search nor canon was checked.

## Novelty and precedent check (optional)

- **Source ideas:** <papers/repos/prior proposals that motivated the change>
- **Novelty check:** <why this is not just re-running a rejected sibling or known negative result>
- **Implementation precedent:** <paper/code evidence that the change is plausible, or "none found">
- **Citation risk:** <peer_reviewed | technical_report | arxiv_preprint | prototype | withdrawn | unknown>

## Prior propagated constraints (optional)

- **Reviewed insight source ids:** <ledger ids whose `branch_insights[]` affect this proposal, or "none">
- **Affected parent/root ids:** <parent ids or "baseline">
- **Validated constraints applied:** <what this proposal must respect>
- **Invalidated sibling ideas avoided:** <ideas this proposal deliberately does not retry>
- **Draft or contested insights:** <context only; do not use as pruning or promotion authority>
- **Retirement signals checked:** <conditions that would make an old insight no longer apply>

## Frontier allocation decision (Level 3+, §8)

Use this section when choosing among multiple active frontier nodes or when
validation exposure / campaign budget affects the next run. Keep it short, but
make the choice auditable.

```yaml
frontier_decision:
  next_branch_choice: "<proposal/node id selected, or none>"
  action: "<select | defer | prune | quarantine | request_holdout_refresh | stop_campaign | emit_promotion_request>"
  budget_reason: "<why this is worth the next unit of budget now>"
  reserve_budget_for_promotion: <true | false>
  frontier_rank_snapshot:
    - node_id: "<ledger/proposal id>"
      branch: "<architecture | loss_objective | data_sampling | features | optimization | calibration | systems_efficiency>"
      evidence: "<label + uncertainty>"
      next_step: "<cheap_proxy | full_validation | ablation | rerun | verifier | none>"
      expected_cost:
        val_queries: <int>
        gpu_hours: <float>
        wall_clock_hours: <float>
        llm_tokens: <int>
        tool_calls: <int>
      remaining_headroom:
        val_queries: <int>
        gpu_hours: <float>
        wall_clock_hours: <float>
        llm_tokens: <int>
        tool_calls: <int>
      decision: "<selected | deferred | blocked | pruned | quarantined | stopped>"
      reason: "<short reason>"
  defer_reason: "<required when action=defer or any snapshot decision=deferred | blocked>"
  stop_reason: "<required when action=prune | quarantine | stop_campaign or any snapshot decision=pruned | quarantined | stopped>"
```

## Proposed change

Describe the minimal implementation. Per `PROTOCOL.md` §11.1.1, exactly ONE non-baseline config switch.

## Single non-baseline switch

```yaml
config:
  <switch_name>: <non-baseline value>
# all other switches pinned to baseline
```

## Files expected to change

- <editable file>

## Protected files that must not change

- <protected file or category>

## Executor handoff (optional, §5.8)

Use this when a separate Implementation Worker, scratch branch, or worktree will
execute the proposal. For a single-session Level-1 campaign, keep the same
payload and record `coordinator_executor_separation: level_0`.

```yaml
executor_handoff:
  proposal_id: "<this proposal id>"
  hypothesis: "<frozen hypothesis from above>"
  single_non_baseline_switch: "<one switch, or explicit stack label>"
  editable_paths:
    - "<path executor may change>"
  protected_paths:
    - "<path executor must not change>"
  isolation: "<worktree | scratch_branch | container | same_session>"
  budget_cap:
    llm_tokens: <int | null>
    tool_calls: <int | null>
    gpu_hours: <float | null>
    wall_clock_hours: <float | null>
  allowed_evaluator_commands:
    - "<smoke/proxy/full command>"
  expected_artifacts:
    - "<metrics/report/model/checkpoint path>"
  coordinator_executor_separation: "<level_0 | level_1 | level_2 | level_3>"
```

## Expected result

| Metric | Baseline | Target | Threshold |
|---|---|---|---|
| <primary> | <FILL_ME> | <FILL_ME> | minimum_meaningful_delta=<FILL_ME> |
| <secondary> | <FILL_ME> | <FILL_ME> | — |
| <guardrail> | <FILL_ME> | <FILL_ME> | max_regression=<FILL_ME> |

## Evaluation plan

- **Smoke test (Stage A):** <budget, what it verifies>
- **Cheap proxy (Stage B):** <budget, on what slice — if val, this counts toward §17.6 exposure>
- **Full validation (Stage C):** <budget, seeds from cost_tier>
- **Seeds:** <count from cost_tier>
- **Ablation type:** <one of §16.1 categories: single_component_swap | stack | additive_component | algorithmic>
- **Promotion reserve after this run:** <val queries / GPU hours / tokens left for reruns + ablation + verifier, or "not promotion-track">

## Early stopping rule

Stop if <condition>. (See §12.2.)

## Risks

- **Leakage:** <how>
- **Compute:** <how>
- **Metric gaming:** <how the agent might inadvertently shape the metric without changing the underlying capability>
- **Implementation:** <known unknowns>

## Promotion criteria

This candidate is promotable (Level 3+) if all of:

- Primary metric clears `minimum_meaningful_delta` per §13.2.1 direction-aware rule.
- Guardrails pass Holm-corrected.
- Subgroup regressions documented and acceptable.
- Single non-baseline switch (or stack treated factorially per §16.1.2).
- Ablation per §16.1 supports the causal mechanism.
- Skeptic review clean.
- Behavioral-equivalence test on evaluator passes.
- Validation-set exposure budget not exhausted.
- Total budgets not exceeded.
- Promotion request → verifier-signed packet (`PROTOCOL.md` §10.5).
