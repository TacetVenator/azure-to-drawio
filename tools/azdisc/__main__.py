"""CLI entry point for azure-to-drawio tool."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .config import load_config
from .config_presets import get_config_preset, list_config_presets
from .analyze import run_analysis
from .discover import prepare_related_extended_inventory, run_expand, run_policy, run_rbac, run_related_candidates, run_seed
from .docs import generate_docs
from .drawio import generate_drawio
from .graph import build_graph
from .htmlmap import generate_html
from .insights import generate_vm_details_csv, run_advisor, run_quota
from .inventory import generate_csv, generate_inventory_by_type_csv, generate_policy_csv, generate_policy_yaml, generate_yaml
from .master_report import generate_master_report
from .review import run_review_related
from .registry import refresh_registry
from .migration_plan import generate_migration_plan
from .pipeline import build_pipeline_stages
from .split import build_split_preview, run_split
from .telemetry import run_telemetry_enrichment
from .test_all import run_render_all, run_report_all, run_test_all
from .util import setup_logging
from .wizard import run_wizard
from .vm_report import generate_vm_report_packs

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: Callable[[argparse.Namespace], None]
    help_text: str
    needs_config: bool = True
    supports_software_inventory: bool = False
    supports_html_options: bool = False


def _run_with_config(action: Callable[..., None], /, **extra_kwargs) -> Callable[[argparse.Namespace], None]:
    def _handler(args: argparse.Namespace) -> None:
        cfg = load_config(args.config)
        action(cfg, **extra_kwargs)

    return _handler


def cmd_split_preview(args) -> None:
    cfg = load_config(args.config)
    print(build_split_preview(cfg), end="")


def cmd_expand(args) -> None:
    cfg = load_config(args.config)
    run_expand(
        cfg,
        software_inventory_workspace=args.software_inventory_csv,
        software_inventory_days=args.software_inventory_days,
    )


def cmd_related_extend(args) -> None:
    cfg = load_config(args.config)
    extended_cfg = prepare_related_extended_inventory(cfg)
    run_expand(extended_cfg)
    if extended_cfg.includeRbac:
        run_rbac(extended_cfg)
    if extended_cfg.includePolicy:
        run_policy(extended_cfg)
    build_graph(extended_cfg)
    if extended_cfg.enableTelemetry:
        run_telemetry_enrichment(extended_cfg)
    generate_drawio(extended_cfg)
    generate_docs(extended_cfg)
    log.info("Extended related-resource pack complete for app=%s at %s", extended_cfg.app, extended_cfg.outputDir)


def cmd_html(args) -> None:
    cfg = load_config(args.config)
    generate_html(cfg, artifact=args.artifact, view=args.view)


def cmd_test_all(args) -> None:
    run_test_all(args.output)


def cmd_wizard(args) -> None:
    run_wizard(args.config)


def cmd_analyze(args) -> None:
    cfg = load_config(args.config)
    run_analysis(
        cfg,
        stage=args.stage,
        intent_name=args.intent,
        pack_name=args.pack,
        rebuild_index=args.rebuild_index,
        model_override=args.model,
    )


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    for stage in build_pipeline_stages(
        cfg,
        software_inventory_workspace=args.software_inventory_csv,
        software_inventory_days=args.software_inventory_days,
    ):
        stage.action()
    log.info("Pipeline complete for app=%s", cfg.app)


def cmd_registry_refresh(args) -> None:
    assets_dir = Path(args.assets_dir).expanduser().resolve()
    subs = [s.strip() for s in (args.subscriptions or "").split(",") if s.strip()]
    summary = refresh_registry(
        assets_dir=assets_dir,
        subscription_ids=subs or None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_config_presets(args) -> None:
    if args.name:
        payload = get_config_preset(args.name)
    else:
        payload = {"presets": list_config_presets(include_config=not args.names_only)}

    serialized = json.dumps(payload, indent=2, sort_keys=True)
    if args.write:
        out = Path(args.write).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(serialized + "\n", encoding="utf-8")
        print(str(out))
        return
    print(serialized)


def _iter_command_specs() -> Iterable[CommandSpec]:
    return [
        CommandSpec("run", cmd_run, "Run the full pipeline", supports_software_inventory=True),
        CommandSpec("telemetry", _run_with_config(run_telemetry_enrichment), "Enrich graph with App Insights, Activity Log, and Flow Log telemetry"),
        CommandSpec("seed", _run_with_config(run_seed), "Seed resources from RGs"),
        CommandSpec("expand", cmd_expand, "Expand resources transitively", supports_software_inventory=True),
        CommandSpec("related-candidates", _run_with_config(run_related_candidates), "Find possible related resources by configured name substrings"),
        CommandSpec("review-related", _run_with_config(run_review_related), "Interactively review and curate related-resource candidates"),
        CommandSpec("related-extend", cmd_related_extend, "Generate an extended pack from curated related resources in a dedicated directory"),
        CommandSpec("rbac", _run_with_config(run_rbac), "Collect RBAC assignments for discovered resources"),
        CommandSpec("policy", _run_with_config(run_policy), "Collect Azure Policy state for discovered resources"),
        CommandSpec("graph", _run_with_config(build_graph), "Build graph model"),
        CommandSpec("drawio", _run_with_config(generate_drawio), "Generate draw.io diagram"),
        CommandSpec("html", cmd_html, "Generate offline HTML mindmap", supports_html_options=True),
        CommandSpec("docs", _run_with_config(generate_docs), "Generate documentation"),
        CommandSpec("split-preview", cmd_split_preview, "Preview application split candidates from seed/inventory artifacts"),
        CommandSpec("split", _run_with_config(run_split), "Generate per-application outputs from an existing inventory/graph"),
        CommandSpec("migration-plan", _run_with_config(generate_migration_plan), "Generate migration planning packs from existing discovery artifacts"),
        CommandSpec("analyze", cmd_analyze, "Run consultant-style local analysis with Ollama"),
        CommandSpec("wizard", cmd_wizard, "Interactively create config, instructions, and optionally execute the workflow"),
        CommandSpec("inventory-csv", _run_with_config(generate_csv), "Generate inventory.csv from inventory.json"),
        CommandSpec("inventory-yaml", _run_with_config(generate_yaml), "Generate inventory.yaml from inventory.json"),
        CommandSpec("inventory-by-type", _run_with_config(generate_inventory_by_type_csv), "Generate per-type inventory CSV exports"),
        CommandSpec("policy-csv", _run_with_config(generate_policy_csv), "Generate policy.csv from policy.json"),
        CommandSpec("policy-yaml", _run_with_config(generate_policy_yaml), "Generate policy.yaml from policy.json"),
        CommandSpec("advisor", _run_with_config(run_advisor), "Collect Azure Advisor recommendations for discovered resources"),
        CommandSpec("quota", _run_with_config(run_quota), "Collect regional compute/network quota snapshots"),
        CommandSpec("vm-details", _run_with_config(generate_vm_details_csv), "Generate vm_details.csv from inventory.json"),
        CommandSpec("vm-report", _run_with_config(generate_vm_report_packs), "Generate focused per-VM report packs from existing artifacts"),
        CommandSpec("render-all", _run_with_config(run_render_all), "Generate all layout x mode variants from an existing graph"),
        CommandSpec("report-all", _run_with_config(run_report_all), "Generate a Markdown report of all layout x mode x spacing variants"),
        CommandSpec("master-report", _run_with_config(generate_master_report), "Generate a consolidated master architecture report"),
        CommandSpec("config-presets", cmd_config_presets, "List built-in scoped config presets or export one", needs_config=False),
        CommandSpec("registry-refresh", cmd_registry_refresh, "Refresh assets/azure_type_registry.json from icon map + ARG type inventory", needs_config=False),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.azdisc",
        description="Azure Resource Graph -> draw.io diagram tool",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    for spec in _iter_command_specs():
        p = sub.add_parser(spec.name, help=spec.help_text)
        if spec.needs_config:
            p.add_argument("config", help="Path to config.json")
        if spec.supports_software_inventory:
            p.add_argument(
                "--software-inventory-csv",
                metavar="WORKSPACE",
                help="Log Analytics workspace ID/name to query Change Tracking and Inventory software data and write software_inventory.csv",
            )
            p.add_argument(
                "--software-inventory-days",
                type=int,
                default=30,
                help="Lookback window in days for software inventory queries (default: 30)",
            )
        if spec.supports_html_options:
            p.add_argument("--artifact", choices=["graph", "related-candidates", "related-promoted", "rbac", "policy"], default="graph", help="Artifact to render as HTML (default: graph)")
            p.add_argument("--view", choices=["topology", "organization", "resources"], default="topology", help="Graph view mode when artifact=graph (default: topology)")
        if spec.name == "analyze":
            p.add_argument("--stage", choices=["extract-evidence", "index", "analyze-intents", "synthesize", "review"], help="Stop after the selected analysis stage")
            p.add_argument("--intent", help="Run only one named analysis intent")
            p.add_argument("--pack", help="Analyze only one pack slug such as root or an application name")
            p.add_argument("--rebuild-index", action="store_true", help="Rebuild the local chunk index before analysis")
            p.add_argument("--model", help="Override the configured localAnalysis.model for this run")
        if spec.name == "registry-refresh":
            default_assets = Path(__file__).parent.parent.parent / "assets"
            p.add_argument(
                "--assets-dir",
                default=str(default_assets),
                help="Path to assets directory containing azure_icon_map.json",
            )
            p.add_argument(
                "--subscriptions",
                help="Comma-separated subscription IDs for ARG discovery (optional)",
            )
        if spec.name == "config-presets":
            p.add_argument("--name", help="Return one preset by name")
            p.add_argument("--names-only", action="store_true", help="Return metadata without embedded config payloads")
            p.add_argument("--write", help="Write JSON output to this path")
        p.set_defaults(func=spec.handler)

    p_test_all = sub.add_parser("test-all", help="Generate all layout x mode combinations from fixtures")
    p_test_all.add_argument(
        "-o", "--output", default="out/test-all",
        help="Root output directory (default: out/test-all)",
    )
    p_test_all.set_defaults(func=cmd_test_all)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    try:
        args.func(args)
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
