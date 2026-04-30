"""Master architecture report generator for migration and governance review."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from .config import Config
from .governance import simplify_rbac_rows, summarize_policy_rows, summarize_resource_access
from .migration_plan import migration_plan_exists
from .util import load_json_file


def _load_optional(path: Path, expected_type: type) -> Any:
    if not path.exists():
        return expected_type()
    return load_json_file(
        path,
        context="Master report artifact",
        expected_type=expected_type,
        advice=f"Fix {path.name} or regenerate the prerequisite artifact before generating the master report.",
    )


def generate_master_report(cfg: Config) -> None:
    output_dir = Path(cfg.outputDir)
    today = date.today().isoformat()
    report_path = output_dir / "master_report.md"

    nodes: List[Dict[str, Any]] = _load_optional(output_dir / "graph.json", dict).get("nodes", []) if (output_dir / "graph.json").exists() else []
    policy_rows: List[Dict[str, Any]] = _load_optional(output_dir / "policy.json", list)
    rbac_rows: List[Dict[str, Any]] = _load_optional(output_dir / "rbac.json", list)
    policy_counts = summarize_policy_rows(policy_rows) if policy_rows else {}
    access_rows = summarize_resource_access(nodes, rbac_rows) if nodes and rbac_rows else []
    simplified_rbac = simplify_rbac_rows(rbac_rows) if rbac_rows else []

    lines = [
        f"# Architecture Master Report — {cfg.app}",
        f"_Generated: {today}_",
        "",
        "---",
        "",
        "## Inventory",
        "Inventory of discovered Azure resources.",
        "- [index.md](index.md): Report landing page.",
        "- [organization.md](organization.md): Subscription and resource-group summary.",
        "- [resource_groups.md](resource_groups.md): Resource-group review output.",
        "- [resource_types.md](resource_types.md): Resource-type review output.",
        "- [inventory.csv](inventory.csv): Tabular resource listing.",
        "- [inventory.yaml](inventory.yaml): Grouped resource listing.",
        "- [inventory_by_type/manifest.json](inventory_by_type/manifest.json): Per-type CSV export manifest.",
        "",
        "---",
        "",
        "## Topology & Diagram",
        "Visual and graph-based representation of the environment.",
        "- [diagram.drawio](diagram.drawio): Draw.io diagram file.",
        "- [catalog.md](catalog.md): Resource catalog summary.",
        "- [edges.md](edges.md): Resource relationships and dependencies.",
        "- [migration.md](migration.md): Migration-oriented exposure and dependency assessment.",
        "",
        "---",
        "",
        "## Routing & Security",
        "Network routing tables and security group details.",
        "- [routing.md](routing.md): Routing, NSG, and ASG details.",
        "",
        "---",
        "",
        "## Access & Compliance",
        "Role assignments and Azure Policy state for discovered resources.",
        "- [rbac.json](rbac.json): Raw role assignments.",
        "- [rbac_summary.md](rbac_summary.md): Human-readable access review summary.",
        "- [policy.json](policy.json): Raw Azure Policy state records tied to discovered resources.",
        "- [policy_summary.md](policy_summary.md): Executive-friendly compliance summary.",
        "",
        "---",
        "",
        "## Advisory & Capacity",
        "Optional ARI-style enrichments generated without external dependencies.",
        "- [advisor.json](advisor.json): Raw Azure Advisor recommendations filtered to discovered resources.",
        "- [advisor_summary.md](advisor_summary.md): Advisor summary for the discovered scope.",
        "- [quota.json](quota.json): Regional compute/network quota snapshots.",
        "- [quota_summary.md](quota_summary.md): Near-limit quota review.",
        "- [vm_details.csv](vm_details.csv): VM-focused detail export.",
        "- [vms/index.md](vms/index.md): Focused per-VM report packs and diagrams.",
        "",
    ]

    if policy_rows:
        other_states = sum(policy_counts.values()) - policy_counts.get("Compliant", 0) - policy_counts.get("NonCompliant", 0) - policy_counts.get("Exempt", 0)
        lines += [
            "### Policy Snapshot",
            "",
            f"- Policy state records: {len(policy_rows)}",
            f"- Compliant: {policy_counts.get('Compliant', 0)}",
            f"- Non-compliant: {policy_counts.get('NonCompliant', 0)}",
            f"- Exempt: {policy_counts.get('Exempt', 0)}",
            f"- Other states: {other_states}",
            "",
        ]
    else:
        lines += [
            "### Policy Snapshot",
            "",
            "- No policy state artifact is available in this output folder.",
            "",
        ]

    if rbac_rows:
        principal_counts: Dict[str, int] = {}
        role_counts: Dict[str, int] = {}
        for row in simplified_rbac:
            principal = row.get("principalName") or "Unknown principal"
            role = row.get("roleName") or "Unknown role"
            principal_counts[principal] = principal_counts.get(principal, 0) + 1
            role_counts[role] = role_counts.get(role, 0) + 1

        top_principals = sorted(principal_counts.items(), key=lambda item: (-item[1], item[0].lower()))[:10]
        top_roles = sorted(role_counts.items(), key=lambda item: (-item[1], item[0].lower()))[:10]

        lines += [
            "### RBAC Snapshot",
            "",
            f"- Role assignments captured: {len(rbac_rows)}",
            f"- Unique principals: {len({row['principalName'] for row in simplified_rbac})}",
            f"- Unique roles: {len({row['roleName'] for row in simplified_rbac})}",
            f"- Resources with effective access captured: {len(access_rows)}",
            "",
        ]
        if top_principals:
            lines += [
                "#### Top Principals (by assignment count)",
                "",
                "| principal | assignments |",
                "|-----------|-------------|",
            ]
            for principal, count in top_principals:
                lines.append(f"| {principal} | {count} |")
            lines.append("")

        if top_roles:
            lines += [
                "#### Top Roles (by assignment count)",
                "",
                "| role | assignments |",
                "|------|-------------|",
            ]
            for role, count in top_roles:
                lines.append(f"| {role} | {count} |")
            lines.append("")

        non_network_access_rows = [
            row for row in access_rows if not str(row.get("resourceType", "")).lower().startswith("microsoft.network/")
        ]
        shown_access_rows = non_network_access_rows if non_network_access_rows else access_rows

        if access_rows:
            lines += [
                "#### Resource Access View",
                "",
                "| resource | resource group | effective assignments | distinct roles | inherited assignments |",
                "|----------|----------------|-----------------------|----------------|-----------------------|",
            ]
            for row in shown_access_rows[:10]:
                lines.append(
                    f"| {row['resourceName']} ({row['resourceType']}) | {row['resourceGroup']} | {row['effectiveAssignments']} | {row['distinctRoles']} | {row['inheritedAssignments']} |"
                )
            lines.append("")
    else:
        lines += [
            "### RBAC Snapshot",
            "",
            "- No RBAC artifact is available in this output folder.",
            "",
        ]

    if migration_plan_exists(cfg):
        copilot_path = output_dir / "migration-plan" / "copilot-prompts.md"
        lines += [
            "---",
            "",
            "## Migration Planning Pack",
            "Action-oriented migration planning artifacts generated from the discovered environment.",
            "- [migration-plan/migration-plan.md](migration-plan/migration-plan.md): Step-by-step migration planning template.",
            "- [migration-plan/migration-questionnaire.md](migration-plan/migration-questionnaire.md): Questions to complete with application, platform, and business stakeholders.",
            "- [migration-plan/migration-decisions.md](migration-plan/migration-decisions.md): Decision and approval register.",
            "- [migration-plan/decision-trees.md](migration-plan/decision-trees.md): Decision guidance for migration choices.",
            "- [migration-plan/wave-plan.md](migration-plan/wave-plan.md): Suggested migration sequencing and validation gates.",
            "- [migration-plan/stakeholder-pack.md](migration-plan/stakeholder-pack.md): Plain-English summary for non-technical stakeholders.",
            "- [migration-plan/technical-gaps.md](migration-plan/technical-gaps.md): Discovery and visualization gaps that are still code-addressable.",
        ]
        if copilot_path.exists():
            lines.append("- [migration-plan/copilot-prompts.md](migration-plan/copilot-prompts.md): Prompt pack for Copilot-assisted review and refinement.")
        lines += ["", "---", ""]
    else:
        lines += ["---", "", "## Unresolved References", "Resources referenced but not resolved during discovery.", "- [unresolved.json](unresolved.json)", ""]

    if migration_plan_exists(cfg):
        lines += [
            "## Unresolved References",
            "Resources referenced but not resolved during discovery.",
            "- [unresolved.json](unresolved.json)",
            "",
        ]

    report_path.write_text("\n".join(lines))
    print(f"Master report written to {report_path}")
