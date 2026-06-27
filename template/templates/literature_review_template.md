---
protocol_version: "0.5"
brief_id: "<YYYYMMDD-slug>"
branch: "<architecture | loss_objective | data_sampling | features | optimization | calibration | systems_efficiency>"
mode: "<live | offline>"
literature_status: "<live_search | canon_only | not_literature_verified>"
web_search_used: <true | false>
scout_agent: "<claude-sonnet-4.5 | codex | gemini-pro | other>"
---

# Literature Brief: <branch> / <hypothesis>

## Search scope

- **Date range searched:** <e.g., 2024-01-01 to 2026-05-18>
- **Sources searched:** <arxiv | papers-with-code | github | hf | conference proceedings | canon.bib offline | ...>
- **Queries used:** <verbatim>

(If `mode: offline`, the Scout worked only from `canon.bib` and the host project's own docs. Novel-architecture claims are blocked in offline mode per §9.0.)

## Candidate ideas

### Idea 1: <name>

- **Source:** <link or canon.bib key>
- **Source type:** <peer-reviewed | preprint | blog | repo | speculation | withdrawn>
- **Citation risk:** <peer_reviewed | technical_report | arxiv_preprint | withdrawn | unknown>
- **Mechanism:** <one sentence>
- **Evidence quality:** <strong | medium | weak — with reasoning>
- **Implementation complexity:** <low | medium | high>
- **Expected benefit:** <on which metric/subgroup>
- **Risks:** <leakage | compute | metric gaming | adapter / dependency complexity>
- **Novelty check:** <why this is not just a rejected sibling, stale retry, or already-covered baseline>
- **Implementation precedent:** <paper/code evidence that the idea has been made to run, or "none found">
- **Minimal test:** <smallest experiment that would distinguish this idea from baseline>

### Idea 2: ...

## Recommended next experiment

(One paragraph. Which candidate to implement first, why, and what the smallest valid test looks like.)

## Ideas rejected for now

- <idea>: <reason>
- <idea>: <reason>

## Notes

(Anything the Scout wants the Director to know but doesn't belong in the structured fields above. Open questions, scope concerns, scout uncertainty.)
