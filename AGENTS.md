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

Do these in order. Each step is atomic; commit at the end of each.

**1. Confirm host repo state.**
Run `git status` in the host repo. If there are uncommitted changes, ask the
human whether to stash, commit on an existing branch, or abort. Don't proceed
on a dirty tree.

**2. Create the integration branch.**
`git checkout -b feature/autoresearch-bootstrap` (or whatever convention the
host repo uses for feature branches).

**3. Copy `template/`.**
Copy this repo's `template/` directory into the host repo as `autoresearch/`.
Don't rename `autoresearch/` — downstream paths in `protected_paths.yaml`
and example workflows assume that exact name. Commit:
`chore(autoresearch): scaffold template at autoresearch/`.

**4. Walk the bootstrap questionnaire.**
Open `template/BOOTSTRAP_QUESTIONS.yaml` in this repo (not the host's copy).
Ask the human each question verbatim, in the order they appear. Record
answers in `<host>/autoresearch/bootstrap-answers.yaml` (a fresh file you
create — there's no `.example` for it). The questionnaire's frontmatter
shows the schema.

If the human doesn't know an answer, **stop** and report. Don't fabricate.
The questionnaire is the protocol's "informed consent" surface; faking it
defeats the point.

**5. Materialize configs from answers.**
For each `<host>/autoresearch/config/*.example.yaml`:
  - Rename to `*.yaml` (drop the `.example` infix).
  - Substitute `<FILL_ME>` placeholders using the questionnaire answers.
    Each question's `maps_to` field names the config key.
  - Keep `protocol_version: "0.4"` exactly as written. Don't bump it.
Commit: `chore(autoresearch): materialize config from bootstrap answers`.

**6. Freeze data splits.**
Per `PROTOCOL.md` §6.3.1, the host must declare its train/val/test split with
content hashes pinned in `data/splits/MANIFEST.json`. Ask the human for the
paths to each split file; compute SHA-256 of each; write the manifest.
Add `data/splits/**` to `<host>/autoresearch/config/protected_paths.yaml`
if it isn't already (the template default includes it).
Commit: `chore(autoresearch): freeze data splits per §6.3.1`.

**7. Seed behavioral-equivalence fixtures.**
Per `PROTOCOL.md` §17.1.1, the loop relies on a small set of golden inputs
to detect silent evaluator drift. Ask the human for 3–5 representative
inputs to the host's evaluation function (one or two is enough to start —
the human can add more after the first campaign). Write them to
`<host>/autoresearch/state/be_fixtures.json`. The schema is documented in
`template/scripts/behavioral_equivalence.py --help`.
Run `python autoresearch/scripts/behavioral_equivalence.py --record` once
to record golden outputs. Commit:
`chore(autoresearch): seed behavioral-equivalence fixtures`.

**8. Hand off to the human.**
Print a summary:
  - Files created.
  - Configs materialized.
  - Maturity level the host is starting at (almost always Level 1).
  - Highest label achievable at this level (`level1_branch_winner`, per §13.3).
  - What the human needs to do before the first proposal (review the
    materialized configs; satisfy themselves about the choice of enforcement
    mechanism).
Open the PR for review. Exit.

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
- `data/splits/MANIFEST.json` with SHA-256 content hashes.
- `autoresearch/state/be_fixtures.json` with at least one fixture entry
  and golden outputs recorded.
- A clean commit history on the integration branch with one commit per
  workflow step.
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
