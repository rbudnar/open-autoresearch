# Example: Level-3 counter-example arc

A Level-3 campaign that **does not promote anything**. The counter-example exists because §19 explicitly accepts "no trustworthy improvement found" as the correct output of a campaign, and §22a says we owe adopters a worked example of what that looks like.

## What this teaches

This campaign exercises every failure mode the v0.5 protocol is designed to surface:

| Iteration | Failure mode demonstrated | §reference |
|---|---|---|
| Iter 1 | **Fail-fast catch** — Stage-A tiny-overfit test catches loss divergence; consumes only smoke budget. | §17.1.1 (preflight), §12.1 Stage A |
| Iter 2 | **Guardrail regression caught by direction-aware §13.2.1** — primary improves but latency regresses past Holm-corrected threshold. | §13.2.1 |
| Iter 3 | **Real `branch_winner`** at Level 3 (no prefix). | §13.3 |
| Iter 4 | **Evaluator drift invalidates earlier result** — behavioral-equivalence test catches a refactor that changed rounding. Iter-3 metrics retroactively `invalidated`. | §17.1.1 |
| Iter 5 | **Re-grade after evaluator refresh** confirms iter-3's effect on the updated evaluator. | §17.1.1 (update procedure) |
| Iter 6 | **Stack masquerading as candidate** — Skeptic catches a proposal that flips two switches; routed for factorial planning. | §11.1.1 |
| Iter 7 | **Factorial ablation** — 2×2 grid attributes gain to attention pool; ordinal loss contributes within noise. | §16.1.2 |
| Iter 8 | **Promotion request REJECTED by verifier** — val-exposure budget exhausted by the iter-5 re-grade + iter-7 factorial. Verifier-signed packet carries `status: rejected`. | §10.5, §17.6 |

Campaign outcome: `no_trustworthy_improvement_found`. The attention-pool candidate is real (Level-3 `branch_winner`) but **cannot promote** until a holdout refresh restores val-exposure budget. The campaign's deliverable is the **negative lessons report** in `reports/counter_example_report.md`.

## The toy task

Same as `level1-success/` — tiny MLP, synthetic regression target, 10k val examples. Same metrics. Cost tier `small` (3 candidate / 5 promotion seeds).

**Enforcement:** `mechanism: ci_enforced` — to demonstrate the verifier signing real (rejected) packets.

**Maturity:** Level 3 throughout.

**val_set_exposure_budget:** 50 — deliberately tight to force the iter-8 rejection. A real campaign would set this higher.

## How the verifier sees the campaign

If you re-run `verify_request.py` against `proposals/iter08-promotion-request.json`, it will produce a packet with `status: rejected` and `rejection_reasons: [val_exposure exhausted]`. The repo's `validate-examples.yml` CI workflow asserts exactly this outcome — the example is part of the test suite for the verifier.

## Files

```text
config/
  metrics.yaml               # val_set_exposure_budget = 50 (tight, to demonstrate exhaustion)
  enforcement.yaml           # mechanism: ci_enforced
  protected_paths.yaml
state/
  experiment_ledger.jsonl    # 8 ledger entries spanning the narrative above
  val_exposure.json          # final counter showing 52/50 — over budget
  budget_ledger.jsonl        # role-resolved cost data
proposals/
  iter01-fail-fast.md
  iter02-cosine-restarts.md
  iter06-stack-rejected.md
  iter08-promotion-request.md
  iter08-promotion-request.json
reports/
  iter04-invalidation.md
  iter07-factorial-ablation.md
  iter09-skeptic-review.md
  iter08-promotion-packet.md
  iter08-promotion-packet.json
  counter_example_report.md  # the campaign's actual deliverable
```

## What this example deliberately is NOT

- Not a polished story arc. Real Level-3 campaigns have ugly iterations; this one shows them.
- Not a victory lap. The best result is `branch_winner` at Level 3 with a blocked promotion. That is the honest outcome.
- Not a unit test for the protocol's English. It's a worked example with concrete numbers.

## Where to start reading

1. `reports/counter_example_report.md` (the meta-narrative — 5 min read)
2. `state/experiment_ledger.jsonl` (one line per iteration; tells the whole story compactly)
3. `reports/iter04-invalidation.md` (the most subtle artifact — evaluator drift + retroactive invalidation)
4. `proposals/iter08-promotion-request.json` and `reports/iter08-promotion-packet.json` (the rejected promotion)
