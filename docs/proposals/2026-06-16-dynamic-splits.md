# Proposal: declarative / dynamic data splits (§6.3.1) + comparison-set identity

Status: ACCEPTED (mechanism + guidance + warnings; see `docs/adr/0002-declarative-data-splits.md`).
Author: rbudnar + agent. Date: 2026-06-16.
Origin: real adoption pain — `OutcomePredictor` PR #1021 (and earlier `ActivityEncoder`)
hit the frozen-only §6.3.1 model on a dataset whose train/val date window keeps
moving forward. Freezing parquet goes stale the day after you freeze it. This is
the same family as the 2026-06-13 content-addressed-provenance redesign, and it
promotes that redesign's Guard B (`data_fingerprint`) into §6.3.1 as a split mode.

---

## 1. Problem (root cause, not symptom)

`PROTOCOL.md` §6.3.1 **mandated** frozen split files content-hashed into
`data/splits/MANIFEST.json` — the agent cannot regenerate them, which is exactly
the anti-cheating property we want. But it has two real failures:

- **Growing datasets.** For a production dataset that grows daily, the
  train/val/test window keeps moving forward. A frozen parquet snapshot is stale
  immediately; you would re-freeze constantly, and every re-freeze is a protected-
  path change requiring out-of-band review. The frozen-only model fights the
  workflow instead of serving it. (Hit in OutcomePredictor PR #1021; earlier in
  ActivityEncoder.)

- **A latent gap in the frozen model itself.** §13.2.1 only *prefers* comparing
  baseline and candidate "on the same examples" (PROTOCOL.md:937). Nothing
  **checked** that two compared runs used the same `val_set_version` / split. The
  record schema didn't capture split identity at all; `verify_request.py`'s 10
  rules included no data/split-identity check. So splits could **silently diverge**
  between two "compared" runs.

The owner's ratified principle: shared/frozen comparison sets are *preferred* but
not always practical. The protocol should provide a declarative MODE + best-
practice guidance + honest warnings, and let the implementing project/agent pick
the tier — **mechanism + guidance, not a hard mandate**. Strongly recommend
identical holdout observations; never *silently* treat divergent splits as
comparable.

## 2. Principle

A split is identified by **durable, content-addressed identity**, not necessarily
by frozen files. Frozen files are the strongest such identity (and stay the
recommended default); a deterministic rule + seed + dataset fingerprint is a
weaker-but-first-class identity for datasets that must grow. Whatever the mode,
each compared run **records** its split identity so "same set" is explicit and
checkable, and a divergent comparison is **flagged, never silently accepted**.

## 3. Design (posture: two modes via `anyOf`, stay protocol 0.5)

Mirror the provenance redesign's back-compat move (schema `anyOf`, no version
bump, CHANGELOG "Unreleased"). `data/splits/MANIFEST.json` becomes an `anyOf`
discriminated by `mode`:

- **`mode: frozen` (current, recommended default).** Per-split content hashes of
  the materialized files; immutable; strongest anti-cheating. The canonical shape
  is reconciled onto the one `bootstrap_verify.py` enforces — top-level
  `snapshot_id` + `val_set_version` + `train`/`val`/`test` each `{path, sha256,
  size_bytes}` + `frozen_at`/`frozen_by` — with `row_ids_sha256` allowed as an
  alternative content hash for row-indexed data (reconciles the old §6.3.1 prose
  example with the enforced shape).
- **`mode: declarative` (new).** A split **rule** (`split_key` e.g. member_id;
  `ratio`/`cutoff`; `temporal_oos_window`), a **`seed`**, and a
  **`dataset_fingerprint`** whose identity is `(source, version, date_window)` —
  required — with optional `row_count` + `schema_hash` strengtheners. A
  growing/forward-moving dataset is identified by its **date range alone** (a
  continuously-appended source cannot pin a stable `row_count`); a campaign that
  pins a fixed snapshot adds `row_count`/`schema_hash` (fail closed when present).
  This is Guard B from the 2026-06-13 provenance redesign, promoted into §6.3.1 as
  a split mode. No persisted files.

A partial/mixed manifest fails closed (neither anyOf branch is satisfied).

**Comparison-set identity (closes the latent gap, both modes).** Each experiment
record may carry an optional `data_fingerprint` recording which split it used.
Depth is project-chosen, with guidance:
- **Strongest:** a **materialized membership hash** — per-split sha256 over the
  sorted train/val/test ids, computed at run time. Byte-level proof of identical
  membership even without frozen files.
- **Lighter:** `dataset_fingerprint` + `split_spec_hash` + `seed`, which proves
  same-set only under deterministic materialization.
The schema accepts either; the protocol documents the tradeoff.

**Comparison-validity = warn, don't gate.** A new **non-failing** verifier rule
`11_comparison_set_identity` compares the baseline's and candidate's recorded
identity and sets `cross_dataset: true` + a note on the packet when they differ or
cannot be confirmed identical. It does **not** auto-reject — the implementer
chooses the evidence tier. Frozen stays the recommended default; declarative is
first-class (no automatic label cap) when identities match.

## 4. Pre-mortem (the part that matters)

- **"Declarative becomes a cheating hole."** Declarative *weakens* the
  agent-can't-regenerate property — an agent with the rule, seed, and dataset can
  re-materialize the split. Mitigation: frozen stays the recommended default; the
  threat model names this explicitly; §6.3.1 recommends frozen or a non-agent
  materialization for deployment-grade; the recorded identity + `cross_dataset`
  warning keep divergence visible.
- **"Warn-not-gate gets ignored."** The flag is surfaced on the signed packet
  (JSON + markdown), so it travels with the artifact and dashboards can display
  it. It is a deliberate policy choice (the owner's), not an oversight; the
  alternative (auto-reject) was explicitly rejected as too rigid for projects
  whose datasets must grow.
- **"Two modes double the surface and rot."** The two shapes share one `anyOf`
  schema and one `bootstrap_verify` code path; the partial/mixed case fails
  closed; tests cover frozen-valid / declarative-valid / mixed-invalid and the
  matching-vs-cross-dataset flag.
- **"Existing records / examples break."** The record `data_fingerprint` is
  OPTIONAL and not in any `anyOf`, so existing records stay valid. Examples ship
  no `MANIFEST.json`, so they are unaffected. No migration.
- **"Declarative + growing data silently leaks val exposure."** §17.6.3 now says:
  any change to the held-out membership is a holdout refresh — bump
  `val_set_version` (and the fingerprint), reset exposure, and comparisons that
  straddle the bump are `cross_dataset`.

## 5. Change list (files)

- `template/schema/split_manifest.schema.json` (NEW): the `frozen | declarative`
  `anyOf`, fail-closed on partial/mixed.
- `template/schema/experiment_record.schema.json`: OPTIONAL `data_fingerprint`
  object (NOT required, NOT via anyOf — existing records stay valid). `data_snapshot`
  retained.
- `template/scripts/bootstrap_verify.py`: `check_manifest` accepts EITHER mode
  (anyOf replicated in stdlib Python — no jsonschema dep), fails closed on mixed.
- `template/scripts/verifier/verify_request.py`: non-failing rule
  `11_comparison_set_identity` → `cross_dataset` flag + note on the packet.
- `template/scripts/log_experiment.py`: optional `--split-mode` /
  `--dataset-fingerprint` / `--split-spec-hash` / `--split-seed` /
  `--split-val-set-version` / `--membership-hash` flags that stamp
  `data_fingerprint` (emitted only when provided).
- `template/scripts/tests/`: coverage for `check_manifest` (frozen/declarative/
  mixed) and the comparison-validity flag (matching vs cross-dataset).
- `template/BOOTSTRAP_QUESTIONS.yaml` group 8: ask the split mode first, then
  frozen paths OR declarative fields; `check_questionnaire_drift` stays at 0 drift.
- `template/config/metrics.yaml.example`: note on `val_set_version` under
  declarative.
- `PROTOCOL.md`: §6.3.1 two-mode rewrite + best practices; §13.2.1 same-set note;
  §14.1 record field; §17.6.3 dataset-growth interaction; §18 `cross_dataset` flag.
- `docs/adr/0002-declarative-data-splits.md` (NEW), `CHANGELOG.md` Unreleased,
  `docs/adoption-levels.md`, `docs/threat-model.md`, `MIGRATION.md`.

## 6. The one-line summary

Add a first-class **declarative** split mode (rule + seed + `data_fingerprint`,
Guard B promoted into §6.3.1) alongside **frozen** (still the recommended
default), and close the latent "same comparison set" gap by recording each run's
split identity and warning — never silently gating — when a baseline/candidate
pair diverges. Mechanism + guidance + honest warnings; protocol stays 0.5,
back-compat via `anyOf`.
