"""Tests for CLI command registration and parser behavior."""
from __future__ import annotations

import argparse

from tools.azdisc import __main__ as cli
from tools.azdisc.__main__ import _iter_command_specs, build_parser
from tools.azdisc.config import Config


def test_build_parser_keeps_test_all_without_config():
    parser = build_parser()
    args = parser.parse_args(["test-all", "--output", "out/test-all"])
    assert args.output == "out/test-all"
    assert not hasattr(args, "config")


def test_command_specs_include_expected_handlers():
    specs = {spec.name: spec for spec in _iter_command_specs()}

    assert specs["run"].supports_software_inventory is True
    assert specs["html"].supports_html_options is True
    assert specs["wizard"].needs_config is True
    assert "analyze" in specs


def test_analyze_parser_supports_stage_and_intent_flags():
    parser = build_parser()
    args = parser.parse_args(["analyze", "app/myapp/config.json", "--stage", "index", "--intent", "estate-summary", "--pack", "root", "--rebuild-index", "--model", "gemma4"] )
    assert args.stage == "index"
    assert args.intent == "estate-summary"
    assert args.pack == "root"
    assert args.rebuild_index is True
    assert args.model == "gemma4"

def test_run_generates_master_report_after_optional_outputs(monkeypatch, tmp_path):
    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.applicationSplit.enabled = True
    cfg.migrationPlan.enabled = True
    calls = []

    monkeypatch.setattr(cli, "load_config", lambda _path: cfg)
    for name in (
        "run_seed",
        "run_expand",
        "run_rbac",
        "run_policy",
        "build_graph",
        "generate_drawio",
        "generate_vm_report_packs",
        "generate_docs",
        "run_split",
        "generate_migration_plan",
        "generate_master_report",
    ):
        monkeypatch.setattr(cli, name, lambda *args, _name=name, **kwargs: calls.append(_name))

    cli.cmd_run(argparse.Namespace(
        config="config.json",
        software_inventory_csv=None,
        software_inventory_days=30,
    ))

    assert calls[-3:] == ["run_split", "generate_migration_plan", "generate_master_report"]
