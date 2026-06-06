---
protocol_version: "0.5"
packet_id: "20260518-233753-pkt"
request_id: "20260518-220000-bbb008"
status: "rejected"
enforcement: "in_band_only"
not_deployable: true
maturity_level: 3
---

# Promotion Packet (verifier-written)

**Status:** `rejected`
**Enforcement:** `in_band_only`
**Not deployable:** `True`

## Verifier identity

```yaml
type: "non_agent_ci"
identity: "smoke-test"
signed_at: "2026-05-18T23:37:53.468894+00:00"
signature: "unsigned"
```

## §10.5 verifier validation results

| Rule | Pass | Note |
|---|---|---|
| 1_protocol_version_match | True |  |
| 2_references_rehash | True |  |
| 3_maturity_level_ge_3 | True |  |
| 4_role_separation_ok | True |  |
| 5_stack_requires_factorial | True |  |
| 6_val_exposure_not_exhausted | False | val exposure 52 >= budget 50; §17.6 requires holdout refresh before further promotion |
| 7_behavioral_equivalence_passed | True |  |
| 8_skeptic_verdict_clean | True |  |
| 9_statistics_recomputed | True |  |
| 10_enforcement_caps_status | True |  |

## Rejection reasons

- val exposure 52 >= budget 50; §17.6 requires holdout refresh before further promotion

## Authoritative artifact

The signed JSON sidecar at `20260518-220000-bbb008-promotion-packet.json` is authoritative. This markdown is a human-readable rendering only.
