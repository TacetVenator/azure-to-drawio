"""Master architecture report generator for migration/architecture review.

Generates a Markdown report consolidating all discovery outputs:
- inventory.csv, inventory.yaml
- diagram.drawio
- catalog.md, edges.md, routing.md, migration.md
- rbac.json
- policy.json
- unresolved.json
- optional migration planning pack

Each section links to the relevant file, with explanations.
"""
from datetime import date
from pathlib import Path

from .config import Config
from .migration_plan import migration_plan_exists


def generate_master_report(cfg: Config) -> None:
    output_dir = Path(cfg.outputDir)
    today = date.today().isoformat()
    report_path = output_dir / "master_report.md"

    lines = [
        f"# Architecture Master Report — {cfg.app}",
        f"_Generated: {today}_",
        "",
        "---",
        "",
        "## Inventory",
        "Inventory of discovered Azure resources.",
        "- [inventory.csv](inventory.csv): Tabular resource listing.",
        "- [inventory.yaml](inventory.yaml): Grouped resource listing.",
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
        "- [rbac.json](rbac.json): Role assignments.",
        "- [policy.json](policy.json): Azure Policy state records tied to discovered resources.",
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
