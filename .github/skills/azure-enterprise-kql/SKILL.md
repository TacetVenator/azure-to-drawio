---
name: azure-enterprise-kql
description: Use when performing Azure enterprise analysis with Global Reader constraints, KQL-based diagnostics, recent Microsoft documentation checks, and ARM schema validation of planned logic.
---

# Azure Enterprise KQL and Validation

Use this skill for enterprise Azure analysis and planning in read-only or controlled-change contexts.

## Operational Assumptions

- Default role profile: `Global Reader` only.
- Prefer read-only discovery and evidence gathering first.
- Escalate for additional RBAC only when a requirement is blocked.

## What This Skill Does

- Builds KQL query packs for common Azure diagnostics and inventory tasks.
- Verifies assumptions against current Microsoft Azure documentation.
- Validates planned resource logic against ARM schema structures when required.

## Documentation Rule

Before final recommendations, check relevant Microsoft docs and state:

- URL used
- Doc section matched
- Any version/date caveats

## ARM Schema Validation Rule

When infrastructure logic is proposed, validate required keys and common mistakes using:

```bash
python3 .github/skills/azure-enterprise-kql/scripts/arm_schema_quickcheck.py --template <template.json>
```

This is a quick structural validator, not a full deployment validator.

## KQL Pack Helper

Generate common KQL starter queries:

```bash
python3 .github/skills/azure-enterprise-kql/scripts/kql_pack_builder.py --topic governance
```

Available topics:

- `governance`
- `cost`
- `network`
- `security`
- `inventory`

## Output Requirements

- Scope and RBAC assumption confirmation
- KQL queries used or recommended
- Documentation citations summary
- ARM schema quickcheck results when applicable
- Risks, gaps, and next actions
