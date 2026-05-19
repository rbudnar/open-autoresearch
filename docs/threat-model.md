# Threat model

What this protocol enforces, what it does NOT enforce, and the honest path between them.

## TL;DR

The protocol's anti-reward-hacking story works **only when out-of-band enforcement is configured** (§3.1.1). In-band controls — i.e., rules the agent reads and is supposed to follow — are advisory. The protocol is structured to make this honest: every artifact carries a label (`enforcement: ci_enforced | in_band_only`) and a `not_deployable` boolean that propagates downstream.

If you read only one section of this doc, read this one. Then decide whether your adoption is mechanically enforced or honor-system. Either is fine; mislabeling them is not.

## What the protocol enforces (with §3.1.1 active)

| Threat | Defense | Section |
|---|---|---|
| Agent edits evaluator code to inflate metrics | CI rejects PRs that touch `protected_paths`; CODEOWNERS requires non-agent review | §3.1.1, §3.1 |
| Agent edits data splits to add held-out examples to training | `data/splits/MANIFEST.json` content-hashed; protected; behavioral_equivalence catches the drift | §6.3.1, §17.1.1 |
| Agent silently changes metric computation while keeping the test green | §17.1.1 tolerance-based golden fixtures catch numerical drift; human review for legitimate refactors | §17.1.1 |
| Agent self-attests a promotion | Verifier (`§10.5`) is a separate non-agent process with a signing key the agent cannot read; emits `promotion_packet.json` with HMAC | §10.5 |
| Agent runs the same val-set comparison 200 times until something "wins" by chance | `val_set_exposure_budget` counter increments on every val read; verifier rejects promotion when budget is exhausted | §17.6 |
| Agent stacks 3 changes into one candidate, claims attribution to whichever change is easy to defend | §11.1.1 forbids stacks; Skeptic role catches; verifier enforces `factorial_grid_completed` for stacks | §11.1.1, §16.1.2 |
| Agent's "Skeptic" is the same model in the same session as the Worker | §5.0 separation levels; verifier rejects promotion when `implementation_worker_vs_skeptic < level_2` | §5.0 |

## What the protocol does NOT enforce

| Threat | Why | What helps anyway |
|---|---|---|
| Agent picks `enforcement.yaml mechanism: none` on bootstrap | Self-attestation is unavoidable when no out-of-band machinery exists. The label namespace (`enforcement: in_band_only`, `not_deployable: true`) makes this VISIBLE; it doesn't prevent it. | Document team policy: production deployments require `enforcement: ci_enforced` or higher. CI gates on this label. |
| Agent picks a weak enforcement mechanism (e.g., a `oop_verifier` script that runs only when the agent invokes it) | The mechanism choice itself is in-band. | Treat the mechanism choice as a deploy-time policy, not a per-campaign choice. Pre-commit it to the host project. |
| Agent's literature brief cites a fabricated paper | §17.3 anti-hallucination controls are advisory. The verifier doesn't check citations against arXiv. | Spot-check briefs in PR review. The protocol's `review_status` field at least makes fabrication detectable. |
| Agent gameable proxy metrics (improves primary by exploiting a degenerate solution) | The protocol cannot tell you what your metrics measure. It enforces multi-objective scoring + guardrails, not metric quality. | This is a metrics-design problem. Add subgroup checks; add guardrails for failure modes you suspect; run §22a counter-example reviews periodically. |
| Agent decides to skip ablation by claiming it ran one | The verifier checks the request's claim against ledger entry IDs. If the agent claims an ablation that doesn't exist, the verifier catches via hash mismatch. But if the agent runs a sham ablation and writes a sham ledger entry, the verifier sees a consistent (sham) story. | Skeptic review reads the ablation report and looks for the documented mechanism. This is the weakest link in the chain. |
| Subtle reward hacking via inputs the evaluator doesn't see (e.g., the model learns to detect "I'm being evaluated" from input distribution) | The evaluator is locked; the model is not. | Hold-out distribution checks; periodic adversarial-input tests; the §22a counter-example campaigns surface this if the eventual deployment behavior diverges. |

## Out-of-band enforcement mechanisms, ranked by trust

Per `PROTOCOL.md` §3.1.1:

| Mechanism | Trust level | When to use |
|---|---|---|
| `ci_enforced` (branch protection + CODEOWNERS) | High, if the agent has no admin token | Default for any team with a GitHub repo. Most accessible. |
| `pre_receive` (server-side git hook) | High, if the agent has push but not shell access | Self-hosted Git. More work to set up; very strong. |
| `oop_verifier` (out-of-process script run by human/CI) | Medium | Useful as a backstop when CI is unavailable. Requires discipline. |
| `container_ro` (read-only bind mount) | High, if image pipeline is itself protected | Strong for containerized workloads. Image build pipeline becomes the new protected surface. |
| `none` | Advisory only | Honest acknowledgment for solo Level-1 exploration. Cap results at `level1_branch_winner`. |

## What this protocol explicitly does not address

- **Model alignment risks** beyond reward hacking. The protocol is about research-loop discipline, not about the model's downstream values.
- **Capability uplift risks** from agent-driven research. If your campaign produces a model dramatically more capable than its training data implies, that's a separate governance question. Out of scope.
- **Supply-chain attacks on `template/scripts/`.** Treat reference scripts as you treat any third-party dependency: pin versions, audit before adopting. CODEOWNERS protects the open-autoresearch repo's copy; what you do with the local copy is on you.
- **Resource exhaustion attacks** (agent intentionally runs the budget dry). §17.7 budget enforcement helps but is in-band; an adversarial agent with permission to write the budget ledger can cheat it. Out-of-band budget tracking (cloud billing console, GPU scheduler logs) is the real backstop.

## How adopters should communicate the trust level

Every output artifact carries enough metadata to communicate trust:

```yaml
maturity_level: <1-5>           # what level of discipline was applied
enforcement: <ci_enforced | ... | in_band_only>   # whether the lock is real
not_deployable: <true | false>  # short-form deployability flag
status: <promoted | level1_branch_winner | rejected | ...>  # protocol-blessed label
```

Dashboards, reports, and downstream consumers should display all four. If you see a "win" without these fields, treat it as untrusted.

## Reporting issues

If you find a way to defeat the protocol's enforcement (in-band or out-of-band), please open a security advisory via GitHub rather than a public issue. See `SECURITY.md` (not yet written — file an issue if you need it).
