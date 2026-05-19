# Example: Level-1 success arc

The smallest legitimate AutoResearch++ campaign. Three iterations on a toy synthetic regression task. One candidate ends as `level1_branch_winner`; the campaign honestly hands off to Level 3 for any promotion attempt.

## What this teaches

- The §1.5 "Start Here" path end-to-end.
- Honest labeling under `mechanism: none` — every artifact carries `enforcement: in-band-only` and `not_deployable: true`.
- The §13.2.1 direction-aware decision rule applied to a minimize metric (NLL).
- The §17.6 val-exposure counter incrementing across iterations.
- Why Level 1 cannot reach `promoted` — no ablation, no Skeptic, no verifier.

## The campaign

**Task:** train a tiny MLP to predict a synthetic regression target.
**Metrics:** validation_nll (primary, minimize), accuracy (secondary), inference_latency_ms (guardrail).
**Cost tier:** small (3 candidate seeds).
**Maturity:** Level 1.
**Enforcement:** `mechanism: none` (in-band-only).

## Iteration narrative

### Iteration 0 — Baseline (`20260518-100000-aaa001`)

Run baseline. NLL = 0.847 (mean of 3 seeds, seed_std = 0.011). Accuracy 0.78. Latency 18.4ms. Captures reproducibility metadata: torch 2.6, CUDA 12.4, cuDNN 9.1, deterministic_mode=false (FlashAttention).

### Iteration 1 — Loss objective candidate (`20260518-110000-aaa002`)

**Proposal:** `loss_type: ordinal_ce_hybrid` (single non-baseline switch; everything else pinned).
**Result:** NLL 0.838 (Δ = -0.009, 95% CI [-0.014, -0.003]). PROMOTE-ELIGIBLE on primary. Accuracy unchanged. Latency unchanged.
**Decision:** `promising` — improvement is real but candidate is at Level 1, no ablation possible. Recorded for the playbook; carried forward.

### Iteration 2 — Architecture candidate (`20260518-130000-aaa003`)

**Proposal:** `encoder_type: attention_pool` (single non-baseline switch; everything else pinned).
**Result:** NLL 0.823 (Δ = -0.024, 95% CI [-0.030, -0.018]). PROMOTE-ELIGIBLE on primary. Accuracy +0.02. Latency 19.7ms (Δ = +1.3ms, max_regression_relative = 0.10 means up to +1.84ms is allowed; PASS).
**Decision:** `level1_branch_winner` (`maturity_level: 1`, `not_deployable: true`). Highest label available at Level 1.

## Honest hand-off

> Candidate `aaa003` (encoder=attention_pool) is a `level1_branch_winner` with NLL improvement of 0.024 over baseline (95% CI [−0.030, −0.018]). Graduate this candidate to **Level 3** before any promotion: add the Skeptic role (§5.7), run a `single_component_swap` ablation per §16.1.1 (lesion test: attention weights → uniform), and emit a `promotion_request` for the non-agent verifier.

## Files

- `config/metrics.yaml`, `config/enforcement.yaml`, `config/protected_paths.yaml` — campaign config
- `state/experiment_ledger.jsonl` — 3 ledger entries (one per iteration)
- `state/val_exposure.json` — exposure counter at campaign end (3 Stage-C runs × 3 seeds = 9 queries)
- `state/budget_ledger.jsonl` — LLM tokens / tool calls / GPU hours per iteration
- `proposals/aaa002.md`, `proposals/aaa003.md` — the two candidate proposals
- `reports/aaa002.md`, `reports/aaa003.md` — result reports

## What this example deliberately does NOT do

- No `promotion_request` artifact — Level 1 cannot reach that gate.
- No Skeptic review — Level 3 only.
- No ablation report — Level 3 only.
- No factorial grid — no stacks were proposed.
- No literature brief — Level 2+ adds the Literature Scout.

Adopters tempted to skip Level 3 and label a result `promoted` from Level 1 should re-read `PROTOCOL.md` §24 and `docs/threat-model.md`.
