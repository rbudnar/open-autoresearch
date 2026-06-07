---
protocol_version: "0.5"
request_id: "<YYYYMMDD-HHMMSS-6hex>"
candidate_proposal_id: "<id>"
campaign_id: "<id>"
maturity_level_used: <3 | 4 | 5>          # MUST be ≥ 3
requested_status: "<promoted | low_evidence_promoted>"
---

# Promotion Request

**Read this:** the agent writes this file to ASK the verifier (`PROTOCOL.md` §10.5) to evaluate the candidate. The agent does NOT self-attest `status: promoted`. The verifier reads this file, re-runs §10.5 validation rules, and emits a signed `promotion_packet.{md,json}` with the final status.

## References (agent claims; verifier re-checks)

The verifier will re-hash every referenced ledger entry and reject the request on drift.

```yaml
references:
  baseline_run:
    ledger_id: "<id>"
    content_sha256: "<hash>"

  candidate_runs:                          # one entry per seed
    - {ledger_id: "<id>", content_sha256: "<hash>"}
    - {ledger_id: "<id>", content_sha256: "<hash>"}
    - {ledger_id: "<id>", content_sha256: "<hash>"}

  baseline_rerun:
    ledger_id: "<id>"
    content_sha256: "<hash>"

  ablation_runs:
    - {ledger_id: "<id>", content_sha256: "<hash>"}

  skeptic_review:
    path: "reports/<id>-skeptic.md"
    content_sha256: "<hash>"

  literature_brief:                        # Level 2+ only
    path: "literature/briefs/<id>.md"
    content_sha256: "<hash>"
```

## Claims (the verifier re-runs these against the ledger)

```yaml
claims:
  enforcement_mode: "<ci_enforced | pre_receive | oop_verifier | container_ro | none>"

  role_separation_achieved:
    implementation_worker_vs_skeptic: "<level_0 | level_1 | level_2 | level_3>"
    research_director_vs_reflection_analyst: "<...>"
    literature_scout_vs_implementation_worker: "<...>"

  ablation:
    change_type: "<single_component_swap | stack | additive_component | algorithmic>"
    factorial_grid_completed: <true | false>   # MUST be true for stacks

  val_set_exposure_at_request:
    queries_against_val_this_campaign: <int>
    exposure_budget: <int from metrics.yaml>

  budget_at_request:
    llm_tokens_total: <int>
    tool_calls_total: <int>
    gpu_hours_total: <float>

  behavioral_equivalence_test_passed_for_evaluator: <true | false>

  causal_attribution: |
    <One-paragraph causal claim grounded in the referenced ablation entries.
    What change in the candidate caused the measured improvement? What did the
    lesion / factorial cells show? What did NOT cause the improvement?>
```

## Reading this file

Verifier authoritative output: `reports/<request_id>-promotion-packet.{md,json}`. Until that file exists and is signed, this request is `promotion_candidate`, not `promoted`. If the verifier rejects the request, the agent revises and resubmits with a new `request_id`.
