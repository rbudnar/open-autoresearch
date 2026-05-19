# Migration

Each major / minor protocol bump may require host-project changes. This file walks through each transition.

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
