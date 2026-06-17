# ADR 0002 — Declarative data splits + comparison-set identity (§6.3.1)

- Status: Accepted
- Date: 2026-06-16
- Deciders: @rbudnar
- Related: `docs/proposals/2026-06-16-dynamic-splits.md`, `docs/proposals/2026-06-13-provenance-redesign.md` (Guard B), `PROTOCOL.md` §6.3.1 / §13.2.1 / §14.1 / §17.6 / §18, downstream OutcomePredictor PR #1021

## Context

`PROTOCOL.md` §6.3.1 **mandated** frozen split files content-hashed into
`data/splits/MANIFEST.json`. That is the strongest anti-cheating shape — the agent
cannot regenerate it — but it breaks for **growing datasets** whose train/val
window keeps moving forward (freezing parquet goes stale immediately; every
re-freeze is a protected-path change). Hit in OutcomePredictor PR #1021 and earlier
in ActivityEncoder.

Research also surfaced a **latent gap in the frozen model**: §13.2.1 only
*preferred* comparing baseline/candidate "on the same examples"; nothing **checked**
that two compared runs used the same `val_set_version` / split. The record schema
didn't capture split identity; `verify_request.py`'s 10 rules had no
data/split-identity check. Splits could silently diverge between two "compared"
runs.

The owner's ratified principle: shared/frozen comparison sets are *preferred* but
not always practical. Provide a declarative MODE + best-practice guidance + honest
warnings; let the implementing project/agent pick the tier — **mechanism +
guidance, not a hard mandate**.

## Decision

Add a two-mode split model to §6.3.1 and close the comparison-set gap, as mechanism
+ guidance + warnings:

1. `data/splits/MANIFEST.json` becomes an `anyOf` discriminated by `mode`:
   - **`mode: frozen`** (current, recommended default) — per-split content hashes,
     reconciled onto the shape `bootstrap_verify.py` already enforces
     (`{path, sha256, size_bytes}` per split + `snapshot_id` + `val_set_version` +
     `frozen_at`/`frozen_by`), with `row_ids_sha256` allowed as an alternative
     content hash. This **reconciles** the pre-existing inconsistency between the
     §6.3.1 prose example (which used `row_ids_sha256`+`size`) and the enforced
     shape — there is now one canonical frozen shape and both the prose and the
     code match it.
   - **`mode: declarative`** (new) — a split rule (`split_key`, ratio/cutoff,
     temporal OOS window) + `seed` + `dataset_fingerprint`. The fingerprint
     IDENTITY is `(source, version, date_window)` — **required** — so a
     growing/forward-moving dataset can be identified by its date range alone (a
     continuously-appended source cannot pin a stable `row_count`). `row_count`
     and `schema_hash` are **optional** integrity strengtheners: include them when
     a campaign pins a fixed materialized snapshot (they fail closed if
     present-but-degenerate and fold into the rule-11 comparison identity); omit
     them for a growing dataset. This is Guard B from the 2026-06-13 provenance
     redesign, promoted into §6.3.1 as a split mode.
   A partial/mixed manifest **fails closed**.
2. Each experiment record may carry an OPTIONAL `data_fingerprint` recording its
   split identity. Depth is project-chosen: strongest = a per-split
   `membership_sha256` (byte-level proof); lighter = `dataset_fingerprint` +
   `split_spec_hash` + `seed`. The schema accepts either. It is **NOT required and
   NOT via `anyOf`**, so existing records stay valid (unlike the provenance
   redesign, which DID force its shape via anyOf).
3. A new **non-failing** verifier rule `11_comparison_set_identity` compares the
   baseline's and candidate's recorded identity and sets `cross_dataset: true` + a
   note on the packet when they differ or cannot be confirmed identical. **Warn,
   don't gate** — the implementer chooses the evidence tier.
4. **Frozen stays the recommended default.** Declarative is first-class (no
   automatic promotion-label cap) when identities match, but it **weakens the
   agent-can't-regenerate property**; §6.3.1 and the threat model recommend frozen
   or a non-agent materialization for deployment-grade campaigns.
5. **Protocol stays 0.5.** Backward-compatible JSON-Schema relaxation (manifest
   `anyOf` includes the frozen form; the record identity field is optional). No
   `PROTOCOL_VERSION` bump and no migration script.

## Drivers

- The growing-dataset blocker is real (PR #1021) and structural, not a one-off.
- Back-compat with the shipped Protocol 0.5 consumers — a 0.6 bump would orphan
  them and trip `protocol-version-consistency`.
- The template is vendored by host repos, so CLI back-compat matters (the new
  `log_experiment` flags are additive; the old behavior with none of them is
  unchanged — no `data_fingerprint` emitted).
- The latent same-set gap is worth closing on its own; the declarative mode and the
  identity record are two halves of one fix.

## Alternatives considered

- **Auto-reject cross-dataset comparisons.** Rejected — too rigid for projects
  whose datasets must grow; the owner ratified warn-not-gate so the implementer
  chooses the tier. We surface `cross_dataset` on the signed packet so it is never
  silently ignored.
- **Force `data_fingerprint` via `anyOf` (like the provenance triple).** Rejected —
  it would invalidate every existing record. Split identity is recommended, not
  mandated, so it stays optional.
- **Keep frozen-only and tell growing-dataset projects to re-freeze constantly.**
  Rejected — fights the workflow; every re-freeze is a protected-path review.
- **Bump to Protocol 0.6 + migration.** Rejected — orphans shipped 0.5 consumers,
  trips `protocol-version-consistency`, no actual breaking change to justify it.

## Consequences

- Growing-dataset projects can express their split honestly and get back to
  `bootstrap_verify` green without re-freezing parquet daily.
- The same-set gap is closed: split identity is recordable, and a divergent
  baseline/candidate comparison is flagged on every packet.
- A new (cheap) attack surface: declarative mode is regenerable by an agent. Made
  VISIBLE in the threat model + §6.3.1 guidance; frozen remains recommended for top
  tiers.
- One canonical frozen shape across prose, schema, and `bootstrap_verify` — the
  pre-existing §6.3.1/code inconsistency is gone.
- `examples/` ship no `MANIFEST.json`, so they are unaffected; `behavioral_equivalence.py`
  fixtures are split-independent. No migration.

## Follow-ups (future work, not this change)

- Host follow-up (OutcomePredictor PR #1021): re-sync the vendored `autoresearch/`
  scaffold to this upstream commit, then express `data/splits/MANIFEST.json` in
  `mode: declarative`.
- Optionally ship a declarative example campaign under `examples/`.
- A future tier could MATERIALIZE the membership hash automatically in a runner
  wrapper (pairs with the provenance redesign's Guard A capture-from-the-run).
