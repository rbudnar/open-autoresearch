---
protocol_version: "0.5"
report_id: "20260518-150000-bbb004-invalidation"
ledger_entry_id: "20260518-150000-bbb004-invalidation"
event_type: "evaluator_drift_invalidation"
maturity_level: 3
status: "invalidated"
not_deployable: true
---

# Evaluator Drift: Behavioral-Equivalence Failure → Invalidation of iter-3

## What happened

The Implementation Worker for iter-4 (a separate proposal exploring a small refactor of `evaluation/metric_defs.py` for clarity — removing some duplicated helpers) committed the refactor and triggered the preflight check. The behavioral-equivalence test (`autoresearch/scripts/behavioral_equivalence.py`, per §17.1.1) ran the live evaluator against the golden fixtures and **failed on every fixture** by approximately 1e-5.

## Investigation

The refactor inadvertently changed the rounding mode used in one metric helper from `round-half-even` (Python's default banker's rounding) to `round-half-up` (a more common-sense, hand-rolled variant the refactorer thought was clearer). On the golden fixtures, this shifted metric outputs by ~1e-5, comfortably above the configured `rtol: 1e-4, atol: 1e-6` for fp32 metrics — BUT, on a 10k-example val set, the rounding shift accumulated to ~3e-5 per metric, which when compared against the new gold values (computed under round-half-even) produced systematic drift.

Wait — re-reading: the refactor changed the live evaluator's rounding. The goldens were computed before the refactor, so they reflect round-half-even. The live evaluator now uses round-half-up. The behavioral-equivalence test compares LIVE vs GOLDEN, and the live values shifted by ~1e-5 per fixture, tripping the tolerance.

## Human review verdict

Per §3.1 the change went to human review. The reviewer judged the rounding-mode change to be **semantic, not byte-equivalent** — round-half-up is genuinely different from round-half-even, and the choice should be deliberate, not a side-effect of a "clarity" refactor.

**Outcomes:**

1. The refactor was reverted on the `main` branch (per §3.1.1 ci_enforced enforcement, the refactor's PR was rejected by CODEOWNERS until reverted).
2. A separate, deliberate proposal to switch to round-half-up was opened — that's a real protocol-eligible candidate (probably no metric effect, but worth confirming with an experiment, not a refactor).
3. **iter-3's measured values are now suspect** because we cannot tell whether the candidate's NLL=0.823 was measured against round-half-even (which we now know is the canonical evaluator) or against an intermediate state during the refactor's review window.
4. Iter-3's metrics are retroactively marked `invalidated`. NOT `failed` — the candidate may still be correct; the comparison just isn't trustworthy under the current evaluator.

## What about the golden fixtures?

Because round-half-even is the canonical, post-revert evaluator, **the existing golden fixtures are still correct** — they were computed under round-half-even originally. No fixture refresh was needed; only the iter-3 metrics need re-grading under the canonical evaluator (iter-5).

## Counter-factual narrative (in case this confuses future readers)

If the refactor had INSTEAD been an intentional change to round-half-up:

- The protocol would have required the goldens to be archived under `evaluation/fixtures/archive/2026-05-18/`.
- A new golden set computed under round-half-up would replace them.
- Iter-3 would be re-graded against the new evaluator to see if the effect persists.
- The promotion packet for any candidate using metrics computed across the boundary would carry a note about which golden version they were measured against.

The "multiple updates per quarter is a warning sign" clause in §17.1.1 exists precisely because this kind of refactor can otherwise compound — every refactor invalidates prior results, and a campaign that refactors often will spend most of its budget on regrading rather than on actual research.

## Cost incurred by this event

- 0 GPU-hours (no new training runs).
- 0.5 wall-clock hours (human review + revert).
- 18k LLM tokens (Worker explaining the refactor, Director coordinating).
- 8 tool calls.
- 0 val queries (no evaluation against val happened during the event).

## Cost of NOT having the behavioral-equivalence test

Estimated. If the refactor had landed and iter-3's metrics had been treated as canonical, the eventual promotion packet would have been signed under a flawed comparison. A downstream production deployment from that packet could have shipped a model that doesn't actually beat baseline under the canonical evaluator. The §17.1.1 test caught this in 0.5 hours; an in-production catch would have been days or weeks.

## Lessons

- Behavioral-equivalence tests should run on every PR touching `evaluation/`, BEFORE merge. The campaign protocol caught this on the next iteration's preflight; a tighter loop would catch it in CI before any merge.
- "Clarity refactors" of evaluator code are the most dangerous kind because their author often assumes no semantic change.
- The protocol's "Multiple updates per quarter are a warning sign" clause is real; track this.
