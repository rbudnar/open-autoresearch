---
protocol_version: "0.4"
packet_id: "<YYYYMMDD-HHMMSS-6hex>"
request_id: "<request that produced this packet>"
status: "<promoted | low_evidence_promoted | rejected>"
enforcement: "<ci_enforced | pre_receive | oop_verifier | container_ro | in_band_only>"
not_deployable: <true | false>
maturity_level: <int from request, MUST be ≥ 3 for promoted>
---

# Promotion Packet (verifier-written, signed)

**Authored by:** the non-agent verifier (`PROTOCOL.md` §10.5).
**Authority:** this file's signed JSON sidecar is the authoritative promotion artifact. The agent CANNOT write this file under §3.1.1 enforcement; if it did, the signature would not validate.

## Verifier identity

```yaml
verifier:
  type: "<non_agent_ci | oop_verifier_script | human>"
  identity: "<CI job id, human name, or service identity>"
  signed_at: "<ISO-8601 timestamp>"
  signature: "<HMAC or detached signature over the packet JSON fields>"
```

## §18 criteria check results

The verifier re-runs each criterion against the referenced ledger entries.

| # | Criterion | Pass |
|---|---|---|
| 1 | Primary metric clears `minimum_meaningful_delta` (§13.2.1) | <true \| false> |
| 2 | Statistical evidence direction-aware (§13.2.1) | <true \| false> |
| 3 | Guardrails pass (Holm-corrected) | <true \| false> |
| 4 | Subgroup regressions acceptable | <true \| false> |
| 5 | Candidate seed-rerun count = <N> | <true \| false> |
| 6 | Baseline rerun matches initial within seed-variance | <true \| false> |
| 7 | Ablation per §16.1 supports causal mechanism | <true \| false> |
| 8 | Protected paths unchanged (per §3.1.1 mechanism) | <true \| false> |
| 9 | No leakage detected | <true \| false> |
| 10 | Runtime / memory / inference cost within budget | <true \| false> |
| 11 | Reproducible within §17.5.1 fixed tolerance | <true \| false> |
| 12 | Skeptic review complete at required separation level | <true \| false> |
| 13 | Human review (required for production-facing or `low_evidence_promoted`) | <true \| false \| pending> |
| 14 | Validation-set exposure budget not exhausted (§17.6) | <true \| false> |
| 15 | Total campaign budgets not exceeded (§17.7) | <true \| false> |
| 16 | Promotion request schema valid (§10.5) | <true \| false> |
| 17 | Maturity level ≥ 3 (§24 prerequisite) | <true \| false> |

## Rejection reasons (only when `status: rejected`)

- <rejection reason 1>
- <rejection reason 2>

## Derived summary

(One paragraph by the verifier, not by the agent. Describes what was promoted and what evidence supports the promotion. Pulled from the references — does not introduce new claims.)

## Artifacts

```yaml
artifacts:
  signed_archive: "<path or content-addressed bundle id>"
  derived_summary_path: "<this file>"
```

## How to read this file

- `status: promoted` + `enforcement: <not in_band_only>` + `not_deployable: false` → safe to deploy with normal change-management.
- `status: low_evidence_promoted` + any `enforcement` → human deploy override required regardless of audience.
- `status: rejected` → candidate returns to `promotion_candidate`. The agent may revise and resubmit with a new `request_id`.
- Any verifier signature that fails validation → discard the packet; the verifier was not the declared identity.
