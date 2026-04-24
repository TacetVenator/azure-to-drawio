---
name: azdisc-enterprise
description: Use when helping an organization run azure-to-drawio/tools.azdisc for read-only Azure discovery, architecture diagrams, governance review, migration planning, or stakeholder reporting.
---

# Azure Discovery In Real Organizations

Use this skill when operating or changing `tools.azdisc` for enterprise Azure discovery. Optimize for safe scoping, evidence quality, repeatable outputs, and stakeholder-ready reports.

## Core Rules

- Treat the tool as read-only. Do not change Azure resources, policies, RBAC, networking, diagnostics, or tags.
- Start narrow, then broaden intentionally. Prefer exact resource IDs, app tags, or known resource groups before whole subscriptions or management groups.
- Preserve evidence boundaries. Clearly separate discovered facts, inferred relationships, unresolved references, and missing visibility.
- Do not print secrets or sensitive artifact content into chat. Summarize findings and point to local artifact paths.
- For code changes, read `Doc4agents.md` before changing discovery behavior.

## First-Run Workflow

1. Confirm the organization goal: inventory, diagram, migration assessment, governance review, or stakeholder pack.
2. Confirm the safest scope:
   - Known application resource: use `seedResourceIds`.
   - Known app tags: use `seedTags` or `seedTagKeys`.
   - Known workload RGs: use `seedResourceGroups`.
   - Platform or estate review: use `seedManagementGroups` or `seedEntireSubscriptions` only after confirming expected scale/noise.
3. Prefer the wizard for first-time users:

```bash
python3 -m tools.azdisc wizard app/<app>/config.json
```

4. For repeatable runs, review or create config directly, then run:

```bash
python3 -m tools.azdisc run app/<app>/config.json
```

5. Open `master_report.md` first. Use it as the report landing page for stakeholders.

## Artifact Triage

Inspect artifacts in this order:

- `master_report.md`: executive landing page and links to the rest of the pack.
- `diagram.drawio`: editable architecture diagram.
- `inventory_by_type/manifest.json`: spreadsheet-friendly inventory by Azure resource type.
- `catalog.md`, `organization.md`, `resource_groups.md`, `resource_types.md`: estate and inventory summaries.
- `edges.md`, `routing.md`, `migration.md`: dependencies, network/security context, and migration-readiness clues.
- `policy_summary.md`, `policy_by_resource.md`, `policy_by_policy.md`: policy compliance views when policy collection is enabled.
- `rbac_summary.md`: access review view when RBAC collection is enabled.
- `migration-plan/`: questionnaires, decision register, wave plan, stakeholder pack, and Copilot prompts when migration planning is enabled.
- `unresolved.json` and `expand_reasons.md`: missing dependencies and why resources were included.

## Enterprise Conversation Checklist

Before running discovery, clarify:

- Which subscriptions, management groups, resource groups, tags, or exact resources are in scope?
- Is this for application migration, platform review, audit evidence, troubleshooting, or documentation?
- What permissions are available: Reader, Global Reader, Policy Reader, RBAC visibility, Entra visibility?
- Are Advisor, quota, policy, RBAC, telemetry, or software inventory outputs needed?
- Which tags define application ownership, environment, criticality, or cost center?
- Are shared services expected, such as hub VNets, private DNS, Log Analytics, Key Vault, firewalls, or identity components?
- Who will consume the output: cloud engineers, app owners, auditors, migration PMs, or executives?

## Safe Expansion Guidance

- Keep `expandScope: "related"` as the default for application work.
- Use `expandScope: "all"` only when the user accepts broader graph traversal and potential platform noise.
- Use deep discovery for due diligence when resources may be related by names, tags, or properties but are not reachable through ARM references.
- Do not casually broaden network discovery. Hub, peering, route, and shared-platform fan-out can overwhelm app-scoped reports.

## When Changing The Tool

- Read `Doc4agents.md` first for pipeline boundaries, discovery invariants, and high-signal tests.
- Preserve the pipeline shape: seed -> expand -> optional enrichment -> graph -> drawio/html/docs -> split/migration/analysis.
- Prefer artifact consumers over new live Azure calls outside discovery/enrichment stages.
- If adding discovery breadth, update discovery tests and check whether graph edge extraction also needs an update.
- If changing wizard prompts or run behavior, update wizard and CLI tests.
- If changing report wording only, update README or report generators without changing discovery behavior.

## Validation Commands

Use focused tests for the area changed:

```bash
python3 -m pytest tools/azdisc/tests/test_cli.py tools/azdisc/tests/test_wizard.py
```

For discovery behavior:

```bash
python3 -m pytest tools/azdisc/tests/test_expand_scope.py tools/azdisc/tests/test_deep_discovery.py tools/azdisc/tests/test_graph_edges.py
```

For full confidence:

```bash
python3 -m pytest tools/azdisc/tests
```
