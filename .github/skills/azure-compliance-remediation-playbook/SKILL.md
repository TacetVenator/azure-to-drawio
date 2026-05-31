---
name: azure-compliance-remediation-playbook
description: Use for triaging Azure non-compliance findings, ranking remediation actions by migration impact, and producing wave-safe policy remediation plans.
---

# Azure Compliance Remediation Playbook

Use this skill when non-compliant resources are blocking migration progress.

## Workflow

1. Collect policy findings and map to impacted workloads.
2. Rank findings by blast radius and migration blocking impact.
3. Split actions into immediate blockers vs deferred hardening.
4. Track remediation evidence per workload wave.

## Helper Script

Prioritize policy findings from CSV:

```bash
python3 .github/skills/azure-compliance-remediation-playbook/scripts/compliance_gap_ranker.py --input policy_findings.csv
```

Expected CSV columns:

- `resourceId`
- `policyName`
- `severity` (`critical|high|medium|low`)
- `migrationBlocker` (`yes|no`)
- `owner`

## Output Requirements

- Top remediation backlog by blocker class
- Suggested ownership and target wave
- Risk accepted vs risk remediated split
