---
name: logicapps-dynamics-integration
description: Use for Logic Apps integrations with Microsoft Dynamics, including connector design, throttling strategy, retry/idempotency controls, and migration-safe cutover planning.
---

# Logic Apps Dynamics Integration

Use this skill when Logic Apps must integrate with Dynamics 365 or Dataverse during modernization.

## Design Checklist

- Connector model: managed connector vs custom connector
- Auth model: managed identity, service principal, or delegated flow (avoid user-bound creds)
- Throughput and throttling limits by endpoint
- Idempotency keys and duplicate-protection strategy
- Error routing: dead-letter or compensating flow

## Helper Script

Generate an integration readiness checklist:

```bash
python3 .github/skills/logicapps-dynamics-integration/scripts/dynamics_readiness_check.py --input integrations.csv
```

Expected CSV columns:

- `integrationName`
- `dynamicsEndpoint`
- `expectedRps`
- `idempotent` (`yes|no`)
- `hasRetryPolicy` (`yes|no`)
- `authModel`

## Output Requirements

- Integration-by-integration readiness status
- Required hardening actions
- Cutover dependencies and rollback plan
