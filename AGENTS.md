# AGENTS.md — Onboarding for AI integrating agents

You are reading this because someone handed you the URL of `open-autoresearch`
and asked you to integrate its protocol into a **host repo**. This file is
your operator's instruction sheet. Read it top-to-bottom before doing anything.

If you are the loop-driving agent (the one that actually runs experiments),
this file is not for you — read `PROTOCOL.md` cover-to-cover instead. This
file targets the **one-shot integrating agent** that bootstraps the host repo
once and then exits.

---

## Who you are

You are an **integrating agent**. Your job is bounded:

1. Copy this repo's `template/` scaffold into the host repo.
2. Walk the human through `template/BOOTSTRAP_QUESTIONS.yaml`.
3. Materialize the host's `autoresearch/config/*.yaml` files from the answers.
4. Freeze data splits, seed behavioral-equivalence fixtures, commit.
5. Exit.

You are **not** the agent that runs the research loop. After you exit, a
different process (or you in a different mode) drives the loop, governed
fully by `PROTOCOL.md`.

---

## Read these in this order

1. This file (you're here).
2. `PROTOCOL.md` §1.5 "Start Here" — the Level-1 implementation path.
3. `PROTOCOL.md` §3.1 + §3.1.1 — what `protected_paths` means and why
   enforcement is out-of-band.
4. `docs/adoption-levels.md` — what each maturity level promises.
5. `template/README.md` — quick map of the scaffold you're about to copy.

Skim, don't read end-to-end. The full PROTOCOL.md is for the loop-driving
agent. The sections above plus the inline cross-references in this file are
enough for bootstrap.

---

## Your bootstrap workflow

Do these in order. Steps that change state in the host repo end with an
explicit `Commit:` line — make exactly that commit before moving on.
Steps that only collect information (ask questions, print summaries) don't
need a commit of their own.

**1. Ask for the host repo path, then confirm its state.**
Ask the human the first questionnaire question (`host_repo_root_path`) so
you know which directory to operate in. `cd` into it. Then run
`git status`. If there are uncommitted changes, ask the human whether to
stash, commit on an existing branch, or abort. Don't proceed on a dirty
tree. No commit yet (no state changed).

**2. Create the integration branch.**
`git checkout -b feature/autoresearch-bootstrap` (or whatever convention the
host repo uses for feature branches). No commit yet (branch creation
doesn't need one).

**3. Copy `template/` — but first, check whether `autoresearch/` already
exists in the host repo.** If it does, the host is in one of three states:
  - **Empty or partial bootstrap** (some files copied, no real campaign
    yet): ask the human whether to clean-slate or resume. If resume,
    diff their `autoresearch/` against the canonical `template/` and ask
    per-file before overwriting.
  - **Mid-campaign state** (`state/experiment_ledger.jsonl` has entries,
    OR `bootstrap-answers.yaml` exists): **stop immediately.** This is
    not a bootstrap — it's a re-bootstrap, which is a separate workflow
    (see `docs/adoption-levels.md` for the migration path). Don't
    overwrite live campaign state.
  - **Fresh** (no `autoresearch/` directory): proceed.
Once you've confirmed it's safe to write, copy this repo's `template/`
directory into the host repo as `autoresearch/`. Don't rename
`autoresearch/` — downstream paths in `protected_paths.yaml` and example
workflows assume that exact name.
Commit: `chore(autoresearch): scaffold template at autoresearch/`.

**4. Walk the bootstrap questionnaire.**
Open `template/BOOTSTRAP_QUESTIONS.yaml` in this repo (not the host's copy).
Ask the human each remaining question (you already asked
`host_repo_root_path` in step 1) verbatim, in the order they appear.
Record answers in `<host>/autoresearch/bootstrap-answers.yaml` (a fresh
file you create — there's no `.example` for it). The questionnaire's
frontmatter shows the schema.

If the human doesn't know an answer, **stop** and report. Don't fabricate.
The questionnaire is the protocol's "informed consent" surface; faking it
defeats the point. The questionnaire's `default_if_unanswered` fields (if
any) are explicit-acceptance defaults — only use one when the human says
"use the default," never as a silent fallback.

Commit: `chore(autoresearch): record bootstrap answers`.

**5. Materialize configs from answers.**
For each `<host>/autoresearch/config/*.yaml.example`:
  - Copy to the same path without the `.example` suffix (e.g.
    `metrics.yaml.example` → `metrics.yaml`). Keep the `.example` file in
    place; it documents the schema for future reference.
  - In the new `.yaml` file, substitute every `<FILL_ME>` placeholder using
    the questionnaire answers. Each question's `maps_to` field names the
    config key.
  - Keep `protocol_version: "0.5"` exactly as written. Don't bump it.
Commit: `chore(autoresearch): materialize config from bootstrap answers`.

**6. Pin the data splits (`MANIFEST.json`, two modes).**
Per `PROTOCOL.md` §6.3.1, the host declares its train/val/test split in
`data/splits/MANIFEST.json`, which carries a `mode` discriminator (the `anyOf`
of `schema/split_manifest.schema.json`). Pick ONE mode:
  - **`mode: frozen`** (recommended default) — content-addressed: ask the human
    for the path to each split file, compute SHA-256, and write `protocol_version`
    `"0.5"` + `snapshot_id` + `val_set_version` + a `train`/`val`/`test` block
    each with `path`/`sha256`/`size_bytes`, plus `frozen_at`/`frozen_by`.
  - **`mode: declarative`** (for growing / forward-moving datasets) — a
    deterministic split RULE instead of persisted files: `protocol_version`
    `"0.5"` + `mode` + `val_set_version` + `split_rule` (with `split_key`) +
    `seed` + a Guard-B `dataset_fingerprint`
    (`source`/`version`/`date_window`/`row_count`/`schema_hash`).
A manifest with no `mode`, or that mixes the two modes' keys, **fails closed** in
`bootstrap_verify.py`. Add `data/splits/**` to
`<host>/autoresearch/config/protected_paths.yaml` if it isn't already (the
template default includes it).
Commit: `chore(autoresearch): pin data splits per §6.3.1`.

**7. Seed behavioral-equivalence fixtures.**
Per `PROTOCOL.md` §1.5 + §17.1.1, the loop relies on a small set of golden
inputs to detect silent evaluator drift. Ask the human for **3–5
representative inputs** to the host's evaluation function (the §1.5
Level-1 checklist calls for 3–5, not "one is enough"; if fewer than 3 are
available, record the bootstrap as `partial` in `bootstrap-answers.yaml`
and flag the gap for the human to close before the first promotion
attempt). Then, for each fixture:

  - Run the host's evaluator on the input **once** and capture the output
    dict `{metric_name: value, ...}`. The agent doing the bootstrap MUST
    NOT skip this step — these values become the "ground truth" the loop
    later compares against. The protocol intentionally has no
    auto-record CLI; that would let the loop self-attest its own
    baselines, which is the exact failure mode §17.1.1 exists to prevent.
  - Write one JSON file per fixture at
    `<host>/evaluation/fixtures/<fixture_id>.json` with shape:
    ```json
    {
      "fixture_id": "fx-001",
      "description": "one-line description",
      "input": { ... opaque payload the evaluator accepts ... },
      "golden_outputs": { "<metric>": <number>, ... }
    }
    ```
  - The metric keys in `golden_outputs` MUST match the names declared in
    `metrics.yaml` (`primary_metric.name`, every `secondary_metrics[].name`,
    every `guardrails[].name`). Mismatches surface as `CONFIG ERROR` from
    the script.

After writing the fixtures, run the verifier (it checks-only — no
recording):
```
python template/scripts/behavioral_equivalence.py \
  --metrics autoresearch/config/metrics.yaml \
  --fixtures evaluation/fixtures \
  --evaluator <module.path>:<compute_fn>
```
Exit 0 = fixtures + evaluator round-trip cleanly within tolerance. Exit
non-zero = read the printed reason; fix and re-run before continuing.

The template's `protected_paths.yaml.example` already lists
`evaluation/fixtures/**` as protected, so no path additions are needed
here.
Commit: `chore(autoresearch): seed behavioral-equivalence fixtures`.

**8. Verify and hand off.**
First, run the bootstrap smoke test:
```
python template/scripts/bootstrap_verify.py <host-repo-root>
```
Exit 0 = every required file/key is present and well-formed. Exit 1 = read
the printed `[FAIL]` lines, fix what's missing, re-run. Don't proceed to
hand-off with any FAIL lines.

The smoke test deliberately does NOT round-trip the host evaluator against
the BE fixtures (that requires importing host code, which this script
won't do). For the round-trip check, run `behavioral_equivalence.py`
directly with `--evaluator <module.path>:<fn>` after bootstrap_verify
passes — or document the call as a follow-up the human runs themselves.

Then print a summary to the human:
  - Files created.
  - Configs materialized.
  - Maturity level the host is starting at (read from `maturity_level_target`
    in the answer file — usually 1).
  - Highest label achievable at this level (per `PROTOCOL.md` §13.3 + §24):
      - Level 1 → `level1_branch_winner`
      - Level 2 → `level2_branch_winner`
      - Level 3+ → `branch_winner` (and `promoted`/`low_evidence_promoted`
        gated by `enforcement.mechanism` and §18 criteria)
    Do not hardcode `level1_branch_winner`; derive from the answer.
  - What the human needs to do before the first proposal (review the
    materialized configs; satisfy themselves about the choice of enforcement
    mechanism; run the BE evaluator round-trip if you skipped it).
Open the PR for review. Exit. No final commit needed (the summary is a
printout, not a file change).

---

## What NOT to do

These are not stylistic preferences. Each one corresponds to a known way
the protocol's guarantees fail.

- **Don't modify the host's copy of `PROTOCOL.md`.** It is a reference, not
  a project file. If the human says it needs changes, that is an RFC against
  THIS repo, not an edit to their copy. The host should not even have a
  copy — they should symlink, vendor a pinned commit, or just point to the
  upstream URL.
- **Don't self-attest promotion packets.** The process that generates a
  `promotion_request` and the process that emits a `promotion_packet` must
  be distinct. v0.3 had a self-attest hole; v0.4 closes it structurally
  (see `PROTOCOL.md` §10.5). If your runtime can only run a single process,
  set `enforcement.mechanism: none` honestly. Don't paper over it.
- **Don't downgrade `evaluator_equivalence.rtol`** below the v0.4 default
  (1e-4 for fp32) without recording the reason in `bootstrap-answers.yaml`
  AND in a project ADR. The default is calibrated to catch ~1e-3 behavioral
  drift while passing reduction-order changes; tightening it without
  justification produces false positives that train the team to ignore the
  signal.
- **Don't claim a `promoted` label** from the loop unless
  `enforcement.mechanism != none` AND a non-agent verifier emitted the
  packet. The protocol's label vocabulary uses `level1_branch_winner` /
  `level2_branch_winner` / `branch_winner` (per §13.3) precisely so that
  level-conditional labels can't be confused with deployment-grade
  `promoted` ones.
- **Don't run `verify_request.py` from inside the loop-driving agent's
  process.** The verifier is structurally separate. If your runtime can't
  enforce that separation, accept `not_deployable: true` in the packet
  output. The verifier exits 1 in that case by design.
- **Don't commit secrets, API keys, or model weights** as part of the
  bootstrap. The scaffold doesn't need any of those. If the host's existing
  `.gitignore` doesn't cover model artifacts, add a line.

---

## Final checklist (what success looks like)

A successful bootstrap leaves the host repo with:

- `autoresearch/` directory, populated.
- All `autoresearch/config/*.yaml` files materialized (no `<FILL_ME>` left).
- `autoresearch/bootstrap-answers.yaml` recording every answer (for
  reproducibility and future re-bootstraps).
- `data/splits/MANIFEST.json` populated for exactly ONE §6.3.1 mode (the `anyOf`
  of `schema/split_manifest.schema.json`): `mode: frozen` (snapshot ID, per-split
  content hashes + sizes, val_set_version, freeze timestamp + freezer identity) OR
  `mode: declarative` (split rule + seed + Guard-B dataset fingerprint). A
  missing/mixed `mode` fails closed.
- `evaluation/fixtures/*.json` with 3–5 fixture files (or a recorded
  `partial` flag in `bootstrap-answers.yaml` if fewer), and the
  behavioral-equivalence script exits 0 against them.
- `template/scripts/bootstrap_verify.py <host-repo-root>` exits 0 (all
  required files present, no `<FILL_ME>` placeholders left, all schemas
  match).
- A clean commit history on the integration branch with one commit per
  state-changing workflow step (steps 3, 4, 5, 6, 7 — usually 5 commits).
- An open PR titled `chore(autoresearch): bootstrap integration` with this
  AGENTS.md linked in the body for the human reviewer.

You are done. The loop-driving agent (or its operator) takes over from
here. Do not start the first proposal yourself unless the human explicitly
asks for it as a separate, scoped task.

---

## If you get stuck

The bootstrap takes ~30–45 min of agent + human time. If you have been at
it longer than that, something is wrong with the protocol's fit for this
project. Stop and report to your operator. Do not fake an answer to keep
moving.

If the questionnaire is missing something material — i.e., the host project
has a constraint the questionnaire doesn't surface — open an issue against
THIS repo (not the host) tagged `bootstrap-gap` describing the missing
question. The protocol gets better from real adoption attempts; that
feedback is wanted.
