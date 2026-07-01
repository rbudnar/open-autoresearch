# ADR 0006 - Coordinator/executor boundary

- Status: Accepted
- Date: 2026-07-01
- Deciders: @rbudnar
- Related: GitHub issue #20, GitHub issue #16, GitHub issue #18, GitHub issue #19, `PROTOCOL.md` Section 5.8 / Section 21.2

## Context

Open-AutoResearch already defines Research Director and Implementation Worker
roles, but their execution boundary was mostly prose. Arbor/HTR adds useful
design pressure: a coordinator chooses one hypothesis and an executor works in
one isolated workspace, returns evidence, and exits.

This repository is not a runnable agent framework. The contract needs to help
adopting agents implement Open-AutoResearch without forcing a scheduler,
orchestrator, Python runner, tmux setup, or specific vendor runtime into host
repositories.

## Decision

1. Add `PROTOCOL.md` Section 5.8 for a coordinator/executor handoff contract.
2. Define the Research Director as coordinator for branch selection, hypothesis
   freeze, budget/path/evaluator constraints, and post-evidence decisions.
3. Define the Implementation Worker as executor for exactly one approved
   hypothesis, with no authority to re-plan, promote, prune, merge, or retire
   branches.
4. Document minimal handoff and return payloads as YAML-shaped protocol
   artifacts, not as a required file format or runtime API.
5. Mirror the handoff payload in `proposal_template.md` and the return payload
   in `result_report_template.md`.
6. Clarify executor result labels for `invalid`, `infra_failed`,
   `budget_truncated`, `failed`, and `informative_failure`.
7. Permit single-session and Level-1 adopters to use the same contract with
   `coordinator_executor_separation: level_0`; degraded separation is labeled,
   not forbidden.

## Alternatives considered

- **Build a scheduler/orchestrator.** Rejected because Open-AutoResearch is a
  protocol and reference scaffold, not a default runtime.
- **Add a Python executor runner.** Rejected because it would turn the reference
  scripts into host machinery and weaken the language-neutral contract.
- **Require separate agents for every campaign.** Rejected because Level-1 and
  Level-2 adoption must remain possible in one session when evidence is labeled
  honestly.
- **Leave the boundary as role prose.** Rejected because it allowed quiet scope
  broadening, hypothesis changes, and self-promotion by the implementer role.

## Consequences

- Positive: Host agents get a concrete handoff shape without inheriting a
  runtime dependency.
- Positive: Reviewers can see whether a result came from the approved proposal
  or from an executor that silently changed the task.
- Positive: Non-Python hosts can implement the contract by producing equivalent
  artifacts and ledger-ready fields.
- Negative: The protocol still relies on host machinery to create isolation and
  enforce protected paths.
- Migration: None. Existing Protocol 0.5 artifacts remain valid.
