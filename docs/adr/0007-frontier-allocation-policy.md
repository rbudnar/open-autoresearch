# ADR 0007 - Cost-aware frontier allocation policy

- Status: Accepted
- Date: 2026-07-01
- Deciders: @rbudnar
- RFC discussion: GitHub issue #21
- Related: GitHub issue #16, GitHub issue #18, GitHub issue #19, GitHub issue #20, `PROTOCOL.md` Section 8, `PROTOCOL.md` Section 17.6, `PROTOCOL.md` Section 17.7

## Context

Protocol 0.5 tracks validation exposure and campaign budgets, and the roadmap
has added operational tree fields, propagated branch insights, and a
coordinator/executor boundary. Level 3+ campaigns still needed a small policy
for deciding which eligible frontier node should receive the next unit of
budget.

The Arbor lesson is not to add a scheduler to Open-AutoResearch. The useful
contract is that a Research Director should spend budget deliberately: exploit
strong branches, preserve branch diversity while evidence is weak, use cheap
falsifiers before expensive validation, reserve enough evidence for promotion,
and stop or defer branches whose evidence or exposure posture has collapsed.

This repository remains a protocol and reference scaffold. The policy must be
recordable by non-Python hosts and by agents that do not use this repository's
reference scripts as their runtime machinery.

## Decision

1. Add `PROTOCOL.md` Section 8.1-8.6 for cost-aware frontier allocation in
   Level 3+ campaigns.
2. Define `frontier_rank_snapshot` as an auditable proposal/report payload,
   not as a required scheduler API.
3. Require the decision record to preserve the core budget dimensions from
   Section 17.7: validation queries, GPU hours, wall-clock, LLM tokens, and
   tool calls.
4. Add `reserve_budget_for_promotion` so exploration cannot silently consume
   the evidence budget needed for reruns, ablations, and verifier promotion.
5. Treat negative and inconclusive results as first-class allocation outcomes:
   branches may be deferred, stopped, pruned, quarantined, or used to request a
   holdout refresh.
6. Clarify that report-level frontier decisions are planning records. They only
   change derived `research_tree` views after the corresponding immutable
   ledger lifecycle fields are recorded.
7. Mirror the policy fields in proposal and result-report templates, and add
   optional configuration hints in `metrics.yaml.example`.
8. Add the Level 3 counter-example report showing a promising branch deferred
   because validation exposure is exhausted, a weak follow-up stopped, and a
   guardrail-regressed branch pruned.
9. Keep Protocol 0.5. This is additive and optional; existing records and host
   projects require no migration.

## Alternatives considered

- **Build a scheduler or queue runner.** Rejected because Open-AutoResearch is
  not a runtime framework, and downstream hosts may be non-Python or use their
  own orchestration.
- **Hard-code universal branch weights.** Rejected because the right weighting
  depends on domain, maturity level, cost tier, and uncertainty; the protocol
  should record the decision, not pretend to know every campaign's utility
  function.
- **Spend greedily on the current best branch.** Rejected because it can exhaust
  validation exposure or compute before promotion evidence can be produced.
- **Leave allocation as informal prose.** Rejected because reviewers need a
  compact record of why a branch was selected, deferred, or stopped.
- **Make frontier decisions mutate the derived tree directly.** Rejected
  because the immutable ledger remains the source of truth and `research_tree`
  stays derived.

## Consequences

- Positive: Research Directors have a small, auditable way to justify the next
  branch choice without adopting a scheduler.
- Positive: Promotion reserves make validation exposure and verifier evidence
  visible before the campaign spends scarce budget.
- Positive: Negative, inconclusive, and budget-blocked outcomes remain useful
  scientific evidence instead of disappearing from the frontier.
- Positive: The policy remains language-neutral; hosts can emit equivalent
  proposal/report fields without using the reference Python scripts.
- Negative: The policy depends on honest campaign accounting. It can require
  judgment when expected cost or uncertainty is approximate.
- Negative: The reference verifier does not prove that a frontier allocation
  was scientifically optimal; it only preserves the recorded rationale and
  budget posture.
- Migration: None. Existing Protocol 0.5 artifacts remain valid.
