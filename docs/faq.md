# FAQ

## Why no working agent in the repo?

The protocol is provider-agnostic. Any capable coding/research agent — Claude Code, Codex, Gemini, OpenAI agents, Aider, Goose — can read `PROTOCOL.md` and implement the loop. Shipping a reference loop in one language would create a default the protocol does not have.

The reference scripts in `template/scripts/` are **non-agent infrastructure** — the behavioral-equivalence test and the verifier. Those are deliberate exceptions: they're things that run outside the agent's edit surface and benefit from a canonical implementation.

## Why is the protocol so long?

1700+ lines is more than a typical README, less than a typical RFC. Most of the length is examples, schemas, and explicit failure-mode coverage. We resisted the temptation to write a "Quick Reference" that omits the operational sections — most of the protocol's value is in the parts new adopters skip.

Read `§1.5` first; it tells you which sections you actually need at Level 1.

## Why are most cited papers preprints?

The 2026 research wave on autonomous ML research happened fast; most of it isn't peer-reviewed yet. We honestly tag each citation's review status in `§2`. The protocol does NOT claim its design is validated by these papers — it's *inspired* by them. The protocol's empirical claims live in `examples/level3-counter-example/` and in future benchmark work.

## What happens if my host project doesn't have CI?

You can run at Level 1 or Level 2 with `enforcement.yaml: mechanism: none`. Every result will be labeled `enforcement: in_band_only` and `not_deployable: true`. This is honest and useful for exploration. It is NOT useful as a basis for production deployment.

For production work, set up at least basic CI: GitHub branch protection + CODEOWNERS on the protected paths is enough for `ci_enforced`.

## The Skeptic role seems expensive — can I skip it?

At Level 1 and Level 2: yes, it's not required.

At Level 3+: no, the verifier rejects packets without a Skeptic review at the required separation level. The Skeptic is the protocol's main intra-iteration defense against stack proposals and metric-gaming attempts.

If LLM cost is the concern: the Skeptic's role is mostly a checklist (see `template/templates/skeptic_review_template.md`). The "Specific concerns surfaced" section is the freeform part; the rest is structured. A short LLM session is enough.

## My val-exposure budget keeps exhausting too fast. What now?

Either:
1. Run a holdout refresh (§17.6.3) — costs human review per §3.1, but resets the counter to 0.
2. Increase `val_set_exposure_budget` on the next campaign. The defaults (100 / 300 / 1000) are starting points; scale with √(val_size) or set empirically.
3. Reduce val usage: ensure Stage B uses a separate proxy slice (not val); avoid early-stop-on-val if you can use a separate dev slice.
4. Cut the campaign short with a counter-example report (§22a) and start fresh.

The counter-example arc in `examples/level3-counter-example/` shows exhaustion happening for legitimate reasons (factorial + re-grade) and the protocol blocking the resulting promotion. Treat that as the intended behavior, not a bug.

## Can I use this with a closed-source model?

Yes. The protocol doesn't care which model your agent uses. It cares which separation level you achieve (§5.0) and whether your evaluator is locked (§3.1.1). A closed-source agent that follows the protocol produces the same artifacts as an open-source one.

## Can I extend the run categories in §13.3?

You can add categories for your project, but the verifier (`template/scripts/verifier/verify_request.py`) only signs packets for the protocol-defined `promoted` / `low_evidence_promoted` / `rejected`. Custom categories live alongside, not instead of.

## What's the difference between `level1_branch_winner` and `branch_winner`?

The `level1_` / `level2_` prefixes mean: this result was produced at Level 1 (or 2) discipline — no ablation, no Skeptic at separation level 2, no verifier signature. The unprefixed `branch_winner` (Level 3+) means all of those things WERE done; the candidate just hasn't met every §18 criterion for full `promoted` (often because of cost — running 5 promotion seeds when you only have 3 candidate seeds).

External readers should treat prefixed labels as "interesting signal, needs Level-3 follow-up" and unprefixed `branch_winner` as "real candidate awaiting the verifier."

## Why HMAC for the promotion-packet signature?

It's symmetric, simple, and adequate when the verifier and the consumer of the packet are the same trust domain. A real production deployment may want public-key signatures (Ed25519 etc.) so packets can travel between domains. Ports of `sign_packet.py` are welcome (see `CONTRIBUTING.md`).

## What if the protocol itself is wrong?

The protocol is `v0.4`, marked pre-1.0, with explicit breaking-change provisions. If you find a real protocol-level flaw, open a Protocol RFC per `CONTRIBUTING.md`. We aim for the v1.0 release after at least three independent host projects have completed end-to-end campaigns.

## Why no tests for the reference scripts?

The scripts are short enough to verify by inspection, and they're not load-bearing on the protocol's correctness (the protocol is). Adding a test suite is a reasonable v1.1 contribution; the absence is acknowledged.

## How do I know if my campaign is "real"?

It produces at least one promotion packet (`status: promoted` or `low_evidence_promoted`) signed by a non-agent verifier, OR it produces a counter-example report (`§22a`) with durable negative lessons. Anything else is a draft, not a campaign.
