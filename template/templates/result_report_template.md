---
protocol_version: "0.4"
report_id: "<YYYYMMDD-HHMMSS-6hex-slug>"
candidate_proposal_id: "<id>"
ledger_entry_id: "<id>"
maturity_level: <1 | 2 | 3 | 4 | 5>
status: "<invalid | failed | informative_failure | promising | level1_branch_winner | level2_branch_winner | branch_winner | promotion_candidate | promoted | low_evidence_promoted>"
not_deployable: <true | false>
evidence_level: "<standard | low>"
enforcement_mode: "<ci_enforced | pre_receive | oop_verifier | container_ro | none>"
scout_mode: "<live | offline>"
---

# Result Report: <short name>

## Summary

(One paragraph. What changed, what happened, what we learned.)

## Metrics (vs baseline)

| Metric | Direction | Baseline | Candidate | Δ | 95% CI | Verdict |
|---|---|---|---|---|---|---|
| <primary> | <maximize/minimize> | <FILL_ME> | <FILL_ME> | <FILL_ME> | <FILL_ME> | <PASS/FAIL> |
| <secondary> | ... | ... | ... | ... | ... | ... |

## Guardrails

| Guardrail | Direction | Threshold | Δ 95% CI | Holm-corrected | Verdict |
|---|---|---|---|---|---|
| <guardrail> | ... | ... | ... | ... | <PASS/FAIL> |

## Subgroup behavior

(Where did this help? Where did it hurt? Per-subgroup deltas.)

## Reproducibility metadata (§17.5.1)

```yaml
torch_version: "..."
cuda_version: "..."
cudnn_version: "..."
gpu_model: "..."
deterministic_mode: <true | false>
amp_dtype: "<fp32 | bf16 | fp16>"
os: "..."
python_version: "..."
dataloader_workers: <int>
container_image_digest: "<sha256:...>"
lockfile_hash: "..."
```

## Validation-set exposure incurred (§17.6)

- Stage-C runs on val: <count>
- Stage-B-on-val runs: <count>
- Seed reruns: <count>
- Early-stop val peeks: <count>
- **Total queries incremented:** <int>
- Counter after this iteration: <int> / <budget>

## Costs (§17.7)

- LLM tokens: <int>
- Tool calls: <int>
- GPU hours: <float>
- Wall clock: <float>
- Provider cost estimate: <$float>

## Likely causal mechanism

(Reflection Analyst's call. What in the candidate change drove the observed effect? Be specific.)

## Failure modes inspected

(Any per-example failures the analyst surfaced. Subgroup regressions, distributional shifts, edge cases.)

## Decision (§13.3)

- Category: <see status field>
- Next action: <add ablation | promote | branch | prune | quarantine>
- Reasoning: <one paragraph>

## Lessons (for playbook)

- <durable lesson 1>
- <durable lesson 2>
