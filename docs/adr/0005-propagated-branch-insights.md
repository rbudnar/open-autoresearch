# ADR 0005 - Propagated branch insights

- Status: Accepted
- Date: 2026-06-30
- Deciders: @rbudnar
- Related: GitHub issue #19, GitHub issue #16, GitHub issue #18, `PROTOCOL.md` Section 14.1 / Section 14.4 / Section 15, `template/schema/experiment_record.schema.json`

## Context

Protocol 0.5 made ledger records immutable and issue #18 added optional
operational tree fields, but the tree still had no structured way to carry a
lesson from an experiment leaf back into an ancestor or sibling branch. Local
`lessons[]` are useful narrative memory, yet they are too loose for branch
constraints because they often combine observed facts, interpretation, and
future policy in one sentence.

Roadmap issue #19 asks for an Arbor-inspired propagation step: an experiment
leaf should be able to update parent constraints, prune a sibling idea, or steer
the next follow-up while preserving the protocol's evidence and review posture.

## Decision

1. Add optional `branch_insights[]` entries to experiment records.
2. Keep `lessons[]` as local narrative memory. Use `branch_insights[]` only for
   tree-facing constraints intended to affect ancestor/root/sibling work.
3. Require each propagated insight to separate:
   - `raw_observation`
   - `distilled_insight`
   - `source_record_ids`
   - `updates_parent_ids`
   - `confidence`
4. Allow optional but structured branch-action fields:
   - `validated_constraint`
   - `invalidated_ideas`
   - `retirement_signal`
   - `review_status`
   - `review_record_ids`
5. Require every insight to carry at least one branch action:
   `validated_constraint` or `invalidated_ideas`.
6. Validate that source/review ids resolve to immutable ledger records, and that
   affected parent ids resolve or use the `baseline` sentinel.
7. Extend `regenerate_state.py` so derived `research_tree.json.views` includes
   compact `branch_insights` indexes by source record, affected parent,
   validated constraint, and invalidated idea.
8. Extend the promotion verifier so referenced ledger evidence cannot be
   promotion-valid while containing malformed branch insight propagation.
9. Keep Protocol 0.5. This is additive and optional; existing records require no
   migration.

## Alternatives considered

- **Reuse `lessons[]`.** Rejected because it does not separate measurement from
  interpretation and cannot support id resolution, review status, or affected
  parent indexing.
- **Add a separate insights ledger.** Rejected because it creates another state
  surface and merge concern. The immutable experiment record is already the
  natural evidence anchor.
- **Make propagated insights required.** Rejected because most experiments only
  need local lessons. Required propagation would create filler and weaken the
  signal.
- **Let the derived tree store hand-authored constraints.** Rejected because
  `research_tree.json` must remain derived and git-ignored.
- **Build an automatic branch pruner now.** Rejected as too much scheduler
  behavior. Reviewed insights can inform humans and future coordinators without
  making the reference scripts act as an autonomous planner.

## Consequences

- Positive: Research Directors can see which ancestor/root constraints were
  updated by leaf evidence without rereading every report.
- Positive: Negative results can explicitly invalidate sibling proposal shapes
  while preserving the source record and review posture.
- Positive: The feature remains language-neutral: direct JSON writers can opt in
  without using the Python helper.
- Positive: Draft, contested, and rejected insights stay visible but are not
  branch-retirement authority.
- Negative: Campaigns must choose when an insight is strong enough to propagate;
  validation can check shape and references, not scientific truth.
- Migration: None. Existing Protocol 0.5 artifacts remain valid.
