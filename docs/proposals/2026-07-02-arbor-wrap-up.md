# Proposal: Arbor wrap-up scope and interoperability map

Status: DRAFT / planning artifact. Author: rbudnar + agent. Date: 2026-07-02.
Related: #16, #24, #25, #4. Sources checked:
`karpathy/autoresearch@228791fb499afffb54b46200aca536f79142f117` and
`RUC-NLPIR/Arbor@4f8c5c2e8d4b8d238ae911da486240e1ba95f4ca`.

This note closes the native Arbor/HTR roadmap loop without making Arbor a
runtime dependency. Open-AutoResearch has already absorbed the durable protocol
pieces it needs: operational tree state, branch insights, coordinator/executor
handoff, and cost-aware frontier allocation. The remaining questions are:

- whether Karpathy's `autoresearch` is the right first real benchmark candidate;
- whether Arbor artifacts can be mapped into Open-AutoResearch artifacts without
  trusting runtime self-attestation.

## 1. Current roadmap state

The native protocol work under #16 is complete through Phase 2:

- #17 grounded Arbor/HTR in the maintained reference register and related-work
  narrative.
- #18 added lifecycle and frontier state to the derived research tree.
- #19 added propagated branch insights.
- #20 added a coordinator/executor handoff contract.
- #21 added cost-aware frontier allocation for Level 3+ campaigns.

Issue #22 was implemented by PR #27: the repo now has root agent instructions,
the docs router, dogfooding guidance, runtime-safety guidance, a quality gate,
harness metrics, weekly reporting, and CODEOWNERS/protected-path checks. It
should be closed as completed by PR #27 rather than reimplemented here.

Issue #23 remains intentionally deferred. It depends on the live HEB benchmark
roadmap and should not be folded into this wrap-up.

## 2. Benchmark-candidate decision for #24

### Recommendation

Use Karpathy's `autoresearch` as the first serious candidate for #4, but only as
a scoped, platform-pinned campaign. It is a good lineage fit and has a clean
single-file candidate surface, but it is not a portable public benchmark in the
leaderboard sense. If no stable NVIDIA GPU budget is available, pause before
running and choose a cheaper CPU benchmark instead.

### Exact candidate

- Repository: `https://github.com/karpathy/autoresearch`
- Baseline commit checked here:
  `228791fb499afffb54b46200aca536f79142f117`
- Default branch: `master`
- Candidate editable path: `train.py`
- Human/agent instruction path: `program.md`
- Protected evaluator/data/runtime paths: `prepare.py`, `pyproject.toml`,
  `uv.lock`, `.python-version`, and downloaded data/tokenizer cache.
- Primary metric: `val_bpb` from `prepare.py` evaluation; lower is better.
- Secondary telemetry: `training_seconds`, `total_seconds`, `peak_vram_mb`,
  `mfu_percent`, `total_tokens_M`, `num_steps`, `num_params_M`, crash rate, and
  diff complexity.

The upstream task's useful property is its locked editable surface: agents edit
`train.py`, while `prepare.py` owns data prep, constants, dataloading, and
evaluation. That maps naturally to Open-AutoResearch protected paths.

### Minimum Open-AutoResearch campaign shape

Level 1 pilot:

1. Clone the target repo at the pinned commit into a clean host worktree.
2. Run `uv sync` and `uv run prepare.py` once.
3. Record baseline `uv run train.py` output as the root ledger record.
4. Run 3-5 candidate iterations that only modify `train.py`.
5. Record every kept, discarded, and crashed attempt as immutable ledger records
   with source branch, source commit, lifecycle state, and local lessons.
6. Commit only Open-AutoResearch artifacts under a new example directory such as
   `examples/real-benchmark-karpathy-autoresearch/`; do not commit datasets,
   checkpoints, local caches, or transient `results.tsv`.

Level 3 graduation:

1. Freeze the host commit, GPU type, driver/runtime notes, seed policy, and
   validation-exposure budget before experimentation.
2. Use coordinator/executor handoffs for one-hypothesis worktrees.
3. Reserve budget for ablations, reruns, and verifier attempts before exploring
   new frontier nodes.
4. Require Skeptic review before any `branch_winner` or promotion-candidate
   claim.
5. Treat the final result as platform-specific unless rerun on another fixed
   platform.

### Guardrails

- Protected path check: candidate diffs must not modify `prepare.py`,
  dependency files, data files, or evaluation parsing.
- Metric direction check: `val_bpb` is minimize; confidence and comparison
  logic must use the minimize path.
- Budget check: a five-minute training loop can still be expensive over many
  iterations. Record compute budget and stop conditions before the run.
- Simplicity check: keep upstream's complexity posture. A tiny `val_bpb` gain
  from a large brittle diff is not automatically worth keeping.
- Artifact-size check: the example should preserve reports and ledger records,
  not model artifacts or cached datasets.

### Fit against other #4 benchmark ideas

| Candidate | Strength | Weakness | Decision |
|---|---|---|---|
| Karpathy `autoresearch` | Closest lineage fit; one editable file; fixed metric; tree-search-friendly. | Requires NVIDIA GPU; results are platform-specific; not a broad benchmark. | Recommended first if hardware/budget exists. |
| GLUE-MNLI small model | Public and recognizable; CPU/GPU options exist. | More setup and artifact weight; less directly tied to autonomous code-edit loops. | Good fallback if portability matters more than lineage. |
| Tiny WMT / translation task | Clear metric and literature context. | Heavier data and evaluation machinery; more room for evaluator drift. | Later candidate, not first. |
| ImageNet-100 style task | Familiar metric and visual-model coverage. | Dataset handling and compute cost are larger than this repo needs now. | Defer. |
| Synthetic examples already in repo | Cheap and deterministic. | Already covered; does not prove real campaign ergonomics. | Keep as regression fixtures only. |

### Decision for #4

Do not merge a full real-benchmark campaign in this wrap-up PR. Instead, treat
Karpathy `autoresearch` as the preferred first candidate and create the real
example only after the hardware, budget, protected-path enforcement, and artifact
retention choices are fixed up front.

## 3. Arbor interoperability map for #25

### Product decision

Build no adapter now. The right artifact today is this mapping note plus the
native Open-AutoResearch protocol surfaces already merged under #18-#21.

A future adapter is only worth opening if a real campaign produces concrete
Arbor artifacts that need import/export. That follow-up should be narrow:
transform a static Arbor session export into Open-AutoResearch proposals,
reports, ledger records, and promotion requests. It should not make Arbor the
default runtime and should not replace verifier-signed promotion packets.

### Concept mapping

| Arbor concept | Open-AutoResearch concept | Mapping posture |
|---|---|---|
| Idea Tree / hypothesis node | Ledger record plus derived `research_tree.json` node | Good conceptual fit. Open-AutoResearch keeps immutable records as source of truth and derives the tree. |
| Coordinator | Research Director | Good fit when the coordinator records frontier choice, budget reserve, and handoff payload. |
| Executor | Implementation Worker | Good fit when each executor has one hypothesis, a scoped worktree, and a recorded separation level. |
| Dev evaluation | Stage-B/proxy evaluator or in-band validation signal | Useful for exploration only. It is not a promotion gate by itself. |
| Held-out merge decision | `branch_winner` or promotion-candidate decision | Partial fit. Open-AutoResearch still needs evidence labels, exposure accounting, and verifier checks. |
| Backpropagated insight | `branch_insights[]` with review status and source records | Good fit when insight provenance resolves to immutable ledger records. |
| Isolated worktree | Per-iteration candidate worktree | Good fit. Protected-path enforcement remains outside the agent when available. |
| Arbor report/session export | Proposal, result report, ledger records, promotion request | Possible adapter target, but only after the exported fields are inspected from a real run. |
| Literature/novelty check | Optional literature metadata and maintained reference discipline | Partial fit. Search output is design context, not proof of novelty or protocol validity. |

### Non-mapping gaps

- Arbor is a runtime. Open-AutoResearch is a protocol and trust contract.
- Arbor can decide that a change survived its held-out evaluation, but that is
  not the same as an Open-AutoResearch `promoted` label.
- Arbor outputs should be treated as in-band agent/runtime claims until converted
  into immutable records and checked by non-agent enforcement.
- Open-AutoResearch's verifier-signed promotion packet has no direct Arbor
  equivalent.
- Protected-path enforcement is the responsibility of the host repo, CI, or
  verifier boundary. Running Arbor does not make evaluator protection out of
  band.
- Open-AutoResearch should not import Arbor's full orchestration layer just to
  preserve the vocabulary alignment.

### Minimal future adapter contract

If #24 or a later campaign shows a real need, open a follow-up issue for a
read-only importer with this contract:

1. Input: a pinned Arbor session export or report directory.
2. Output: Open-AutoResearch proposal files, result reports, ledger records, and
   optional promotion requests.
3. Required checks: source record ids resolve, protected-path policy is recorded,
   metric direction is explicit, validation exposure is accounted for, and any
   branch insights carry source ids plus review status.
4. Non-goals: running Arbor, installing Arbor, replacing Open-AutoResearch's
   verifier, or adding Arbor as a default runtime.

## 4. Closeout recommendation

- Close #24 with this scoping artifact and link it from #4.
- Close #25 with this interoperability map.
- Close #22 separately with a comment pointing to PR #27.
- Leave #23 open and deferred until the HEB benchmark prerequisites exist.
- Leave #16 open only if it remains the umbrella for #23 and future real-campaign
  work; otherwise close it after the issue links above are updated.

This keeps the Arbor integration honest: native protocol semantics are complete,
runtime interoperability is documented but not overbuilt, and the first real
campaign has a concrete candidate without pretending the campaign has already
run.
