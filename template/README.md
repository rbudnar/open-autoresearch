# template/ — files to copy into your host project

This directory is **not** part of the open-autoresearch repo's runtime. It is a scaffold the agent (or human) copies into the host project as `<host>/autoresearch/`.

## How to use

For agents: read `AGENTS.md` at the repo root first — it walks the full 8-step bootstrap. The instructions below are the human shortcut.

```bash
# From your host project root:
cp -R /path/to/open-autoresearch/template/ ./autoresearch/

# Then, for every config example, copy to the un-suffixed name.
# Files are *.yaml.example (not *.example.yaml); strip just the .example.
for f in autoresearch/config/*.yaml.example; do
  cp "$f" "${f%.example}"
done
```

After this step you have a `<host>/autoresearch/` directory matching the layout described in `PROTOCOL.md` §4. None of the configs are usable yet — they are template placeholders with `<FILL_ME>` fields. Read `PROTOCOL.md` §1.5 ("Start Here") and edit them, OR walk `BOOTSTRAP_QUESTIONS.yaml` with an agent.

When you're done, verify the install:

```bash
python /path/to/open-autoresearch/template/scripts/bootstrap_verify.py <host-root>
```

Exit 0 = bootstrap complete and self-consistent.

## Layout

```text
template/
├── PROTOCOL_VERSION              # contains "0.4"
├── README.md                     # this file
├── BOOTSTRAP_QUESTIONS.yaml      # questionnaire the integrating agent walks with the human
├── config/
│   ├── enforcement.yaml.example  # §3.1.1: pick an enforcement mechanism
│   ├── metrics.yaml.example      # §6.1: cost tier, metrics, budgets, exposure
│   ├── editable_paths.yaml.example
│   └── protected_paths.yaml.example
├── state/
│   └── README.md                 # describes the runtime state files the agent creates
├── literature/
│   ├── canon.bib.example         # §9.0 offline-mode seed bibliography
│   └── briefs/
├── scripts/
│   ├── behavioral_equivalence.py     # §17.1.1 fixture check (verify-only)
│   ├── bootstrap_verify.py           # end-of-bootstrap smoke test
│   ├── check_questionnaire_drift.py  # CI drift check vs BOOTSTRAP_QUESTIONS.yaml
│   └── verifier/
│       ├── verify_request.py         # §10.5 non-agent verifier
│       └── sign_packet.py            # §10.5 packet signer
└── templates/                    # markdown templates for proposals, reports, packets
    ├── proposal_template.md
    ├── promotion_request_template.md
    ├── promotion_packet_template.md
    ├── result_report_template.md
    ├── literature_review_template.md
    ├── skeptic_review_template.md
    └── counter_example_report_template.md
```

## Once stamped, what changes

The protocol expects your host project to have, at minimum:

- `data/splits/MANIFEST.json` — content hashes of frozen train/val/test splits (§6.3.1). Must be in `protected_paths`.
- `evaluation/fixtures/` — golden fixtures the behavioral-equivalence script reads (§17.1.1). Must be in `protected_paths`.
- `evaluation/metric_defs.py` (or your project's equivalent) — the locked evaluator code. Must be in `protected_paths`.

These live **outside** `autoresearch/` because they describe your project's data and metrics, not the autoresearch loop's machinery.
