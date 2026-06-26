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
