---
name: landing-zone-migration-factory
description: Use for end-to-end Azure Landing Zone migration planning, wave orchestration, dependency-aware sequencing, and execution governance across mixed workloads.
---

# Landing Zone Migration Factory

Use this skill to plan and run a multi-wave migration for mixed Azure estates with compliance debt.

## Scope

- Migrating from VM-centric workloads to platform services including Logic Apps.
- Managing mixed integration footprints such as Dynamics-connected Logic Apps.
- Sequencing remediation and migration waves with business risk controls.

## Operating Model

1. Baseline inventory and classify workloads by criticality, coupling, and migration pattern.
2. Prioritize and remediate non-compliance blockers that prevent safe migration.
3. Build migration waves with rollback points and dependency constraints.
4. Execute wave-by-wave with validation gates and business sign-off.

## Helper Script

Generate migration waves from a CSV inventory:

```bash
python3 .github/skills/landing-zone-migration-factory/scripts/migration_wave_planner.py --input workload_inventory.csv --max-wave-size 12
```

Expected CSV columns:

- `workload`
- `criticality` (`high|medium|low`)
- `pattern` (`rehost|refactor|logicapp`)
- `blockedByCompliance` (`yes|no`)
- `dependsOn` (semicolon-delimited workload names)

## Output Requirements

- Wave plan with scope and owners
- Preconditions for each wave
- Rollback criteria and go/no-go gates
- Risks and unresolved dependency chain
