"""CLI entry point for azure-to-drawio tool."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .discover import run_seed, run_expand, run_rbac
from .drawio import generate_drawio
from .docs import generate_docs
from .graph import build_graph
from .util import setup_logging

log = logging.getLogger(__name__)


def cmd_seed(args) -> None:
    cfg = load_config(args.config)
    run_seed(cfg)


def cmd_expand(args) -> None:
    cfg = load_config(args.config)
    run_expand(cfg)


def cmd_graph(args) -> None:
    cfg = load_config(args.config)
    build_graph(cfg)


def cmd_drawio(args) -> None:
    cfg = load_config(args.config)
    generate_drawio(cfg)


def cmd_docs(args) -> None:
    cfg = load_config(args.config)
    generate_docs(cfg)


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    run_seed(cfg)
    run_expand(cfg)
    run_rbac(cfg)
    build_graph(cfg)
    generate_drawio(cfg)
    generate_docs(cfg)
    log.info("Pipeline complete for app=%s", cfg.app)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.azdisc",
        description="Azure Resource Graph → draw.io diagram tool",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func, help_text in [
        ("run", cmd_run, "Run the full pipeline"),
        ("seed", cmd_seed, "Seed resources from RGs"),
        ("expand", cmd_expand, "Expand resources transitively"),
        ("graph", cmd_graph, "Build graph model"),
        ("drawio", cmd_drawio, "Generate draw.io diagram"),
        ("docs", cmd_docs, "Generate documentation"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("config", help="Path to config.json")
        p.set_defaults(func=func)

    args = parser.parse_args()
    setup_logging(args.verbose)
    try:
        args.func(args)
    except Exception as e:
        log.error("Error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
