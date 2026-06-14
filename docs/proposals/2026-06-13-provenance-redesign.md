# Proposal: Content-addressed provenance (kill the dangling-commit problem)

> **Implementation status (read first):** This document is the full design +
> roadmap. **Only Level 1 is implemented in the template today** — the
> `source_commit` / `source_branch` / `resolvable_from_main` top-level triple,
> `git_sha_*` deprecation, and the honesty/docs changes (see
> `docs/adr/0001-content-addressed-provenance.md`). **Levels 2-3** below (the
> `provenance` object, run-fingerprint capture wrapper, content-addressed code
> store, fail-closed two-tier validator, `verify_provenance.py` / `reproduce.py`,
> data/env fingerprints, and the v0.6 migration) are **future work, NOT yet
> built.** Treat §3/§5/§6 as the plan for that future work, not a description of
> the current code.

Status: DRAFT / plan. Author: rbudnar + agent. Date: 2026-06-13.
Origin: real adoption in `ActivityEncoder` (PR #93) drew an adversarial blocker —
"12 landed records reference experiment commits the repo cannot resolve, which
defeats the auditability goal." This proposal fixes the root cause and is hardened
against a written pre-mortem of the obvious fix.

---

## 1. Problem (root cause, not symptom)

`experiment_record.schema.json` **requires** `git_sha_before` / `git_sha_after`.
`log_experiment.py` fills them from `git rev-parse HEAD` at **log time**. In the
real workflows this template targets:

- **Squash-merge** destroys the original commit SHAs.
- **Ephemeral experiment branches** mean the SHAs never reach `main`, and dangle
  after branch deletion + GC.
- **Multi-repo** consumers each have different history.

Worse, empirically (ActivityEncoder campaign): every record's SHA is an off-main
branch commit, `before == after` for all of them, and **8 experiments share one
SHA**. The field never identified an experiment's code state; it recorded "what
HEAD was when I wrote the ledger row." It was decorative provenance from day one.

**A commit SHA is history-position-dependent and branch-scoped. It is structurally
incompatible with squash + ephemeral branches. No amount of tagging or re-anchoring
fixes that cleanly.** (Tag preservation keeps the "dirty" commits alive forever and
pollutes refs; rejected.)

## 2. Principle

**Provenance must be carried by durable CONTENT, not by mutable git history.**
Auditability = a `(code, data, environment)` fingerprint triple that resolves from
`main` alone, forever, independent of any branch or commit lifecycle. Landing the
records on main already makes the *experiments* auditable (hypothesis, params,
metrics, lineage are self-contained); the only false promise on main today is the
commit pointer. Remove the false promise; add durable content for true reproduction.

## 3. Pre-mortem-driven design (the part that matters)

A 13-point pre-mortem of the naive "store a code patch" fix found that **every top
failure is process/lifecycle, not data-structure**. The schema being elegant buys
almost nothing. The guards below are ordered by the failure they kill (most→least
likely) and tiered by adoption level so Level 1 stays trivial (kills the
over-engineering/abandonment death).

### Guard A — Capture from the RUN, not from the LOG  (kills #1: capture ≠ reality)
The single highest-value change. Provenance must be captured at the moment the
experiment runs, bound to the run, including UNCOMMITTED working-tree state — not
reconstructed at ledger-write time.
- New `template/scripts/capture_provenance.py` (or a library hook) the **runner**
  calls at run start. It writes `state/runs/<id>/fingerprint.json` immediately:
  `code_state` hash (of declared `code_paths`, dirty state included), the diff
  blob, `dirty: bool`, `captured_at: "run_start"`.
- Ship a thin `autoresearch run <cmd>` wrapper that captures, runs, and finalizes —
  so capture is mechanical, not a discipline that erodes.
- `log_experiment.py` REFERENCES the run fingerprint by run id; it does not
  re-derive provenance. Batched / after-the-fact logging stays fine *as long as the
  run captured its own fingerprint*.
- Schema adds `provenance.captured_at`. Validator WARNS (Level 1) / FAILS (Level 2)
  on `log_time` capture — makes the `before==after` failure mode visible.

### Guard B — Capture DATA + ENVIRONMENT, not just code  (kills #2: reproduction impossible)
Code alone never reproduces an ML result. In ActivityEncoder, the 0.8TB raw data
was deleted mid-project and pyspark 4.0.0-vs-4.1.1 broke the run — neither is code.
- `provenance.data_fingerprint`: manifest hash of inputs — `(source table/path,
  version, date-window, row-count, schema-hash)`. NOT the data itself. Extends the
  existing `data/splits/MANIFEST.json` idea. Makes "the data was deleted" auditable
  and drift-detectable.
- `provenance.env_fingerprint`: lockfile hash + key resolved versions (python,
  framework, accelerator/driver, and any JVM/spark pins). Cheap: hash of `pip
  freeze` / `uv.lock` + a short allowlist of versions.
- Auditability contract becomes the TRIPLE `(code_state, data_fingerprint,
  env_fingerprint)`, not code alone.

### Guard C — Durable, reachability-checked, content-addressed store  (kills #3 store rot, #9 divergence, #10 brittleness)
- Pluggable `code_store` interface: content-addressed `put/get(hash)`, an explicit
  **retention** contract (never GC referenced blobs), and `verify_reachable(hash)`.
- **Determinism**: define a CANONICAL serialization for the code-state blob
  (normalize line endings to LF, sort file order, pinned diff/tar format,
  git-version-independent). Add a bootstrap test: same input → same hash across
  machines/git versions. Kills #10.
- **Atomicity**: `log_experiment` pushes the blob and verifies the put BEFORE
  committing the record (push-then-record). Fail the record if the push fails.
  Kills #9 (ledger/store divergence).
- **Canary**: a scheduled `verify-provenance` job (WITH store creds — not the
  creds-less PR CI) that checks every referenced hash still resolves in the store.
  Catches LFS prune / S3 lifecycle / access loss EARLY, not at autopsy. Kills #3.

### Guard D — Honest, fail-closed validator: "valid" ⇒ "auditable"  (kills #4 checkbox auditability, #8 dangling anchors)
- A record is VALID only if it carries a complete provenance triple, OR is
  explicitly flagged `provenance: { state: "none", reason: "..." }` — so
  "unauditable" is VISIBLE, never silent.
- Two validation tiers:
  - **PR-CI tier (no creds):** structural + provenance-completeness + hash-format +
    determinism self-check. **Fail-closed** on a missing triple (not format-only).
  - **Scheduled tier (creds):** blob reachability in the store.
- **Never resolve commits.** `source_commit` is a breadcrumb; `resolvable_from_main`
  is informational. Re-anchoring on merge is DELETED as a requirement —
  content-addressing makes it unnecessary (the blob is durable by hash, so there is
  nothing to re-stamp). Kills #8.

### Guard E — Keep capture cheap + ONE blessed path  (kills #5 abandonment, #11 backend sprawl)
- Capture is one wrapper / one library call the harness already makes. Near-zero
  friction.
- **ONE** blessed, end-to-end-tested backend (git-LFS default) with a shipped
  conformance test the backend must pass. Other backends (local dir, S3, Azure) are
  documented "advanced/at-your-own-risk." Avoids N half-working backends.
- Capture is **fail-soft for the run, logged**: if capture fails, the run proceeds
  but the record is flagged `provenance: incomplete` (visible). Never block the
  researcher; never silently lose provenance.
- `make provenance-report`: % of records with a complete triple, so erosion is
  managed, not discovered in the autopsy.

### Guard F — `code_paths` correctness  (kills #6: lever outside the glob)
- Default `code_paths` GENEROUS (whole repo minus data/artifacts/gitignored).
  Narrowing is opt-in.
- Capture the FULL working-tree diff into the blob (cheap text); `code_paths` only
  scopes what's hashed for `code_state` identity. So even a wrong glob keeps the
  full diff for forensics. Flag changes to tracked files outside `code_paths`.

### Guard G — Propagation: version + update-check, stop vendoring  (kills #7: vendored drift)
- Template ships VERSION + `autoresearch doctor` that warns when a consumer repo is
  behind upstream. Record stamps `template_version` AND `protocol_version` so
  cross-repo audits detect dialect drift.
- Recommend submodule/package reference over vendoring; ship a one-command updater.

### Guard H — Secret hygiene in captured diffs  (kills #12: leak → capture disabled)
- Capture runs a mandatory secret-scan (gitleaks/regex denylist) on the diff before
  store; redact or refuse + flag. Document that diffs may contain secrets.

### Guard I — Ship the reproduce tool, or no one audits  (kills #13: quiet death)
- `autoresearch reproduce <record_id>`: fetch code_state + data manifest + env,
  reconstruct a runnable checkout / the run command. Capture is only worth its cost
  if reproduction is ONE command. Close the loop or delete the apparatus.

## 4. Adoption-level tiering (so Level 1 stays trivial)

- **Level 1 (no store, no friction):** honest breadcrumb only — rename git_sha to
  `source_commit`/`source_branch` + `resolvable_from_main:false`; auditability =
  structured record (hypothesis/params/metrics/lineage). Validator never resolves
  commits. Guards D(format), G. NOTHING else required. This alone unblocks PR #93.
- **Level 2 (durable code provenance):** Guards A, C, E, F, H. `code_state` captured
  at run start, stored in LFS, fail-closed validator.
- **Level 3 (full reproduction):** Guards B, I. data+env fingerprints + reproduce
  tool. For teams that promote to production off these results.

## 5. Concrete change list (files)

- `template/schema/experiment_record.schema.json`: replace required `git_sha_*`
  with a `provenance` object (code_state/data_fingerprint/env_fingerprint/
  source_commit/source_branch/resolvable_from_main/captured_at/state). Keep
  git_sha_* accepted-but-deprecated for back-compat; add migration.
- `template/scripts/log_experiment.py`: stop deriving SHA as authority; reference
  run fingerprint; push-then-record; self-stamp `provenance.state`.
- New `template/scripts/capture_provenance.py` + `autoresearch run` wrapper.
- `template/scripts/_ledger_common.py`: canonical code-state serialization + hash.
- `template/scripts/validate_ledger.py`: two-tier, fail-closed on missing triple,
  never resolve commits, determinism self-check.
- New `template/scripts/verify_provenance.py` (scheduled, creds) + `reproduce.py`.
- `template/config/code_store.yaml.example` (backend: lfs|local|s3|azure) +
  `code_paths.yaml.example`.
- `PROTOCOL.md`: new §"Provenance" (content-addressed model), update §4 repo
  structure (`state/runs/<id>/fingerprint.json`, `state/code/` or store ref), §6
  init (capture wrapper).
- `docs/threat-model.md`: add the 13 pre-mortem failures as named threats + the
  guard that mitigates each.
- `docs/adoption-levels.md`: the Level 1/2/3 tiering above.
- Migration script v0.5 → v0.6.

## 6. Immediate path for ActivityEncoder PR #93 (Level 1, ship now)

We cannot reconstruct true per-experiment patches for past config-sweeps (the
content never existed per-experiment). So land #93 at **Level 1**:
1. Re-stamp the 22 records: demote `git_sha_*` to `source_commit` + add
   `source_branch: variable-length-autoencoder`, `resolvable_from_main: false`.
2. Auditability = the now-on-main structured record (hypothesis/params/metrics/
   lineage). Honest, no dangling-pointer promise.
3. Reply to the reviewer: provenance is content/structured, the commit is a
   non-authoritative hint, and the durable-code-capture model (this proposal) lands
   upstream for future campaigns. Link this doc.

## 7. The one-line summary

Stop pointing at commits. Point at content: capture `(code, data, env)` at run
time, store code/data/env blobs in a content-addressed store keyed by hash, keep
only hashes in the (tiny, in-git) ledger, validate fail-closed that every landed
record is auditable by durable means, and ship a one-command reproduce. Tier it so
Level 1 is just honesty and Level 3 is full reproduction.
