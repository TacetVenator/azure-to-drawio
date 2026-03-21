"""Master architecture report generator for migration/architecture review.

Generates a Markdown report consolidating all discovery outputs:
- inventory.csv, inventory.yaml
- diagram.drawio
- catalog.md, edges.md, routing.md, migration.md
- rbac.json
- unresolved.json

Each section links to or embeds the relevant file, with explanations.
"""
from pathlib import Path
from datetime import date

from .config import Config

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
        "## RBAC & Access Control",
        "Role assignments and access control for discovered resources.",
        "- [rbac.json](rbac.json): Role assignments.",
        "",
        "---",
        "",
        "## Unresolved References",
        "Resources referenced but not resolved during discovery.",
        "- [unresolved.json](unresolved.json)",
        "",
    ]

    report_path.write_text("\n".join(lines))
    print(f"Master report written to {report_path}")
