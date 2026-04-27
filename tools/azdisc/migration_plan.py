"""Migration planning pack generator."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .config import Config
from .util import load_json_file, normalize_id


def _migration_output_root(cfg: Config) -> Path:
    configured = cfg.migrationPlan.outputDir.strip()
    if not configured:
        return Path(cfg.outputDir) / "migration-plan"
    out = Path(configured)
    if out.is_absolute():
        return out
    return Path(cfg.outputDir) / out


def _load_optional(path: Path, *, expected_type: type | None = None) -> Any:
    if not path.exists():
        return [] if expected_type is list else None
    return load_json_file(
        path,
        context="Migration plan artifact",
        expected_type=expected_type,
        advice=f"Fix {path.name} or regenerate the prerequisite artifact before running migration-plan.",
    )


def _public_indicators(nodes: List[Dict[str, Any]]) -> List[str]:
    findings: List[str] = []
    for node in nodes:
        ntype = (node.get("type") or "").lower()
        props = node.get("properties") or {}
        if ntype == "microsoft.network/publicipaddresses":
            findings.append(node.get("name") or node.get("id"))
        elif props.get("defaultHostName"):
            findings.append(f"{node.get('name')} ({props.get('defaultHostName')})")
        elif str(props.get("publicNetworkAccess", "")).lower() == "enabled":
            findings.append(node.get("name") or node.get("id"))
    return sorted(dict.fromkeys(findings))


def _private_endpoint_count(nodes: List[Dict[str, Any]]) -> int:
    return sum(
        1
        for node in nodes
        if (node.get("type") or "").lower() == "microsoft.network/privateendpoints"
    )


def _shared_targets(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Tuple[str, int, int, int]]:
    node_by_id = {normalize_id(node["id"]): node for node in nodes if node.get("id")}
    incoming: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source = node_by_id.get(normalize_id(edge.get("source", "")))
        target_id = normalize_id(edge.get("target", ""))
        target = node_by_id.get(target_id)
        if source and target and not target.get("isExternal"):
            incoming[target_id].append(source)

    rows: List[Tuple[str, int, int, int]] = []
    for target_id, sources in incoming.items():
        rgs = {source.get("resourceGroup") for source in sources if source.get("resourceGroup")}
        subs = {source.get("subscriptionId") for source in sources if source.get("subscriptionId")}
        if len(rgs) < 2 and len(subs) < 2:
            continue
        target = node_by_id[target_id]
        rows.append((target.get("name") or target_id, len(sources), len(rgs), len(subs)))
    rows.sort(key=lambda row: (-row[3], -row[2], -row[1], row[0].lower()))
    return rows[:20]


def _policy_summary(policy_rows: List[Dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for row in policy_rows:
        state = (row.get("complianceState") or "Unknown").strip() or "Unknown"
        counts[state] += 1
    return counts


def _top_resource_types(inventory: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    counts = Counter((resource.get("type") or "unknown").lower() for resource in inventory)
    return counts.most_common(10)


def _build_pack_summary(
    pack_name: str,
    graph: Dict[str, Any],
    inventory: List[Dict[str, Any]],
    unresolved: List[str],
    policy_rows: List[Dict[str, Any]],
    rbac_rows: List[Dict[str, Any]],
    slice_manifest: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    public_indicators = _public_indicators(nodes)
    private_endpoint_count = _private_endpoint_count(nodes)
    policy_summary = dict(_policy_summary(policy_rows))
    shared_targets = _shared_targets(nodes, edges)
    telemetry_edges = len(graph.get("telemetryEdges") or [])
    non_compliant_policies = policy_summary.get("NonCompliant", 0)
    app_boundary = {
        "available": False,
        "confidence": 1.0,
        "ambiguityLevel": "low",
        "ambiguousResourceGroupCount": 0,
        "ambiguousResourceCount": 0,
        "ambiguousResourceGroups": [],
    }
    if isinstance(slice_manifest, dict) and isinstance(slice_manifest.get("appBoundary"), dict):
        boundary = slice_manifest["appBoundary"]
        app_boundary = {
            "available": True,
            "confidence": float(boundary.get("confidence", 1.0)),
            "ambiguityLevel": str(boundary.get("ambiguityLevel", "low")),
            "ambiguousResourceGroupCount": int(boundary.get("ambiguousResourceGroupCount", 0)),
            "ambiguousResourceCount": int(boundary.get("ambiguousResourceCount", 0)),
            "ambiguousResourceGroups": list(boundary.get("ambiguousResourceGroups") or []),
        }

    return {
        "pack": pack_name,
        "resources": len(inventory) or len(nodes),
        "graphNodes": len(nodes),
        "graphEdges": len(edges),
        "subscriptions": sorted({node.get("subscriptionId") for node in nodes if node.get("subscriptionId")}),
        "resourceGroups": sorted({node.get("resourceGroup") for node in nodes if node.get("resourceGroup")}),
        "unresolved": len(unresolved),
        "publicIndicators": public_indicators,
        "privateEndpointCount": private_endpoint_count,
        "policySummary": policy_summary,
        "rbacAssignments": len(rbac_rows),
        "topTypes": _top_resource_types(inventory),
        "sharedTargets": shared_targets,
        "hasTelemetry": bool(telemetry_edges),
        "telemetryEdges": telemetry_edges,
        "externalNodes": sum(1 for node in nodes if node.get("isExternal")),
        "hasPublicExposure": bool(public_indicators),
        "hasPrivateEndpoints": private_endpoint_count > 0,
        "hasPolicyEvidence": bool(policy_rows),
        "hasNonCompliantPolicies": non_compliant_policies > 0,
        "nonCompliantPolicies": non_compliant_policies,
        "hasSharedDependencies": bool(shared_targets),
        "hasUnresolvedReferences": bool(unresolved),
        "appBoundaryAnalysis": app_boundary,
    }


def _write_markdown(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _render_migration_plan(cfg: Config, summary: Dict[str, Any], is_root: bool) -> List[str]:
    scope_label = "Root coordination pack" if is_root else "Application migration pack"
    lines = [
        f"# Migration Plan — {summary['pack']}",
        "",
        f"_Generated: {date.today().isoformat()}_",
        "",
        f"{scope_label} for audience `{cfg.migrationPlan.audience}`.",
        "",
        "## Current State Summary",
        "",
        f"- Resources: {summary['resources']}",
        f"- Graph nodes: {summary['graphNodes']}",
        f"- Graph edges: {summary['graphEdges']}",
        f"- Subscriptions: {len(summary['subscriptions'])}",
        f"- Resource groups: {len(summary['resourceGroups'])}",
        f"- Unresolved references: {summary['unresolved']}",
        f"- External placeholder nodes: {summary['externalNodes']}",
        f"- RBAC assignments captured: {summary['rbacAssignments']}",
        f"- Policy records captured: {sum(summary['policySummary'].values())}",
        "",
        "## Step-by-Step Migration Plan",
        "",
        "1. Confirm scope, owners, and business criticality for this pack.",
        "2. Validate shared dependencies, cross-subscription coupling, and target landing-zone placement.",
        "3. Resolve compliance gaps and document waivers, exemptions, or required remediation before cutover.",
        "4. Define foundation prerequisites: networking, identity, DNS, observability, and backup expectations.",
        "5. Plan migration waves and cutover pattern with rollback checkpoints.",
        "6. Capture open questions, decisions, and stakeholder approvals before execution.",
        "",
        "## Generated Inputs To Complete",
        "",
        "- `migration-questionnaire.md` for stakeholder and engineering inputs",
        "- `migration-decisions.md` for decisions and approvals",
        "- `decision-trees.md` for migration choice guidance",
        "- `wave-plan.md` for sequencing",
        "- `stakeholder-pack.md` for non-technical communication",
        "- `technical-gaps.md` for code-addressable discovery and evidence gaps",
    ]
    if cfg.migrationPlan.includeCopilotPrompts:
        lines.append("- `copilot-prompts.md` for Copilot-assisted refinement")
    lines += [
        "",
        "## Known Risks And Blockers",
        "",
    ]
    blocker_lines: List[str] = []
    if summary["sharedTargets"]:
        blocker_lines.append(
            f"{len(summary['sharedTargets'])} shared dependency candidates require ownership and target-state decisions."
        )
    if summary["unresolved"]:
        blocker_lines.append("Unresolved references remain and can hide off-scope dependencies or deleted resources.")
    if not summary["hasTelemetry"]:
        blocker_lines.append("No telemetry-derived relationships were available for this pack; runtime coupling may be understated.")
    if not summary["policySummary"]:
        blocker_lines.append("No policy state evidence was available; compliance interpretation is incomplete.")
    if not blocker_lines:
        blocker_lines.append("No high-confidence blockers were inferred from the current artifacts alone.")
    lines.extend(f"- {line}" for line in blocker_lines)
    app_boundary = summary.get("appBoundaryAnalysis") or {}
    if app_boundary.get("available"):
        lines += [
            "",
            "## Application Boundary Confidence",
            "",
            f"- Boundary confidence: {app_boundary.get('confidence', 1.0)}",
            f"- Ambiguity level: {app_boundary.get('ambiguityLevel', 'low')}",
            f"- Ambiguous resource groups: {app_boundary.get('ambiguousResourceGroupCount', 0)}",
            f"- Resources in ambiguous groups: {app_boundary.get('ambiguousResourceCount', 0)}",
        ]
    return lines


def _render_questionnaire(summary: Dict[str, Any]) -> List[str]:
    lines = [
        f"# Migration Questionnaire — {summary['pack']}",
        "",
        "Use this pack as an interview guide. Capture answers inline or copy the questions into your working session notes.",
        "",
        "## Interview Plan",
        "",
        "1. Meet the application owner and business sponsor to confirm scope, criticality, and change constraints.",
        "2. Meet the platform, security, and network teams to validate landing-zone readiness and shared services.",
        "3. Meet the operations and support teams to confirm monitoring, backup, DR, and cutover readiness.",
        "4. Close open decisions in `migration-decisions.md` before execution planning starts.",
        "",
        "## Business Sponsor / Application Owner",
        "- What business capability does this workload support, and what is the impact if it is unavailable?",
        "- Which environments are in scope: production, DR, test, shared services, batch, integration?",
        "- What are the approved maintenance windows, blackout periods, and escalation contacts?",
        "- What are the RTO and RPO expectations, and are they contractual or informal?",
        "- Which parts of the solution can tolerate coexistence during migration, and which require a single cutover event?",
        "- Which downstream business processes, partners, or users must be informed before cutover?",
        "",
        "## Application Engineering",
        "- Which components are stateful vs stateless, and which ones can be rebuilt from code?",
        "- Which runtime dependencies are not visible in Azure resource relationships: hard-coded URLs, certificates, third-party APIs, scheduled jobs, agents, file shares?",
        "- Which configuration items change per environment: DNS names, connection strings, secrets, firewall rules, identity endpoints?",
        "- What is the current deployment model: manual, pipeline-based, image-based, or script-based?",
        "- Which cutover patterns are technically possible: rehost, blue/green, phased, active/passive, dual-write, or big bang?",
        "- Which validation steps prove the application is healthy after migration?",
        "",
        "## Identity And Access",
        "- Which managed identities, service principals, certificates, and Key Vault references must be recreated or reauthorized?",
        "- Which people or groups currently have privileged access, and which of those access paths should be removed in the target state?",
        "- Are any application-to-application trust relationships dependent on IP allowlists, shared secrets, or Entra app registrations?",
        "- Which RBAC assignments are required for runtime, deployment, operations, and break-glass support?",
        "- What approvals are required for access changes during cutover and rollback?",
        "",
        "## Network, Connectivity, And DNS",
        "- Which private endpoints, private DNS zones, routes, firewalls, proxies, or on-prem paths are mandatory in the target landing zone?",
        "- Does the workload require fixed outbound IPs, inbound public endpoints, partner connectivity, or hybrid network reachability?",
        "- Which name resolution paths must change during migration, and how will DNS TTL and propagation be handled?",
        "- Are there shared hub, inspection, or egress services that must migrate first or remain stable during cutover?",
        "",
        "## Data, State, And Resilience",
        "- Which data stores require replication, seeding, export/import, or ongoing synchronization?",
        "- What is the largest data set involved, and how long can data synchronization run before cutover?",
        "- What are the backup, restore, and DR recovery procedures today, and are they tested?",
        "- Which components cannot lose in-flight transactions or queued work during migration?",
        "",
        "## Security, Compliance, And Operations",
        "- Which policy violations must be remediated before go-live, and which require formal exceptions or waivers?",
        "- Which Defender, logging, monitoring, alerting, and audit requirements are mandatory before production cutover?",
        "- Which operational runbooks, dashboards, alerts, and support handoffs must be updated for the target environment?",
        "- Which smoke tests, rollback tests, and hypercare checkpoints are required after migration?",
        "",
        "## Cutover And Rollback",
        "- What is the exact business decision point for go / no-go?",
        "- What events force rollback, and who has authority to trigger it?",
        "- What must remain unchanged until rollback is no longer possible: DNS, data sync, old environment, network paths, access?",
        "- What evidence must be captured during cutover for audit and post-migration review?",
    ]
    if summary["hasPrivateEndpoints"]:
        lines += [
            "",
            "## Private Connectivity And DNS",
            f"- Discovery signal: {summary['privateEndpointCount']} private endpoint resource(s) detected.",
            "- Which private DNS zones, zone links, conditional forwarders, or custom DNS resolvers must exist before cutover?",
            "- Which consumers depend on private name resolution across peered VNets, hubs, or on-prem networks?",
            "- Which endpoints require static IP expectations, subnet placement, or firewall approvals in the target state?",
            "- What validation proves private connectivity works end-to-end before public or legacy paths are disabled?",
        ]
    if summary["hasPublicExposure"]:
        lines += [
            "",
            "## Public Exposure Review",
            f"- Discovery signal: {len(summary['publicIndicators'])} public exposure indicator(s) detected.",
            "- Which public endpoints are intentionally customer-facing vs temporary or legacy exposures?",
            "- Which controls must front those endpoints in the target state: WAF, reverse proxy, DDoS controls, IP restrictions, or CDN?",
            "- Which certificates, custom domains, redirects, and external allowlists must move with the exposure?",
            "- Which validation checks confirm the new public path is healthy before traffic is shifted?",
        ]
    if summary["hasNonCompliantPolicies"]:
        lines += [
            "",
            "## Compliance Remediation Interview",
            f"- Discovery signal: {summary['nonCompliantPolicies']} non-compliant policy record(s) detected.",
            "- Which non-compliant controls are deployment blockers vs advisory findings for this workload?",
            "- Which findings can be remediated in the migration wave, and which require a formal exception or time-bound waiver?",
            "- Who owns each remediation item, and what evidence is required to close it?",
            "- Which controls must be revalidated immediately after cutover?",
        ]
    if summary["hasSharedDependencies"]:
        lines += [
            "",
            "## Shared Services And Coordination",
            f"- Discovery signal: {len(summary['sharedTargets'])} shared dependency candidate(s) detected.",
            "- Which shared services are truly multi-application or platform-owned, and who approves changes to them?",
            "- Must the shared service migrate first, stay in place, or be consumed cross-environment during coexistence?",
            "- Which other application teams, platform teams, or CAB processes must be coordinated for cutover and rollback?",
            "- Which sequencing constraints prevent this workload from moving independently?",
        ]
    if summary["hasUnresolvedReferences"] or not summary["hasTelemetry"]:
        lines += ["", "## Evidence Follow-Up"]
        if summary["hasUnresolvedReferences"]:
            lines.append("- Which unresolved references represent real dependencies vs deleted or out-of-scope resources?")
        if not summary["hasTelemetry"]:
            lines.append("- Which runtime calls or operational dependencies may be missing because no telemetry-derived edges were captured?")
        lines.append("- What extra evidence should be gathered before final wave planning: telemetry, code/config review, CMDB data, or SME interviews?")
    lines += [
        "",
        "## Known Signals From Discovery",
        f"- Shared dependency candidates detected: {len(summary['sharedTargets'])}",
        f"- Public exposure indicators detected: {len(summary['publicIndicators'])}",
        f"- Private endpoints detected: {summary['privateEndpointCount']}",
        f"- Non-compliant policy records detected: {summary['nonCompliantPolicies']}",
        f"- Unresolved references detected: {summary['unresolved']}",
        f"- Policy records captured: {sum(summary['policySummary'].values())}",
        f"- Telemetry-derived relationships captured: {summary['telemetryEdges']}",
    ]
    return lines


def _render_decisions(summary: Dict[str, Any]) -> List[str]:
    return [
        f"# Migration Decisions — {summary['pack']}",
        "",
        "Use this register to capture the decisions made while completing the questionnaire and decision trees.",
        "",
        "| decision | status | owner | due date | evidence | notes |",
        "|----------|--------|-------|----------|----------|-------|",
        "| Target landing-zone placement confirmed | Open | TBD | TBD | graph, policy, shared dependencies | |",
        "| Migration pattern selected (rehost / replatform / refactor) | Open | TBD | TBD | questionnaire, runtime constraints | |",
        "| Identity model confirmed | Open | TBD | TBD | RBAC and application runtime inputs | |",
        "| Networking and DNS pattern confirmed | Open | TBD | TBD | topology, private endpoints, shared services | |",
        "| Data migration and synchronization method confirmed | Open | TBD | TBD | data store inventory, RPO/RTO input | |",
        "| Cutover and rollback strategy approved | Open | TBD | TBD | wave plan and business input | |",
        "| Compliance remediation / exception path approved | Open | TBD | TBD | policy summary and security review | |",
    ]


def _render_decision_trees(summary: Dict[str, Any]) -> List[str]:
    shared_hint = "Yes" if summary["hasSharedDependencies"] else "No"
    public_hint = "Yes" if summary["hasPublicExposure"] else "No"
    private_hint = "Yes" if summary["hasPrivateEndpoints"] else "No"
    policy_hint = "Yes" if summary["hasPolicyEvidence"] else "No"
    non_compliant_hint = "Yes" if summary["hasNonCompliantPolicies"] else "No"
    lines = [
        f"# Decision Trees — {summary['pack']}",
        "",
        "These trees are intended to be used during workshops. Follow the branches and record the result in `migration-decisions.md`.",
        "",
        "## Decision Tree 1: Choose The Migration Pattern",
        "",
        "1. Can the workload be rebuilt from code and configuration with limited infrastructure coupling?",
        "   If yes: evaluate replatform or refactor before rehost.",
        "   If no: start from a rehost baseline and reduce risk first.",
        "2. Does the workload depend on shared services or cross-subscription services?",
        f"   Discovery hint: {shared_hint}.",
        "   If yes: create prerequisite work for shared services before scheduling the application wave.",
        "   If no: the application is a better candidate for an earlier pilot wave.",
        "3. Does the workload require tight data consistency during cutover?",
        "   If yes: prefer phased migration, replication, blue/green, or parallel-run patterns.",
        "   If no: a simpler cutover may be acceptable if rollback is rehearsed.",
        "",
        "## Decision Tree 2: Network And Exposure",
        "",
        "1. Does the workload expose public endpoints or rely on public network access?",
        f"   Discovery hint: {public_hint}.",
        "   If yes: decide whether the target should preserve public exposure, move behind reverse proxy/WAF, or move to private-only access.",
        "2. Does the workload require private endpoints, hybrid connectivity, or hub inspection services?",
        f"   Discovery hint: {private_hint}.",
        "   If yes: validate DNS, firewall, route, and peering prerequisites before any application wave starts.",
        "3. Will DNS or endpoint ownership change at cutover?",
        "   If yes: plan TTL reduction, ownership approvals, rollback DNS steps, and validation commands.",
        "",
        "## Decision Tree 3: Identity And Access",
        "",
        "1. Are managed identities or service principals part of the runtime path?",
        "   If yes: document which identities must be recreated, reassigned, or reconsented in the target environment.",
        "2. Are privileged RBAC assignments broader than the target operating model allows?",
        "   If yes: treat access redesign as part of migration readiness, not a post-cutover cleanup task.",
        "3. Are any secrets, certificates, or trust chains tied to the current environment?",
        "   If yes: decide whether to rotate, migrate, or dual-run those credentials during cutover.",
        "",
        "## Decision Tree 4: Compliance And Landing-Zone Readiness",
        "",
        "1. Are policy results available for the discovered resources?",
        f"   Discovery hint: {policy_hint}.",
        "   If no: generate policy evidence before finalizing the migration plan.",
        "2. Are there non-compliant controls that block production deployment into the target landing zone?",
        f"   Discovery hint: {non_compliant_hint}.",
        "   If yes: either remediate before cutover or secure a documented exception path with owners and expiry dates.",
        "3. Are logging, backup, DR, and monitoring controls present in the target environment?",
        "   If no: stop and complete foundation work first.",
        "",
        "## Decision Tree 5: Cutover And Rollback",
        "",
        "1. Can the old and new environments run in parallel for a period of time?",
        "   If yes: use that overlap to validate traffic, identity, and data movement before final cutover.",
        "   If no: tighten rollback criteria, increase rehearsal depth, and shorten the dependency chain in the cutover window.",
        "2. Is rollback technically possible after data changes begin in the target?",
        "   If yes: define the rollback trigger, latest safe decision point, and exact restoration steps.",
        "   If no: require stronger executive sign-off and production validation before switching traffic.",
    ]
    if summary["hasPrivateEndpoints"]:
        lines += [
            "",
            "## Priority Tree: Private Connectivity And DNS",
            "",
            "1. Are private endpoints part of the required runtime path?",
            f"   Discovery hint: {private_hint}.",
            "   If yes: treat private DNS, route propagation, and resolver dependencies as hard prerequisites.",
            "2. Can private DNS and endpoint approval be completed before application deployment starts?",
            "   If no: move this workload behind the networking foundation wave.",
        ]
    if summary["hasPublicExposure"]:
        lines += [
            "",
            "## Priority Tree: Public Exposure Review",
            "",
            "1. Is each discovered public endpoint still required in the target state?",
            f"   Discovery hint: {public_hint}.",
            "   If no: remove or privatize the endpoint as part of migration readiness.",
            "2. If public exposure remains, can traffic be shifted behind equivalent controls without changing the user contract?",
            "   If no: escalate the design decision before approving the cutover path.",
        ]
    if summary["hasNonCompliantPolicies"]:
        lines += [
            "",
            "## Priority Tree: Compliance Remediation",
            "",
            "1. Do any discovered non-compliant controls block deployment or production operation?",
            f"   Discovery hint: {non_compliant_hint}.",
            "   If yes: remediation or exception approval must complete before the workload enters a cutover wave.",
            "2. Is there a documented owner and due date for each non-compliant finding?",
            "   If no: keep the workload out of the committed migration schedule.",
        ]
    if summary["hasSharedDependencies"]:
        lines += [
            "",
            "## Priority Tree: Shared Services And Coordination",
            "",
            "1. Are shared services or shared targets on the critical path?",
            f"   Discovery hint: {shared_hint}.",
            "   If yes: sequence this workload after the shared-service decision and owner sign-off are complete.",
            "2. Can this workload roll back independently if the shared dependency is reused by other applications?",
            "   If no: require a coordinated rollback and communications plan.",
        ]
    if summary["hasUnresolvedReferences"]:
        lines += [
            "",
            "## Priority Tree: Unresolved Dependency Review",
            "",
            "1. Do unresolved references point to still-active resources or services?",
            "   If yes: bring them into scope or document why they remain external dependencies.",
            "2. If no: remove the stale dependency evidence before final sign-off.",
        ]
    return lines


def _render_wave_plan(summary: Dict[str, Any], is_root: bool) -> List[str]:
    lines = [
        f"# Wave Plan — {summary['pack']}",
        "",
        "## Suggested Waves",
        "- Wave 0: landing-zone foundation, policy remediation, monitoring, DNS, and identity prerequisites.",
    ]
    if summary["sharedTargets"]:
        lines.append("- Wave 1: shared services and cross-application dependencies.")
    lines.append("- Wave 2: pilot migration for one low-risk workload or bounded component.")
    lines.append("- Wave 3+: remaining workloads ordered by dependency and business risk.")
    if is_root:
        lines.append("- Final wave: coordinated cutover validation and hypercare across application packs.")
    lines += [
        "",
        "## Validation Gates",
        "- Target controls deployed and validated.",
        "- Connectivity and identity paths tested.",
        "- Backup and rollback paths rehearsed.",
        "- Stakeholder approvals recorded.",
        "",
        "## Exit Criteria Per Wave",
        "- All open decisions for that wave are closed or explicitly waived.",
        "- Application and platform owners sign off on functional validation.",
        "- Security and operations teams confirm monitoring, logging, and access expectations are met.",
        "- Rollback steps remain viable until the agreed point of no return.",
    ]
    return lines


def _render_stakeholder_pack(summary: Dict[str, Any]) -> List[str]:
    return [
        f"# Stakeholder Pack — {summary['pack']}",
        "",
        "## What Is Deployed",
        f"This pack covers {summary['resources']} discovered Azure resources across {len(summary['subscriptions'])} subscription(s) and {len(summary['resourceGroups'])} resource group(s).",
        "",
        "## What Matters For Migration",
        f"- Shared dependency candidates: {len(summary['sharedTargets'])}",
        f"- Public exposure indicators: {len(summary['publicIndicators'])}",
        f"- Compliance records captured: {sum(summary['policySummary'].values())}",
        f"- Open unresolved references: {summary['unresolved']}",
        "",
        "## Decisions Needed",
        "- Confirm target landing-zone placement and ownership boundaries.",
        "- Approve migration waves, cutover windows, and rollback expectations.",
        "- Confirm which compliance gaps must be fixed before go-live.",
    ]


def _render_technical_gaps(summary: Dict[str, Any]) -> List[str]:
    items = [
        "Add more explicit evidence confidence and source attribution into graph and reports.",
        "Add stronger ownership inference for shared and untagged resources.",
        "Improve governance interpretation from raw policy and RBAC evidence into migration-focused summaries.",
        "Expand visibility-gap reporting when permissions or unsupported surfaces hide evidence.",
        "Add stakeholder-oriented summaries so technical findings translate into decisions and migration actions.",
    ]
    if not summary["policySummary"]:
        items.append("Policy evidence was missing for this pack; improve compliance-stage adoption and summaries.")
    if not summary["hasTelemetry"]:
        items.append("Telemetry evidence was missing for this pack; improve runtime dependency coverage or retention guidance.")
    if summary["unresolved"]:
        items.append("Unresolved references remain; improve cross-scope coverage and unresolved-reference classification.")
    return [
        f"# Technical Gaps — {summary['pack']}",
        "",
        "## Code-Addressable Discovery And Visualization Gaps",
        *[f"- {item}" for item in items],
    ]


def _render_copilot_prompts(summary: Dict[str, Any]) -> List[str]:
    context = (
        f"Pack={summary['pack']}; resources={summary['resources']}; graph_nodes={summary['graphNodes']}; "
        f"graph_edges={summary['graphEdges']}; shared_targets={len(summary['sharedTargets'])}; "
        f"public_indicators={len(summary['publicIndicators'])}; unresolved={summary['unresolved']}; "
        f"policy_records={sum(summary['policySummary'].values())}; telemetry_edges={summary['telemetryEdges']}"
    )
    return [
        f"# Copilot Prompts — {summary['pack']}",
        "",
        "## Current State Summary",
        f"```text\nUsing this context: {context}. Summarize the current Azure deployment in plain English for both architects and non-technical stakeholders. Separate known facts, inferred dependencies, and open questions.\n```",
        "",
        "## Migration Review",
        f"```text\nUsing this context: {context}. Review the migration-plan, wave-plan, and migration-questionnaire outputs. Identify missing assumptions, hidden dependencies, governance gaps, and rollback risks.\n```",
        "",
        "## Target State And Inputs",
        f"```text\nUsing this context: {context}. Help complete target landing-zone placement, identity, networking, DNS, observability, and compliance decisions. Produce concise tables for decisions, assumptions, and blockers.\n```",
    ]


def _load_pack_inputs(base_dir: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    graph = load_json_file(
        base_dir / "graph.json",
        context="Migration plan graph artifact",
        expected_type=dict,
        advice="Fix graph.json or rerun the graph stage before generating the migration plan.",
    )
    inventory = _load_optional(base_dir / "inventory.json", expected_type=list) or []
    unresolved = _load_optional(base_dir / "unresolved.json", expected_type=list) or []
    policy_rows = _load_optional(base_dir / "policy.json", expected_type=list) or []
    rbac_rows = _load_optional(base_dir / "rbac.json", expected_type=list) or []
    return graph, inventory, unresolved, policy_rows, rbac_rows


def _load_slice_manifest(base_dir: Path) -> Dict[str, Any] | None:
    manifest = _load_optional(base_dir / "slice.json", expected_type=dict)
    if isinstance(manifest, dict):
        return manifest
    return None


def _pack_targets(cfg: Config) -> List[Tuple[str, Path, Path, bool]]:
    output_root = _migration_output_root(cfg)
    targets: List[Tuple[str, Path, Path, bool]] = []
    scope = cfg.migrationPlan.applicationScope
    if scope in {"root", "both"}:
        targets.append((cfg.app, Path(cfg.outputDir), output_root, True))
    applications_root = Path(cfg.outputDir) / "applications"
    if scope in {"split", "both"} and applications_root.exists():
        for child in sorted(applications_root.iterdir()):
            if child.is_dir() and (child / "graph.json").exists():
                targets.append((child.name, child, output_root / "applications" / child.name, False))
    return targets


def generate_migration_plan(cfg: Config) -> None:
    targets = _pack_targets(cfg)
    if not targets:
        raise FileNotFoundError(
            f"No migration-plan inputs were found under {cfg.outputDir}. Run graph first, and run split if you want per-application packs."
        )

    for pack_name, base_dir, pack_dir, is_root in targets:
        graph, inventory, unresolved, policy_rows, rbac_rows = _load_pack_inputs(base_dir)
        slice_manifest = _load_slice_manifest(base_dir)
        summary = _build_pack_summary(pack_name, graph, inventory, unresolved, policy_rows, rbac_rows, slice_manifest)
        pack_dir.mkdir(parents=True, exist_ok=True)

        _write_markdown(pack_dir / "migration-plan.md", _render_migration_plan(cfg, summary, is_root))
        _write_markdown(pack_dir / "migration-questionnaire.md", _render_questionnaire(summary))
        _write_markdown(pack_dir / "migration-decisions.md", _render_decisions(summary))
        _write_markdown(pack_dir / "decision-trees.md", _render_decision_trees(summary))
        _write_markdown(pack_dir / "wave-plan.md", _render_wave_plan(summary, is_root))
        _write_markdown(pack_dir / "stakeholder-pack.md", _render_stakeholder_pack(summary))
        _write_markdown(pack_dir / "technical-gaps.md", _render_technical_gaps(summary))
        if cfg.migrationPlan.includeCopilotPrompts:
            _write_markdown(pack_dir / "copilot-prompts.md", _render_copilot_prompts(summary))

        (pack_dir / "migration-plan.json").write_text(json.dumps(summary, indent=2, sort_keys=True))


def migration_plan_exists(cfg: Config) -> bool:
    return (_migration_output_root(cfg) / "migration-plan.md").exists()
