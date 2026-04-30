"""Tests for CLI command registration and parser behavior."""
from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

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
    assert specs["config-presets"].needs_config is False
    assert "analyze" in specs
    assert "vm-quick" in specs


def test_analyze_parser_supports_stage_and_intent_flags():
    parser = build_parser()
    args = parser.parse_args(["analyze", "app/myapp/config.json", "--stage", "index", "--intent", "estate-summary", "--pack", "root", "--rebuild-index", "--model", "gemma4"] )
    assert args.stage == "index"
    assert args.intent == "estate-summary"
    assert args.pack == "root"
    assert args.rebuild_index is True
    assert args.model == "gemma4"


def test_vm_quick_parser_supports_vm_resource_id_flags():
    parser = build_parser()
    args = parser.parse_args([
        "vm-quick",
        "app/myapp/config.json",
        "--vm-resource-id",
        "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a",
        "--relationship-depth",
        "2",
        "--output-dir",
        "out/vm-a",
    ])
    assert args.vm_resource_id.endswith("/virtualMachines/vm-a")
    assert args.relationship_depth == 2
    assert args.output_dir == "out/vm-a"

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
    monkeypatch.setattr(
        cli,
        "build_pipeline_stages",
        lambda *_args, **_kwargs: [
            SimpleNamespace(action=lambda _name=name: calls.append(_name))
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
            )
        ],
    )

    cli.cmd_run(argparse.Namespace(
        config="config.json",
        software_inventory_csv=None,
        software_inventory_days=30,
    ))

    assert calls[-3:] == ["run_split", "generate_migration_plan", "generate_master_report"]


def test_config_presets_parser_supports_name_and_write_flags(tmp_path):
    parser = build_parser()
    out = tmp_path / "preset.json"
    args = parser.parse_args(["config-presets", "--name", "rg-scoped", "--write", str(out)])
    assert args.name == "rg-scoped"
    assert args.write == str(out)


def test_cmd_config_presets_writes_named_preset_json(tmp_path):
    out = tmp_path / "preset.json"
    cli.cmd_config_presets(argparse.Namespace(name="single-vm-deterministic-min-noise", names_only=False, write=str(out)))

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["name"] == "single-vm-deterministic-min-noise"
    assert payload["config"]["expandScope"] == "related"
    assert payload["config"]["diagramFocus"]["networkScope"] == "immediate-vm-network"
