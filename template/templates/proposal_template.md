---
protocol_version: "0.4"
proposal_id: "<YYYYMMDD-HHMMSS-6hex-slug>"
branch: "<architecture | loss_objective | data_sampling | features | optimization | calibration | systems_efficiency>"
parent_proposal_id: "<id or baseline>"
literature_brief: "<path or null>"
web_search_used: <true | false>
maturity_level: <1 | 2 | 3 | 4 | 5>
---

# Experiment Proposal: <short name>

## Hypothesis

Because <observed failure>, changing <mechanism> should improve <metric/subgroup> by ≥ <expected_delta> without worsening <guardrails> beyond <regression_tolerance>.

## Literature basis

- <source 1> [<peer-reviewed | preprint | blog | repo | speculation>]: <relevant finding>

(If `web_search_used: false`, this section pulls only from `canon.bib`; tag the brief `mode: offline` and avoid novelty claims.)

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
