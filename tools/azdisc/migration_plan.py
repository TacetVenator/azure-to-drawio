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
) -> Dict[str, Any]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    return {
        "pack": pack_name,
        "resources": len(inventory) or len(nodes),
        "graphNodes": len(nodes),
        "graphEdges": len(edges),
        "subscriptions": sorted({node.get("subscriptionId") for node in nodes if node.get("subscriptionId")}),
        "resourceGroups": sorted({node.get("resourceGroup") for node in nodes if node.get("resourceGroup")}),
        "unresolved": len(unresolved),
        "publicIndicators": _public_indicators(nodes),
        "privateEndpointCount": _private_endpoint_count(nodes),
        "policySummary": dict(_policy_summary(policy_rows)),
        "rbacAssignments": len(rbac_rows),
        "topTypes": _top_resource_types(inventory),
        "sharedTargets": _shared_targets(nodes, edges),
        "hasTelemetry": bool(graph.get("telemetryEdges")),
        "telemetryEdges": len(graph.get("telemetryEdges") or []),
        "externalNodes": sum(1 for node in nodes if node.get("isExternal")),
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
    return lines


def _render_questionnaire(summary: Dict[str, Any]) -> List[str]:
    return [
        f"# Migration Questionnaire — {summary['pack']}",
        "",
        "## Business And Ownership",
        "- What business capability does this pack support?",
        "- Who approves downtime, rollback, and target-state design?",
        "- What are the RTO/RPO expectations?",
        "",
        "## Application And Runtime",
        "- Which components are stateful vs stateless?",
        "- What hidden dependencies are not represented in Azure resources?",
        "- Which cutover pattern is acceptable: big bang, blue/green, phased, or coexistence?",
        "",
        "## Identity, Network, And Data",
        "- Which identities, certificates, and secrets must be recreated or reconnected?",
        "- Which private endpoints, DNS zones, routes, and firewalls are required in the target landing zone?",
        "- Which data stores require replication, seeding, or sync?",
        "",
        "## Operations And Compliance",
        "- Which monitoring, alerting, backup, and DR controls are mandatory before go-live?",
        "- Which policy violations can be remediated before migration and which require exceptions?",
    ]


def _render_decisions(summary: Dict[str, Any]) -> List[str]:
    return [
        f"# Migration Decisions — {summary['pack']}",
        "",
        "| decision | status | owner | due date | evidence | notes |",
        "|----------|--------|-------|----------|----------|-------|",
        "| Target landing-zone placement confirmed | Open | TBD | TBD | graph, policy, shared dependencies | |",
        "| Identity model confirmed | Open | TBD | TBD | RBAC and application runtime inputs | |",
        "| Networking and DNS pattern confirmed | Open | TBD | TBD | topology, private endpoints, shared services | |",
        "| Cutover and rollback strategy approved | Open | TBD | TBD | wave plan and business input | |",
    ]


def _render_decision_trees(summary: Dict[str, Any]) -> List[str]:
    return [
        f"# Decision Trees — {summary['pack']}",
        "",
        "## Migration Pattern",
        "- Is the workload tightly coupled to shared services? If yes, plan shared-service prerequisites before app migration.",
        "- Is data synchronization required? If yes, favor phased or blue/green cutover over big bang.",
        "",
        "## Landing-Zone Readiness",
        "- Are mandatory network, identity, and observability controls available in the target? If no, stop and complete foundation work first.",
        "- Are compliance violations unresolved? If yes, document remediation or exception path before wave execution.",
    ]


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
        summary = _build_pack_summary(pack_name, graph, inventory, unresolved, policy_rows, rbac_rows)
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
