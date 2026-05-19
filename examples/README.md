# examples/ — completed campaign artifacts

Two example campaigns showing what AutoResearch++ v0.4 looks like in practice. Both run on a fictional toy task (a tiny synthetic regression model) to keep the protocol's shape visible without the noise of a real ML pipeline.

## Why two examples

| Example | Demonstrates | Outcome |
|---|---|---|
| [`level1-success/`](./level1-success/) | The smallest legitimate campaign from `PROTOCOL.md` §1.5 — baseline + two candidates at Level 1, no ablation, no Skeptic, no promotion attempted. | One `level1_branch_winner`; honest hand-off to Level 3. |
| [`level3-counter-example/`](./level3-counter-example/) | A Level-3 campaign that exercises every failure mode in `PROTOCOL.md` §22a — fail-fast catch, ablation rejecting a hypothesis, guardrail regression caught by §13.2.1, stack handled factorially, evaluator-equivalence catching a refactor, and a promotion request the verifier rejects. | `no_trustworthy_improvement_found`; durable negative lessons. |

## How to read an example

Each campaign directory mirrors the `template/` layout: `config/`, `state/`, `proposals/`, `reports/`. Read the example's local `README.md` first; it narrates the campaign and points you at each artifact in iteration order.

## The toy task (both examples)

Train a small MLP to predict a synthetic regression target. The val set has 10,000 examples drawn from a fixed seed.

**Metrics:**
- Primary: `validation_nll` (minimize, fp32, mean over examples, min_meaningful_delta = 0.005)
- Secondary: `accuracy` (maximize, int)
- Guardrail: `inference_latency_ms` (minimize, fp32, max_regression_relative = 0.10)

**Cost tier:** `small` (≈ 1-hour training run). Seed counts: 3 candidate / 5 promotion.

**Enforcement mode in the examples:**
- `level1-success/` uses `mechanism: none` — the campaign explicitly accepts the in-band-only label.
- `level3-counter-example/` uses `mechanism: ci_enforced` — to demonstrate the verifier signing real packets.

## Re-running the verifier against the examples

After signing key setup (see [`../template/scripts/verifier/`](../template/scripts/verifier/)):

```bash
# Level-3 example — should produce status: rejected, since the request
# deliberately fails one of the §10.5 rules.
OPEN_AUTORESEARCH_VERIFIER_KEY=<32+ byte secret> \
  python ../template/scripts/verifier/verify_request.py \
    --request level3-counter-example/proposals/iter-08-promotion-request.json \
    --ledger level3-counter-example/state/experiment_ledger.jsonl \
    --metrics level3-counter-example/config/metrics.yaml \
    --enforcement level3-counter-example/config/enforcement.yaml \
    --out-dir /tmp/oar-example-out \
    --verifier-identity "smoke-test"
```

The `validate-examples.yml` CI workflow in this repo runs exactly this and asserts the expected status.
