"""Tests for CLI command registration and parser behavior."""
from __future__ import annotations

from tools.azdisc.__main__ import _iter_command_specs, build_parser


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
