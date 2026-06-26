---
protocol_version: "0.5"
proposal_id: "20260518-170000-bbb006-stack-rejected"
branch: "architecture+loss_objective"
parent_proposal_id: "20260518-160000-bbb005-regrade"
literature_brief: null
web_search_used: false
maturity_level: 3
---

# Experiment Proposal (REJECTED BY SKEPTIC): Attention pool + ordinal hybrid combined

## Hypothesis

Because attention pool gave -0.022 NLL (iter-5) and ordinal hybrid gave -0.009 NLL (carried-forward from earlier campaign), combining them should produce additive gains around -0.030.

## Proposed change

```yaml
config:
  encoder_type: attention_pool       # non-baseline #1
  loss_type: ordinal_ce_hybrid       # non-baseline #2  ← stack
```

## What the Skeptic caught

**Per §11.1.1, this is a STACK, not a candidate.** A candidate flips exactly one non-baseline switch. A stack flips two or more. Stacks require factorial ablation per §16.1.2 before they can be promoted, NOT a single ablation per §16.1.1.

The Skeptic returned this proposal to the Research Director with the note:

> "Two non-baseline switches in a single candidate (`encoder_type` and `loss_type`). Per §11.1.1 this is a stack. Either:
>
> (a) Decompose into two candidates (already done: attention_pool in iter-3/5, ordinal_hybrid in iter-2 of a prior campaign — those candidates already exist), then propose a factorial ablation (§16.1.2) to attribute the combined effect, OR
>
> (b) Reframe as a single conceptual change that justifies the combined edit (e.g., a published method that pairs an attention encoder with an ordinal loss as a coupled mechanism). I do not see such a mechanism in your literature brief.
>
> (a) is the right path. Plan a 2×2 factorial: ~12 runs at the current cost tier. This will cost ~36 GPU-hours."

## Outcome

**Status:** `informative_failure`. No experiment was run. Zero val queries incurred. The protocol's §11.1.1 enforcement prevented a stack from contaminating ablation discipline.

**Lessons:**
- The agent's instinct to stack improvements is the most common protocol violation. The Skeptic role exists precisely to catch this.
- The lesson is real, not pedantic: if the combined run had shown a -0.03 improvement, we could not have attributed it to either change alone without the factorial. The protocol forces the factorial up front.

**Next step:** Plan the factorial as iter-7 (see `reports/iter07-factorial-ablation.md`).
