# Maintained References

This register is the maintainer-facing bibliography for Open-AutoResearch's
foundations. Use it to understand where the protocol's design pressures came
from, what evidence level each source carries, and which claims should stay
modest until the literature changes.

`PROTOCOL.md` §2 is the adopter-facing citation snapshot. Keep this register,
`PROTOCOL.md` §2, and `docs/related-work.md` in sync whenever a foundational
source is added, removed, reclassified, or materially reinterpreted.

## Maintenance Policy

- Review this file during the quarterly citation re-review tracked by issue #7.
- Prefer primary sources: papers, official repositories, conference pages, and
  journal pages.
- Record the current evidence status and date checked for every source that
  influences protocol semantics.
- Treat unreviewed preprints and prototypes as design influences only.
- Do not claim that Open-AutoResearch is empirically validated by a source
  unless the source actually tests this protocol or an equivalent protocol.
- When a preprint changes status, update this file, `PROTOCOL.md` §2, and
  `docs/related-work.md` in the same PR.

## Evidence Status Vocabulary

| Status | Meaning | Protocol posture |
|---|---|---|
| Peer-reviewed | Accepted by a journal, conference, or workshop process. | Can support specific adopted patterns, within the paper's actual scope. |
| Technical report | Public report from authors or a lab without normal peer review. | Design influence; do not treat as independent validation. |
| Unreviewed preprint | arXiv or equivalent preprint without peer review. | Design influence only; mark claims as provisional. |
| Prototype | Public implementation without a reviewed paper. | Implementation precedent or baseline pattern only. |
| Withdrawn | Removed or withdrawn by the venue or authors. | Traceability only; empirical claims are not relied on. |

## Foundational Sources

| Source | Primary reference | Current status | Date checked | Used for |
|---|---|---|---|---|
| Karpathy `autoresearch` | https://github.com/karpathy/autoresearch | Prototype | 2026-05-18 | Tight loop baseline, locked-judge framing, constrained editable surface. |
| AutoResearch-RL | https://arxiv.org/abs/2603.07300 | Withdrawn | 2026-05-18 | Loop-as-RL framing as idea source only. |
| Hyperagents / DGM-H | https://arxiv.org/abs/2603.19461 | Unreviewed preprint | 2026-05-18 | Variant archives, self-improvement framing, cross-iteration lessons. |
| MARS | https://arxiv.org/abs/2602.02660 | Unreviewed preprint | 2026-05-18 | Budget-aware tree search, reflective memory, sibling comparisons. |
| AlphaLab | https://arxiv.org/abs/2604.08590 | Unreviewed preprint | 2026-05-18 | Strategist/Worker split, persistent playbook, literature-grounded search. |
| Deep Researcher Agent | https://arxiv.org/abs/2604.05854 | Unreviewed preprint | 2026-05-18 | Leader/worker split, bounded memory, multi-day operation. |
| ResearchGym | https://arxiv.org/abs/2602.15112 | Peer-reviewed | 2026-05-18 | Workshop-reviewed source for long-horizon agent failure modes and reliability gaps. |
| MLGym | https://openreview.net/forum?id=ryTr83DxRq | Peer-reviewed | 2026-05-18 | Conference-reviewed source for long-horizon ML-agent failure modes, budget/time/confidence management. |
| AI Scientist v2 | https://arxiv.org/abs/2504.08066 | Technical report | 2026-05-18 | Tree budget allocation, experiment-manager role, ablation requirement. |
| AI Scientist (Nature) | https://www.nature.com/articles/s41586-026-10265-5 | Peer-reviewed | 2026-05-18 | Journal-reviewed source for end-to-end automated research framing. |
| Arbor / Hypothesis-Tree Refinement | https://arxiv.org/abs/2606.11926 and https://github.com/RUC-NLPIR/Arbor | Unreviewed preprint | 2026-06-27 | Hypothesis-tree refinement, coordinator/executor split, isolated worktrees, insight propagation, and implementation precedent. |

## Maintainer Checklist

Before merging a citation or related-work update:

- The source appears here with status, date checked, and a concrete "used for"
  claim.
- `PROTOCOL.md` §2 carries the adopter-facing status snapshot.
- `docs/related-work.md` explains the contrast without overstating evidence.
- Any template or proposal fields added for literature grounding remain
  optional unless a protocol version bump deliberately makes them required.
- Issue #7 or its successor covers the next scheduled re-review.
