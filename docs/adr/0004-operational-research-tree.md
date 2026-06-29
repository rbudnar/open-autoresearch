# ADR 0004 - Operational research tree fields

- Status: Accepted
- Date: 2026-06-29
- Deciders: @rbudnar
- Related: GitHub issue #18, GitHub issue #16, `PROTOCOL.md` Section 14.1 / Section 15, `template/schema/experiment_record.schema.json`

## Context

Protocol 0.5 made the ledger sharded and immutable. That solved merge
conflicts and made `research_tree.json` derivable, but the tree still mostly
acted as reconstructed history. Roadmap issue #18 asks for an Arbor-inspired
next step: the tree should expose operational planning state such as frontier,
blocked, pruned, and merged nodes without making the derived tree a second
source of truth.

The existing `status` field also carries mixed meanings. Some values describe
evidence or promotion posture (`promising`, `branch_winner`, `promoted`), while
Arbor-style lifecycle questions ask something different: is this node proposed,
running, blocked, pruned, merged, or complete?

## Decision

1. Add optional tree-facing fields to experiment records:
   - `lifecycle_status`
   - `promotion_status`
   - `frontier_eligible`
   - `blocked_by`
   - `pruned_reason`
   - `merged_into`
   - `node_type`
2. Keep every new field optional. Existing Protocol 0.5 records that only carry
   the legacy `status` label remain valid.
3. Keep the immutable ledger as the source of truth. `research_tree.json` remains
   derived and git-ignored.
4. Extend `regenerate_state.py` so derived `research_tree.json` includes a
   `views` object for lineage order, active frontier, blocked nodes, pruned
   branches, merged/subsumed nodes, and promotion candidates by maturity level.
5. Extend `validate_ledger.py` and the promotion verifier with additive
   cross-field checks when records opt into lifecycle fields: blocked nodes need
   blockers, pruned nodes need a reason, merged nodes need a known target, and
   closed nodes cannot be marked frontier-eligible.
6. Keep Protocol 0.5. This is an additive schema/template/script change and does
   not require a migration.

## Alternatives considered

- **Make lifecycle fields required.** Rejected because it would invalidate
  existing Protocol 0.5 records and host ledgers for a planning view.
- **Infer lifecycle from legacy `status`.** Rejected for pruned/merged/blocked
  decisions because that would preserve the overloaded-status problem. Tools may
  infer promotion posture from known `status` labels, but lifecycle decisions
  require explicit fields.
- **Store frontier state in `research_tree.json`.** Rejected because it would
  turn a derived aggregate into writable state and reintroduce merge-conflict
  pressure.
- **Build a scheduler now.** Rejected as too much runtime surface. The smaller
  control is a deterministic derived view that future coordinator/executor work
  can consume.

## Consequences

- Positive: Research Directors can ask what is active, blocked, pruned, merged,
  or promotion-ready without hand-reading every ledger shard.
- Positive: Lifecycle state and promotion/evidence labels are now explicitly
  separated.
- Positive: The implementation remains language-neutral: direct JSON writers can
  opt into the fields without using the Python helper.
- Negative: The derived frontier is only as good as the optional fields written
  by the campaign.
- Migration: None. Existing Protocol 0.5 artifacts remain valid.
