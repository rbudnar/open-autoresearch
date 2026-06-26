# open-autoresearch

A disciplined protocol for autonomous ML model improvement, plus the scaffolding to drop it into your project.

> **AI agent reading this?** Start with [`AGENTS.md`](./AGENTS.md). It speaks to you directly and tells you exactly what to do, in what order, with which questions to ask the human.

**Centerpiece:** [`PROTOCOL.md`](./PROTOCOL.md) — AutoResearch++ v0.5, a 1700-line specification for autonomous research loops with honest separation between in-band-advisory and out-of-band-enforced controls.

**Protocol version shipped:** `0.5` (final pre-1.0 candidate).

---

## What this is

A bootstrapping template that any AI coding/research agent — Claude Code, Codex, Gemini, OpenAI agents, etc. — can clone to instantiate a literature-grounded autonomous research loop on a host ML project.

**This repo is not a Python framework.** It is a protocol document plus copyable scaffolding (markdown templates, config examples, JSON schemas implicit in the protocol, a Python reference verifier). The agent that adopts this protocol writes its own experimentation loop against the contracts described in `PROTOCOL.md`. The repo provides:

- The protocol document itself (the rulebook).
- `template/autoresearch/` — directory layout the agent stamps into the host project.
- `template/scripts/` — minimal Python reference scripts (behavioral-equivalence test, promotion verifier).
- `examples/` — two completed example campaigns (Level-1 success arc + Level-3 counter-example arc).
- `docs/` — adoption guide, threat model, related-work positioning.

## What this is not

- Not a working autoresearch agent. The agent is your responsibility; the protocol is ours.
- Not a Python library you `pip install`. The reference scripts are templates.
- Not a guarantee that your agent can't cheat. See [`docs/threat-model.md`](./docs/threat-model.md) for an honest enumeration of what the protocol enforces and what it does not.

## 30-second quickstart for adopters

1. Read [`PROTOCOL.md` §1.5 "Start Here"](./PROTOCOL.md) (about 10 minutes).
2. Copy `template/` into your host project as `autoresearch/`.
3. Pick an enforcement mechanism in `autoresearch/config/enforcement.yaml.example` and rename to `enforcement.yaml`. If you have no CI / no out-of-band machinery, set `mechanism: none` and accept that your campaign results will carry `enforcement: in-band-only` and `not_deployable: true`.
4. Fill in `autoresearch/config/metrics.yaml.example` — cost tier, primary metric (with direction, aggregation, eval_dtype), guardrails, exposure budget, LLM/compute budgets. Rename to `metrics.yaml`.
5. Freeze your splits (`§6.3.1` — write `data/splits/MANIFEST.json` with content hashes; protect the path).
6. Write 3-5 golden fixtures for `behavioral_equivalence.py`.
7. Run your first proposal under the Level-1 path. Highest available label at Level 1 is `level1_branch_winner`. Graduate to Level 3 (ablation + Skeptic + non-agent verifier) before attempting `promoted`.

## Reading order

| Audience | Read |
|---|---|
| First-time adopter | `PROTOCOL.md` §1.5 → `examples/level1-success/` → `docs/adoption-levels.md` |
| Reviewer assessing whether to adopt | `docs/threat-model.md` → `docs/related-work.md` → `PROTOCOL.md` §3 + §17 + §18 |
| Maintainer or contributor | `CONTRIBUTING.md` → `PROTOCOL.md` §0 (versioning policy) |
| Curious about failure modes | `examples/level3-counter-example/` → `PROTOCOL.md` §22a |

Repo maintainers should use [`docs/README.md`](./docs/README.md) as the docs
router and run `python scripts/quality_gate.py` before closing harness,
template, example, verifier, or workflow changes.

## Why this exists

Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) demonstrated the value of a tight autonomous loop. The 2026 literature (TREX, AlphaLab, MARS, AI Scientist v2, etc.) added tree search, durable memory, role specialization, and explicit ablation discipline. This protocol synthesizes those ideas with an opinionated stance on what's enforceable vs. honor-system.

The single largest distinction from prior art: this protocol **does not promise** to prevent reward-hacking by an agent that controls bootstrap. It is structured to make cheating **detectable** through external verification, namespaced labels, behavioral-equivalence tripwires, and explicit `not_deployable` markers when out-of-band enforcement is absent. The README, threat model, and label vocabulary all say this out loud.

## Status

`v0.5` is the final pre-1.0 protocol candidate. v1.0 will be tagged after at least three independent host projects have completed end-to-end campaigns and reported results.

The repo is dogfooded — `PROTOCOL.md`, the example artifacts, and the reference scripts are protected by `CODEOWNERS` and CI per `§3.1.1` of the protocol. See [`docs/threat-model.md`](./docs/threat-model.md).

## License

MIT. See [`LICENSE`](./LICENSE).
