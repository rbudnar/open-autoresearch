# Runtime Safety

Open-AutoResearch has no production runtime, but it does contain scripts,
workflows, package execution examples, generated artifacts, and verifier
surfaces. Treat those as execution surfaces.

## Safe Defaults

- Prefer read-only survey commands before writing harness files.
- Keep generated example aggregates ignored and regenerable.
- Use temp directories for verifier packets and other validation output.
- Inspect CI shell snippets before copying them into local shells, especially
  snippets with GitHub expressions or unresolved environment variables.
- Do not add network, package, or credential flows to the canonical quality gate
  unless the command is explicit, deterministic, and documented here.

## Package Execution

The HEB bootstrap package path used for this bootstrap was:

```bash
npm exec --yes --package "github:rbudnar/harness-engineering-bootstrap#main" -- harness-bootstrap init -- --repo <repo> --json
```

The stable `v0.1.0` tag was attempted first, but that tag does not contain
`package.json`, so npm cannot install it as a package. The direct checkout
fallback also ran:

```bash
node <heb-checkout>/scripts/harness-bootstrap-plan.mjs init --repo <repo> --json
```

## Risky Changes

Get explicit review before adding or changing:

- commands that deploy, publish, upload, delete, or mutate external state;
- package install or package execution steps in CI;
- verifier signing behavior or packet trust assumptions;
- git hooks, workflow permissions, or protected path policy;
- generated-file cleanup logic.

Rollback for this harness layer is a normal PR revert plus restoration of
`docs/harness-version.json` and the prior validation evidence.

## Agent Inbox Execution Boundary

This repository is public, so both Agent Inbox workflows use ephemeral
GitHub-hosted runners. Although `rbudnar-linux` is authorized to run inboxes,
a persistent self-hosted label in a public personal-account repository is not
an access-control boundary: an admitted fork workflow could target it. The
safer event-driven design intentionally does not register or require that host.

The checked-in review signal has empty permissions and one fixed no-op step. It
does not checkout code, call APIs, use secrets, or consume untrusted event text.
A fork may propose a different signal definition, but that code stays on an
ephemeral hosted runner with the fork's restricted token and no secrets; its
completed run can only request a fresh state read from the base-owned
publisher. The publisher starts with a read-only routing job, accepts only
canonical current workflow ID/name/path/event combinations, and treats upstream
runs solely as refresh requests. It never downloads producer artifacts, logs,
caches, or PR code. After per-PR concurrency admission it re-reads the current
PR and default branch, requires the default name and exact OID to equal the
route-time values, and checks out only that verified base OID with persisted
credentials disabled.

GitHub concurrency keeps at most one running and one pending job per PR. A
third arrival replaces the older pending job even with cancellation disabled;
the newest job's post-admission state reread subsumes the skipped intermediate
publication. If that newest run fails or is cancelled, operators recover with
the exact authorized refresh comment, a PR-specific manual dispatch, the
bounded blank dispatch, or a later admitted event.
