---
name: vm-to-logicapps-modernization
description: Use for workload modernization planning from VM-hosted jobs/services to Logic Apps with trigger/action mapping, connector strategy, and cutover sequencing.
---

# VM to Logic Apps Modernization

Use this skill to transform VM-based integration or scheduling workloads into Logic App implementations.

## Transformation Heuristics

- Batch/scheduled scripts -> Recurrence trigger + action workflow
- Polling jobs -> Event-driven triggers where possible
- Long-running VM glue code -> Durable or split Logic App patterns
- Secret handling -> Managed identity + Key Vault references

## Helper Script

Build a draft modernization map from CSV inventory:

```bash
python3 .github/skills/vm-to-logicapps-modernization/scripts/vm_workload_mapper.py --input vm_workloads.csv
```

Expected CSV columns:

- `workload`
- `jobType`
- `frequency`
- `externalSystems` (semicolon-delimited)
- `stateful` (`yes|no`)

## Output Requirements

- Candidate Logic App pattern per workload
- Connector requirements and identity strategy
- Rollout plan with parallel run and cutover checks
