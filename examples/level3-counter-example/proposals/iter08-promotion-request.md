---
protocol_version: "0.4"
request_id: "20260518-220000-bbb008"
candidate_proposal_id: "20260518-130000-bbb003"
campaign_id: "level3-counter-example-2026-05-18"
maturity_level_used: 3
requested_status: "promoted"
---

# Promotion Request: Attention pooling encoder

**This file is a REQUEST.** The agent asks the verifier (`PROTOCOL.md` §10.5) to evaluate this candidate. The verifier's authoritative response is in `reports/iter08-promotion-packet.json`. **In this example the verifier rejects the request** — see the packet for details.

## What is requested

Promote the attention-pooling encoder (introduced in iter-3, re-graded in iter-5 after the evaluator refresh) to `promoted` status based on:

- Strong primary-metric improvement (NLL Δ = -0.022, 95% CI [-0.028, -0.016]).
- Latency guardrail within budget (Δ = +1.3ms, upper CI +1.6ms vs threshold +1.84ms).
- Factorial ablation (iter-7) confirming attention pool drives the gain; ordinal_hybrid is a smaller secondary effect (-0.006, 95% CI [-0.012, -0.000]) with no detectable interaction.
- Lesion test (iter-8): attention weights replaced with uniform → NLL reverts to 0.846 (within seed variance of baseline 0.847). Confirms the attention mechanism causes the improvement.
- Skeptic review (`reports/iter09-skeptic-review.md`) — verdict `no_objection`.

## References

See `iter08-promotion-request.json` for the structured references block (ledger entry IDs + content hashes for each referenced run).

## Claims (verifier will re-check)

- enforcement_mode: `ci_enforced`
- role_separation_achieved.implementation_worker_vs_skeptic: `level_2` (Codex was the Implementation Worker; Claude was the Skeptic)
- ablation.change_type: `single_component_swap` (the lesion test is the §16.1.1 type)
- ablation.factorial_grid_completed: `false` (this is a single-swap candidate, not a stack; the iter-7 factorial was a separate analysis to disambiguate from ordinal_hybrid)
- val_set_exposure_at_request: queries=52, budget=50  ⚠️
- behavioral_equivalence_test_passed_for_evaluator: `true` (re-checked after iter-4 refresh)

## ⚠️ Self-flagged risk

The val-exposure counter (52) **exceeds the configured budget** (50). The agent emits this request anyway to demonstrate the verifier's rejection path; in a real campaign the agent would request a holdout refresh (§17.6.3) BEFORE writing the request.

## Expected verifier outcome

Verifier rule 6 (val exposure not exhausted) will FAIL. The packet will carry `status: rejected` with `rejection_reasons: [val exposure 52 >= budget 50]`.
