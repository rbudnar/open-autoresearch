# Related work

Where AutoResearch++ sits in the 2026 landscape, and what it deliberately is and is not.

## Lineage

The protocol's `§2` citation status table is the authoritative reference; this doc is the longer narrative.

### Karpathy's `autoresearch` (2026, GitHub prototype)

The point of departure. Karpathy's prototype showed that a tight autonomous loop — edit one file, fixed budget, single-metric keep/revert — is a viable starting point. The biggest contribution was demonstration: "this works at all."

**What we keep:** the tight feedback loop, the constrained editable surface, the locked-judge framing.

**What we changed:** added literature search, multi-objective scoring, ablation discipline, tree search over branches, role separation, out-of-band enforcement, validation-exposure accounting, budget accounting. Most of these are downstream of "what happens when this runs for days instead of minutes?"

### 2026 research wave — TREX, MARS, AlphaLab, AI Scientist v2, AutoResearch-RL, Hyperagents

`PROTOCOL.md` §2 tags each citation's review status honestly. Most of these are concurrent preprints from 2026 Q1-Q2; one (AutoResearch-RL) was withdrawn by arXiv admin.

**What we absorbed from each:** the budget-aware tree search idea (MARS, AI Scientist v2), Strategist/Worker role split (AlphaLab), persistent playbook (AlphaLab), ablation-before-promotion (AI Scientist v2), variant archives + cross-iteration lessons (Hyperagents). The literature-grounded search pattern itself is absorbed from AlphaLab's domain-understanding phase.

**What we did not adopt:** the RL-based meta-policy framing of AutoResearch-RL — interesting structurally but the paper was withdrawn and the empirical claims unsupported, so it stays as an "idea source only" tag. The Strategist/Worker pair-programming pattern from AlphaLab was generalized into our 7-role split rather than adopted verbatim.

### Peer-reviewed: ResearchGym (ICLR 2026 workshop), MLGym (COLM 2025)

The only peer-reviewed evidence we lean on. Both document **long-horizon agent failure modes** — impatience, poor resource management, overconfidence, weak coordination, context-window overflow. The §17.4 long-horizon controls and §17.5 operational realities sections trace directly to these.

If we trust anything in this protocol on empirical grounds, it's the failure-mode taxonomy — these are the bits with peer review behind them.

### AI Scientist (Nature 2026)

The broader AI-Scientist line has a 2026 Nature paper. It frames the whole end-to-end research process — hypothesis → experiment → write-up — as automatable. We borrow narrower than the Nature paper: we focus on the experimentation loop and the promotion gate; we don't try to automate hypothesis generation or paper writing.

## What we are NOT

- **Not a research-paper-writing system.** AI Scientist v2 and the Nature line do this; we don't. We stop at "promoted model" — the human writes the paper.
- **Not an architecture-search system.** Our `architecture` branch is one of seven; tools like ENAS, DARTS, NAS-Bench are vastly more focused for architecture search alone. Use them under the protocol's umbrella if you want.
- **Not a hyperparameter-optimization framework.** Optuna, Ax, Sweeps from Weights & Biases are better for that. Wire them into the `optimization` branch.
- **Not an experiment-tracking platform.** MLflow, W&B, Neptune, Comet do this better than our `experiment_ledger.jsonl`. Our ledger is sufficient for the protocol's purposes; if you want richer tracking, treat the ledger as the source of truth and sync to your tracker.
- **Not a CI/CD system.** We define what CI must enforce (`§3.1.1`); we don't ship the CI itself. The repo's own `.github/workflows/` is illustrative.
- **Not a security framework.** See `docs/threat-model.md` — we are deliberately narrow about what we enforce.

## What we ARE

- **A disciplined research-loop spec** that any agent can follow, written to be implementable without a specific language or platform commitment.
- **A label vocabulary** (`level1_branch_winner`, `branch_winner`, `promoted`, etc.) that travels with artifacts and communicates evidence quality.
- **A separation-of-concerns artifact** (agent emits requests; non-agent verifier signs packets) that makes "self-attestation" structurally impossible if enforcement is configured.
- **A reusable failure-mode catalog** (§17 + §22a) so adopters don't have to discover every long-horizon failure firsthand.

## Differences from prior art (the differentiation argument)

The 2026 research wave converged on **tree search + durable memory + role specialization + multi-fidelity** as the four design upgrades. We took those as input — and added:

1. **Honest in-band-vs-out-of-band labeling.** Most prior systems claim to "lock" the evaluator; very few specify how, or admit when the lock is honor-system. The §3.1.1 honesty disclaimer is the protocol's most-distinguishing feature.
2. **Verifier-signed promotion packets.** The agent emits a *request*; a non-agent verifier emits the *packet*. Self-attestation is structurally blocked.
3. **Namespaced result labels.** `level1_branch_winner` is visibly different from `promoted` in dashboards, reports, and downstream consumers. Prior systems often have a single "winner" label that hides whether ablation was done.
4. **Direction-aware statistics.** Sounds obvious; missed often. §13.2.1 explicitly handles maximize and minimize with the correct CI bound. Several prior systems we surveyed had `lower_95_CI > threshold` rules that were wrong for minimize metrics.
5. **Operational realities section.** Nondeterministic GPU kernels, distributed training, dependency drift, ledger growth, multi-agent contention — these are protocol concerns, not orchestration concerns. §17.5 names them explicitly.
6. **Counter-example campaigns** as a first-class deliverable. §22a + the worked example in `examples/level3-counter-example/`.

## What we owe future versions

- A real, peer-reviewed benchmark of "protocol-following agent vs no-protocol agent" on a public task. Out of scope for v1.0; on the v1.1+ roadmap.
- A ports list (Go, Rust, Bash) for the reference scripts. Welcome via the CONTRIBUTING flow.
- Quarterly §2 citation review — preprints either get peer review or get demoted to "design influence only" in the table.

## When to look elsewhere

If your need is:

- **Quick demo of "AI doing ML"** — Karpathy's `autoresearch` is closer to what you want.
- **Production ML platform with all the trimmings** — use a real platform (W&B, MLflow + your CI), wire its outputs into this protocol's ledger format.
- **Architecture search at scale** — ENAS / NAS-Bench / DARTS first; treat this protocol as the wrapping discipline.
- **Multi-agent debate / scientist-style research synthesis** — the Nature AI Scientist line is further along on that axis.
- **Theoretical guarantees about agent behavior** — this protocol is engineering; it does not provide proofs.

Use this protocol when your problem is "I want autonomous research to run for days with rigor and honesty, on a real codebase, with the option of shipping the result." That's the problem this is shaped for.
