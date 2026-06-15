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
7. Provenance presence is **enforced**: a schema `anyOf` requires either the full
   triple or the legacy `git_sha_*` pair (no provenance-less or partial-triple
   records), and the in-repo example campaigns are migrated to the triple so the whole
   repo models one shape.

## Drivers

- The dangling-commit blocker is real (PR #93) and structural, not a one-off.
- Back-compat with the just-shipped Protocol 0.5 consumer (ActivityEncoder PR #93
  stamped `protocol_version: "0.5"` + the triple). A 0.6 bump would orphan it.
- The template is vendored by host repos, so CLI back-compat matters (kept the old
  flags as aliases) — this intentionally diverges from PR #93, which removed them
  because it had no external callers.
- `content_sha256` integrity: example ledger shards are content-addressed and
  referenced by hash in a promotion packet, so re-stamping them requires recomputing
  those references in lock-step (done — see the Alternatives update below).

## Alternatives considered

- **Bump to Protocol 0.6 + migration.** Clean semantic signal, but orphans the shipped
  0.5 consumer, breaks back-compat, trips `protocol-version-consistency`, and pulls the
  Level-2/3 migration deliverable forward. Rejected.
- **Bump to Protocol 0.6 + migration** — rejected (orphans the shipped 0.5 consumer;
  trips `protocol-version-consistency`; pulls the Level-2/3 migration forward).

> **Update (same PR): the two items below were initially deferred, then adopted once
> the migration proved mechanical and fully gate-verified — the repo is now internally
> consistent rather than half-new/half-legacy.**

- **Re-stamp the example campaigns to the new shape — ADOPTED.** All 12 example shards
  carry the triple; the 5 ledger-record `content_sha256` references in
  `iter08-promotion-request.json` were recomputed from the shared
  `_canonical_record_bytes`. The feared risk (a stale hash reddening
  `verify_request.py`'s `rule_2_references_rehash` / `validate-ledger.yml`) is guarded by
  the verifier itself: `test_verifier_shard_load` asserts rule_2 passes, and the level3
  campaign still rejects on val-exposure with rule_2 green.
- **Enforce a complete provenance shape — ADOPTED (a cleaner form of Guard-D).** Rather
  than a warn-on-`git_sha_*` check (which would fire on legacy records), the schema now
  carries an `anyOf` requiring EITHER the full `source_commit`/`source_branch`/
  `resolvable_from_main` triple OR the legacy `git_sha_before`+`git_sha_after` pair (with
  `anyOf` support added to the stdlib validator). A provenance-less or partial-triple
  record is invalid; legacy records still validate via the legacy branch.

## Consequences

- Honest provenance with zero CI-blocker risk; legacy records and downstream consumers
  keep validating (legacy `anyOf` branch).
- The copy surface (PROTOCOL.md §14.1), the test fixtures, AND the example campaigns all
  model the new shape — one convention in-repo. Back-compat is proven by an explicit
  `make_legacy_record` test, not by leaving the examples on the deprecated shape.
- Every landed record is guaranteed to carry a provenance breadcrumb (schema `anyOf`).
- The schema contract is now properly governance-gated.

## Follow-ups (future work, not this change)

- Level 2: run-start code capture + canonical serialization + content-addressed
  (git-LFS) store + fail-closed two-tier validator.
- Level 3: data/env fingerprints + one-command `reproduce`.
