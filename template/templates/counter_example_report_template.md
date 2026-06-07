---
protocol_version: "0.5"
report_id: "<YYYYMMDD-HHMMSS-6hex-slug>"
campaign_id: "<id>"
iterations_covered:
  - "<id>"
maturity_level: <1 | 2 | 3 | 4 | 5>
campaign_outcome: "<no_trustworthy_improvement_found | reframed_problem | killed_branch | other>"
---

# Counter-Example Report

**What this is:** §22a in `PROTOCOL.md` allows — and `§19` explicitly accepts — campaign outcomes where the trustworthy answer is "no improvement found." This report exists because such outcomes carry the campaign's most durable lessons. Skipping the report turns negative results invisible; preserving it turns them into reusable knowledge.

## What we tried

(One paragraph summary of the campaign goal and approach.)

## What happened

(Iteration-by-iteration narrative. Tighter than the result reports — this is the meta-view. Each iteration:)

### Iteration <id>

- Branch: <branch>
- Candidate: <single non-baseline switch>
- Outcome label: <§13.3 category>
- Reason: <one sentence>

### Iteration <id>
- ...

## Why no candidate was promoted

(Specific to this campaign. Examples of legitimate reasons:)

- "Best candidate's NLL improvement reversed on seed rerun; iteration 5 was an outlier."
- "Two candidates passed primary; both failed Holm-corrected guardrails (latency, calibration)."
- "Behavioral-equivalence test failed on iteration 7 due to a refactor; iterations 5–7 invalidated."
- "Validation-set exposure budget reached without a candidate meeting §13.2.1; campaign halted pending holdout refresh."
- "All branches failed; cost-tier seed counts unable to distinguish noise from signal at this training budget."

## Lessons (durable, for playbook)

- <Lesson 1, branch-tagged>
- <Lesson 2, branch-tagged>

## "Do not retry without new evidence"

(Specific patterns this campaign ruled out. Future campaigns should reference this list before proposing similar candidates.)

- <pattern>: <why it failed; what new evidence would justify retrying>

## What would unlock progress

(Honest assessment. Examples:)

- "A larger training budget would let us run more seeds and resolve noise vs signal."
- "An additional held-out subgroup slice would catch the regression we suspect but couldn't statistically confirm."
- "A literature scout pass on <topic> might surface ideas this campaign didn't explore."
- "The evaluator itself may be the limit; consider §17.1.1 audit before more iterations."

## Open questions raised

(Questions for the playbook's `open_questions.md` — things this campaign couldn't answer.)

- <question 1>
- <question 2>
