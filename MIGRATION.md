# Migration

Each major / minor protocol bump may require host-project changes. This file walks through each transition.

## Within v0.5 — declarative data splits + comparison-set identity (no data migration; one-line manifest `mode` add)

The two-mode §6.3.1 split model and the comparison-set identity record field are a
**backward-compatible** addition and the protocol stays 0.5. **No data migration is
required** — records are zero-touch — but existing frozen manifests need one trivial,
mechanical edit (a single `mode: frozen` line), not a data migration:

- **Existing frozen `MANIFEST.json` files need a one-line `mode: frozen` add.** The
  manifest is now the `anyOf` of a frozen and a declarative shape; the frozen branch
  is the same enforced shape (`{path, sha256, size_bytes}` per split + `snapshot_id` +
  `val_set_version` + `frozen_at`/`frozen_by`). The only required change is the
  explicit `mode: frozen` discriminator — add it so `bootstrap_verify` can select the
  frozen branch. **A manifest with no `mode` now fails closed, by design** (it cannot
  select a branch), so this edit is not optional for existing manifests, but it is a
  one-liner, not a data migration. `row_ids_sha256` is newly allowed as an alternative
  content hash but is not required.
- **Existing experiment records stay valid.** The new `data_fingerprint` split
  identity is OPTIONAL and not forced via `anyOf`, so records without it validate
  unchanged. Add it (any tier — from a lighter `dataset_fingerprint`+`seed` to a
  per-split `membership_sha256`) when you want the verifier's `cross_dataset`
  warning to have something to compare.
- **Adopting declarative mode** is opt-in: set `mode: declarative` and write
  `split_rule` + `seed` + `dataset_fingerprint` instead of the frozen file hashes.
  Frozen remains the recommended default; for deployment-grade campaigns prefer
  frozen or freeze a non-agent materialization of the declarative split.
- `examples/` ship no `MANIFEST.json`, so they are unaffected.

See `docs/adr/0002-declarative-data-splits.md` and
`docs/proposals/2026-06-16-dynamic-splits.md`.

## v0.4 → v0.5

**Scope:** The experiment ledger moves from a single append-only `state/experiment_ledger.jsonl` to a **directory of immutable per-record files** `state/ledger/<id>.json` (the new source of truth). Four files become DERIVED and git-ignored. A new committed `state/campaign.json` holds campaign metadata. The §10.5 promotion-request hashes are recomputed against the pinned canonical serializer.

### Required changes

1. **Run the migrator.** From the host project root:

   ```bash
   python3 autoresearch/scripts/migrate_ledger_v04_to_v05.py \
       --state-dir autoresearch/state/
   ```

   It splits each jsonl line into a field-preserving `state/ledger/<id>.json` shard (no field allow-list — additive consumer fields like `maturity_level`, `not_deployable`, nested `artifacts.mlflow` are preserved), stamps each record `protocol_version: "0.5"`, then regenerates the derived aggregates. It sets the per-record val-query inputs so the **derived** `val_exposure.json` counter REPRODUCES the prior committed counter, and **asserts equality or fails loudly** — if it aborts, the source counter and the per-record inputs disagree and must be reconciled by hand. It refuses to clobber existing shards unless `--force`.

2. **Create `state/campaign.json`** (committed, single-writer): `campaign_id`, `host_branch`, `scratch_branch`, `maturity_level`, `branch_policy`, and the root-node title/status. This is the home for campaign-level and curated metadata that has no source in any single record (§15). Without it, `research_tree.json` cannot regenerate its root/branch-policy content.

3. **Regenerate the derived aggregates** and confirm they reproduce the prior committed tree/counter:

   ```bash
   python3 autoresearch/scripts/regenerate_state.py --state-dir autoresearch/state/   # or `make ledger`
   python3 autoresearch/scripts/validate_ledger.py --ledger-dir autoresearch/state/ledger/   # every record schema-valid, ids unique, parent_ids resolve
   ```

4. **Git-ignore the derived files** and stop tracking them:

   ```bash
   git rm --cached autoresearch/state/experiment_ledger.jsonl \
                   autoresearch/state/research_tree.json \
                   autoresearch/state/val_exposure.json \
                   autoresearch/state/INDEX.md
   ```

   Add those four `state/*` paths to `.gitignore` (see `template/.gitignore`). Add `state/budget_ledger.jsonl merge=union` to `.gitattributes`. Keep `state/ledger/*.json` **tracked**.

5. **Recompute promotion-request hashes.** Any committed `promotion_request.{json,md}` carries `content_sha256` references over ledger record bytes. Because the `0.4 → 0.5` stamp changes the hashed bytes (and trailing-zero float loss can change them independently), every ledger-id-based `content_sha256` MUST be recomputed against the pinned canonical serializer (`_ledger_common._canonical_record_bytes`: compact, insertion order, `ensure_ascii=False`, no trailing newline) applied to the stamped-0.5 record. Path-based hashes (e.g. a `skeptic_review` reference by file path) do NOT change. The §10.5 verifier reads the `state/ledger/` shard directory and re-hashes via the same shared helper, so the recomputed values must match exactly.

6. **Repoint runtime readers.** Anything that named `experiment_ledger.jsonl` as the source of truth (e.g. a `tracking_policy.yaml` `ledger_policy.source_of_truth`) must point at the `state/ledger/` directory, and any `protocol_version` it asserts bumps `0.4 → 0.5`. Readers regenerate aggregates before reading them (a fresh clone has no derived files until `make ledger` runs); do not rely on file mtime for staleness.

7. **Bump the version stamp.** `autoresearch/PROTOCOL_VERSION` (and `template/PROTOCOL_VERSION`) `0.4 → 0.5`; the PROTOCOL.md header is `0.5`. Update any test/CI assertions that pinned `0.4`.

### Vendoring note

Consumers vendor `schema/` and `scripts/` as a flat copy of the template (no submodule). Record the upstream commit SHA the copy came from (a `VENDOR.lock` is the conventional place) so CI can detect drift between the vendored copy and upstream.

## v0.3 → v0.4

**Scope:** Polish pass after a second dual-voice review of v0.3. No conceptual redesign; many tightenings.

### Required changes

Update `metrics.yaml`:

- Bump `protocol_version: 0.4`.
- **Per-metric `aggregation` (`mean` | `sum` | `count` | `ratio`) and `eval_dtype` (`fp32` | `bf16` | `fp16` | `int`) are now required** for primary, secondaries, guardrails, subgroups.
- Guardrails now require `direction:` (`maximize` or `minimize`) — the direction-aware decision rule (§13.2.1) branches on it. v0.3 example omitted direction on guardrails; v0.4 requires it.
- Tighten `evaluator_equivalence` tolerances if you copied v0.3 defaults: fp32 reductions over ~10k elements need `rtol: 1e-4`, not `1e-5`. The v0.3 defaults will false-positive on benign refactors. Override per-metric if necessary; ensure tolerance ≤ 0.1 × `minimum_meaningful_delta`.
- Add `budgets.per_iteration_caps_by_level` (or accept the defaults). v0.3 had a single 200k token cap which is too tight for Level-4 multi-role work.
- Add `val_set_exposure_budget` if not already present.

Update `protected_paths.yaml`:

- Add `data/splits/MANIFEST.json` to `protected_paths` (new in v0.4 — see §6.3.1).
- Add `evaluation/fixtures/**` if not already covered.

Update `state/`:

- Add an empty `val_exposure.json` (`{"protocol_version":"0.4","queries":0,"val_set_version":1}`).
- Add an empty `budget_ledger.jsonl`.

Update `scripts/`:

- The `verifier/` subdirectory is new in v0.4 — the agent no longer self-signs promotion packets. Copy `template/scripts/verifier/verify_request.py` and `sign_packet.py` from this repo, or wire your CI to call them. If you previously emitted `promotion_packet.{md,json}` from the agent, those become `promotion_request.{md,json}` — see §10.5.

Update labels / dashboards:

- Any Level-1 or Level-2 result that was previously labeled `branch_winner` becomes `level1_branch_winner` / `level2_branch_winner`. Plain `branch_winner` is now reserved for Level 3+.
- Every label-carrying artifact must include `maturity_level: <N>` and `not_deployable: true|false` frontmatter.

Update `§18` consumers:

- The promotion gate grew from 13 to 17 criteria. The added criteria (14–17) cover val-exposure exhaustion, total budget caps, promotion-packet validity, and the maturity-level ≥ 3 prerequisite. Criterion 2 is now direction-aware.

### Backward-compatibility shim

There is no automated v0.3 → v0.4 migration script in this release. The diff is small enough to apply by hand or via `sed`. If you maintain many host projects, write one and contribute it.

## v0.2 → v0.3

(Internal-draft transition; no public artifacts to migrate.)

The notable user-visible change was the introduction of `§1.5` Start Here, the `§17.6` validation-exposure policy, and the `§17.7` budget accounting. If you happen to have a v0.2 setup, follow the v0.3 → v0.4 steps above and you'll inherit both transitions.

## v0.1 → v0.2

(Internal-draft transition; no public artifacts to migrate.)

The v0.1 → v0.2 transition was substantial: out-of-band enforcement requirement (§3.1.1), citation status table (§2), role-separation modes (§5.0), cost-tier seed counts (§6.1), candidate/component/stack definitions (§11.1.1), the default statistical rule (§13.2.1), tolerance-based behavioral equivalence (§17.1.1), operational realities (§17.5), counter-example pattern (§22a), and reconciled maturity levels (§24). If you adopted v0.1 internally, prefer to start over from v0.4 rather than trying to migrate piecewise.

## General notes

- The protocol's semver policy lives in `PROTOCOL.md` §0. Breaking changes only on major bumps; v0.x → v0.y may include breaking changes since we are pre-1.0.
- Every artifact (ledger entries, proposals, reports, packets) must carry `protocol_version: <version>` so downstream tooling can detect mismatches.
- When in doubt, regenerate artifacts under the new protocol rather than migrating them — the protocol's anti-overfit story (§17.2) prefers a fresh holdout over carried-over results across versions.
