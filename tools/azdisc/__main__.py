"""CLI entry point for azure-to-drawio tool."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .discover import prepare_related_extended_inventory, run_expand, run_policy, run_rbac, run_related_candidates, run_seed
from .docs import generate_docs
from .drawio import generate_drawio
from .graph import build_graph
from .inventory import generate_csv, generate_yaml
from .master_report import generate_master_report
from .migration_plan import generate_migration_plan
from .split import build_split_preview, run_split
from .telemetry import run_telemetry_enrichment
from .test_all import run_render_all, run_report_all, run_test_all
from .util import setup_logging
from .wizard import run_wizard

log = logging.getLogger(__name__)


def cmd_master_report(args) -> None:
    cfg = load_config(args.config)
    generate_master_report(cfg)


def cmd_split_preview(args) -> None:
    cfg = load_config(args.config)
    print(build_split_preview(cfg), end="")


def cmd_split(args) -> None:
    cfg = load_config(args.config)
    run_split(cfg)


def cmd_seed(args) -> None:
    cfg = load_config(args.config)
    run_seed(cfg)


def cmd_expand(args) -> None:
    cfg = load_config(args.config)
    run_expand(cfg)


def cmd_related_candidates(args) -> None:
    cfg = load_config(args.config)
    run_related_candidates(cfg)


def cmd_related_extend(args) -> None:
    cfg = load_config(args.config)
    extended_cfg = prepare_related_extended_inventory(cfg)
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


def cmd_rbac(args) -> None:
    cfg = load_config(args.config)
    run_rbac(cfg)


def cmd_policy(args) -> None:
    cfg = load_config(args.config)
    run_policy(cfg)


def cmd_graph(args) -> None:
    cfg = load_config(args.config)
    build_graph(cfg)


def cmd_drawio(args) -> None:
    cfg = load_config(args.config)
    generate_drawio(cfg)


def cmd_docs(args) -> None:
    cfg = load_config(args.config)
    generate_docs(cfg)


def cmd_test_all(args) -> None:
    run_test_all(args.output)


def cmd_render_all(args) -> None:
    cfg = load_config(args.config)
    run_render_all(cfg)


def cmd_report_all(args) -> None:
    cfg = load_config(args.config)
    run_report_all(cfg)


def cmd_inventory_csv(args) -> None:
    cfg = load_config(args.config)
    generate_csv(cfg)


def cmd_inventory_yaml(args) -> None:
    cfg = load_config(args.config)
    generate_yaml(cfg)


def cmd_telemetry(args) -> None:
    cfg = load_config(args.config)
    run_telemetry_enrichment(cfg)


def cmd_migration_plan(args) -> None:
    cfg = load_config(args.config)
    generate_migration_plan(cfg)


def cmd_wizard(args) -> None:
    run_wizard(args.config)


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    run_seed(cfg)
    run_expand(cfg)
    run_rbac(cfg)
    run_policy(cfg)
    build_graph(cfg)
    if cfg.enableTelemetry:
        run_telemetry_enrichment(cfg)
    generate_drawio(cfg)
    generate_docs(cfg)
    if cfg.applicationSplit.enabled:
        run_split(cfg)
    if cfg.migrationPlan.enabled:
        generate_migration_plan(cfg)
    log.info("Pipeline complete for app=%s", cfg.app)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.azdisc",
        description="Azure Resource Graph -> draw.io diagram tool",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func, help_text in [
        ("run", cmd_run, "Run the full pipeline"),
        ("telemetry", cmd_telemetry, "Enrich graph with App Insights, Activity Log, and Flow Log telemetry"),
        ("seed", cmd_seed, "Seed resources from RGs"),
        ("expand", cmd_expand, "Expand resources transitively"),
        ("related-candidates", cmd_related_candidates, "Find possible related resources by configured name substrings"),
        ("related-extend", cmd_related_extend, "Generate an extended pack from curated related resources in a dedicated directory"),
        ("rbac", cmd_rbac, "Collect RBAC assignments for discovered resources"),
        ("policy", cmd_policy, "Collect Azure Policy state for discovered resources"),
        ("graph", cmd_graph, "Build graph model"),
        ("drawio", cmd_drawio, "Generate draw.io diagram"),
        ("docs", cmd_docs, "Generate documentation"),
        ("split-preview", cmd_split_preview, "Preview application split candidates from seed/inventory artifacts"),
        ("split", cmd_split, "Generate per-application outputs from an existing inventory/graph"),
        ("migration-plan", cmd_migration_plan, "Generate migration planning packs from existing discovery artifacts"),
        ("wizard", cmd_wizard, "Interactively create config, instructions, and optionally execute the workflow"),
        ("inventory-csv", cmd_inventory_csv, "Generate inventory.csv from inventory.json"),
        ("inventory-yaml", cmd_inventory_yaml, "Generate inventory.yaml from inventory.json"),
        ("render-all", cmd_render_all, "Generate all layout x mode variants from an existing graph"),
        ("report-all", cmd_report_all, "Generate a Markdown report of all layout x mode x spacing variants"),
        ("master-report", cmd_master_report, "Generate a consolidated master architecture report"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("config", help="Path to config.json")
        p.set_defaults(func=func)

    p_test_all = sub.add_parser("test-all", help="Generate all layout x mode combinations from fixtures")
    p_test_all.add_argument(
        "-o", "--output", default="out/test-all",
        help="Root output directory (default: out/test-all)",
    )
    p_test_all.set_defaults(func=cmd_test_all)

    args = parser.parse_args()
    setup_logging(args.verbose)
    try:
        args.func(args)
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
