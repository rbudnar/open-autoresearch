# template/ — files to copy into your host project

This directory is **not** part of the open-autoresearch repo's runtime. It is a scaffold the agent (or human) copies into the host project as `<host>/autoresearch/`.

## How to use

```bash
# From your host project root:
cp -R /path/to/open-autoresearch/template/ ./autoresearch/

# Then, for every *.example.yaml, rename to drop the suffix:
for f in autoresearch/config/*.example.yaml; do
  mv "$f" "${f%.example.yaml}.yaml"
done
```

After this step you have a `<host>/autoresearch/` directory matching the layout described in `PROTOCOL.md` §4. None of the configs are usable yet — they are template placeholders with `<FILL_ME>` fields. Read `PROTOCOL.md` §1.5 ("Start Here") and edit them.

## Layout

```text
template/
├── PROTOCOL_VERSION              # contains "0.4"
├── README.md                     # this file
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
│   ├── behavioral_equivalence.py # §17.1.1 fixture check
│   └── verifier/
│       ├── verify_request.py     # §10.5 non-agent verifier
│       └── sign_packet.py        # §10.5 packet signer
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
