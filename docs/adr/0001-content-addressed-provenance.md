# ADR 0001 — Content-addressed provenance (Level 1)

- Status: Accepted
- Date: 2026-06-13
- Deciders: @rbudnar
- Related: `docs/proposals/2026-06-13-provenance-redesign.md`, `PROTOCOL.md` §14.1, downstream ActivityEncoder PR #93

## Context

`experiment_record.schema.json` **required** `git_sha_before` / `git_sha_after`, and
`log_experiment.py` filled them from `git rev-parse HEAD` at log time. In the real
workflows this template targets, a commit SHA is structurally incompatible with
auditability:

- Campaigns run on **off-main, often ephemeral** experiment branches; the SHA never
  reaches `main` and dangles after branch deletion + GC.
- **Squash-merge** destroys the original commit SHAs.
- Empirically (ActivityEncoder VLA campaign, PR #93): every landed record's SHA was
  an off-main branch commit, `before == after` for all of them, and the field never
  identified an experiment's code state — it recorded "what HEAD was when I wrote the
  ledger row." A reviewer correctly flagged that landed records referenced commits the
  repo could not resolve, defeating the stated auditability goal.

So the required field promised reproducibility it could not keep — decorative
provenance from day one.

## Decision

Adopt **Level 1** of the content-addressed provenance model in the template:

1. A record's auditability is the **structured record itself** (hypothesis, params,
   metrics, lineage), which is durable on `main`.
2. Records carry a **non-authoritative breadcrumb triple**: `source_commit`,
   `source_branch`, and `resolvable_from_main` (true only if `source_commit` is an
   ancestor of `main`). This makes (un)auditability of the commit pointer *visible*
   instead of an implied promise.
3. `git_sha_before` / `git_sha_after` are **demoted to deprecated-optional** (dropped
   from `required`, kept as accepted properties). Legacy records stay valid;
   `log_experiment.py` no longer emits them but still accepts the deprecated
   `--git-sha-before` / `--git-sha-after` flags as aliases that populate
   `source_commit` (back-compat for vendored host scripts).
4. **Validators never resolve commits** to gate validity.
5. **Protocol stays 0.5.** This is a backward-compatible JSON-Schema relaxation (drop
   two `required` entries, add optional properties); no `PROTOCOL_VERSION` bump and no
   migration script.
6. `template/schema/**` is added to `CODEOWNERS` and `protect-protocol.yml` so the
   record contract is governance-gated directly, not only transitively via
   `PROTOCOL.md`.

## Drivers

- The dangling-commit blocker is real (PR #93) and structural, not a one-off.
- Back-compat with the just-shipped Protocol 0.5 consumer (ActivityEncoder PR #93
  stamped `protocol_version: "0.5"` + the triple). A 0.6 bump would orphan it.
- The template is vendored by host repos, so CLI back-compat matters (kept the old
  flags as aliases) — this intentionally diverges from PR #93, which removed them
  because it had no external callers.
- `content_sha256` immutability: example ledger shards are content-addressed and
  referenced by hash in a promotion packet, so they are **not** re-stamped.

## Alternatives considered

- **Bump to Protocol 0.6 + migration.** Clean semantic signal, but orphans the shipped
  0.5 consumer, breaks back-compat, trips `protocol-version-consistency`, and pulls the
  Level-2/3 migration deliverable forward. Rejected.
- **Re-stamp the example campaigns to the new shape.** Strongest "model the protocol,"
  but mutates a content-addressed hash chain (every shard's `content_sha256` would have
  to be recomputed in `iter08-promotion-request.json` or `verify_request.py`'s
  `rule_2_references_rehash` reports mismatches and reddens `validate-ledger.yml`).
  High recompute-error surface for a teaching nicety already covered by the §14.1
  example + tests; loses the back-compat exemplar. Deferred.
- **Add Guard-D validator enforcement now** (warn on `git_sha_*`-only / triple-missing).
  Listed under Level 1 in the proposal, but a warn-on-`git_sha_*` check fires on the
  repo's own legacy example campaigns. Deferred so it can land with the example
  migration.

## Consequences

- Honest provenance with zero CI-blocker risk; legacy records and downstream consumers
  keep validating.
- The copy surface (PROTOCOL.md §14.1) and the test fixtures model the new shape; the
  dated example campaigns remain legacy back-compat exemplars by design (two
  conventions coexist for legacy records, intentionally).
- The schema contract is now properly governance-gated.

## Follow-ups (future work, not this change)

- Guard-D validator enforcement + example-campaign migration (land together).
- Level 2: run-start code capture + canonical serialization + content-addressed
  (git-LFS) store + fail-closed two-tier validator.
- Level 3: data/env fingerprints + one-command `reproduce`.
- Fix the unrelated stale `autoresearch/PROTOCOL_VERSION = 0.4` reference in
  `docs/adoption-levels.md` (pre-existing, provenance-unrelated).
