# ADR 0003 - Optional literature grounding fields

- Status: Proposed
- Date: 2026-06-27
- Deciders: @rbudnar
- Related: GitHub issue #17, `docs/references.md`, `docs/related-work.md`, `PROTOCOL.md` Section 2 / Section 3.3 / Section 9.0

## Context

Open-AutoResearch depends on a small set of research-system precedents, but those
precedents were split across `PROTOCOL.md`, `docs/related-work.md`, templates, and
roadmap discussion. That made it easy for agents to cite a source once, forget its
evidence status, or overclaim novelty when live web search was unavailable.

Issue #17 adds Arbor / Hypothesis-Tree Refinement as a current adjacent system.
That addition exposed the larger maintenance problem: the repo needs a durable
reference register and a lightweight way for proposal and literature artifacts to
record how their claims were grounded.

## Decision

1. Add `docs/references.md` as the maintained reference register for foundational
   systems, current evidence status, usage in this repo, and recheck dates.
2. Keep `PROTOCOL.md` Section 2 and `docs/related-work.md` as interpretive
   summaries, but route citation status and maintenance rules through
   `docs/references.md`.
3. Add optional, commented literature-grounding fields to the proposal and
   literature templates:
   - `literature_status`
   - `source_ideas`
   - `novelty_check`
   - `implementation_precedent`
   - `citation_risk`
4. Preserve offline behavior: `web_search_used: false` means the agent may only
   use the curated canon and host-project docs, must tag the brief as offline,
   and must avoid novelty claims.
5. Keep Protocol 0.5. The fields are optional comments in templates and examples;
   no existing artifacts become invalid and no migration script is required.

## Alternatives considered

- **Only update `docs/related-work.md`.** Rejected because it would leave evidence
  status and recheck cadence informal, recreating the same maintenance drift.
- **Require the new fields in proposal and literature artifacts.** Rejected
  because that would be a breaking contract change and would invalidate existing
  Protocol 0.5 artifacts for a review-aid field family.
- **Add a verifier or schema gate now.** Rejected because the observed problem is
  contributor and agent routing, not machine-verifiable artifact validity. The
  smaller control is a maintained reference register, template hints, CODEOWNERS,
  and protected-path review.

## Consequences

- Positive: Agents and reviewers have one maintained place to check foundational
  sources, evidence status, citation risk, and Arbor/HTR's role in the repo.
- Positive: New proposals can record literature grounding without changing the
  required artifact schema.
- Positive: Offline campaigns stay honest about canon-only grounding and cannot
  silently convert offline reading into novelty claims.
- Negative: The optional fields are advisory until a future host campaign proves a
  need for validation or verifier support.
- Migration: None. Existing Protocol 0.5 artifacts remain valid.
