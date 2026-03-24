"""Tests for the interactive wizard."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.wizard import run_wizard


def _input_fn(answers):
    iterator = iter(answers)
    return lambda _prompt: next(iterator)


def test_run_wizard_writes_full_subscription_config_and_instructions(tmp_path):
    config_path = tmp_path / "wizard.json"
    answers = [
        "landing-zone",
        "sub1, sub2",
        str(tmp_path / "out"),
        "f",
        "s",
        "",
        "",
        "n",
        "",
        "",
        "",
        "",
        "",
        "",
        "y",
        "",
        "n",
    ]
    echoed = []

    result = run_wizard(
        str(config_path),
        input_fn=_input_fn(answers),
        echo=echoed.append,
        execute_fn=lambda action, path: None,
    )

    cfg = json.loads(config_path.read_text())
    assert cfg["seedEntireSubscriptions"] is True
    assert cfg["applicationSplit"]["enabled"] is True
    assert cfg["migrationPlan"]["enabled"] is True
    assert result["actions"] == ["run", "report-all", "master-report"]

    instructions = Path(result["instructionsPath"]).read_text()
    assert "python3 -m tools.azdisc run" in instructions
    assert "python3 -m tools.azdisc report-all" in instructions
    assert "python3 -m tools.azdisc master-report" in instructions
    assert "migration-plan/" in instructions


def test_run_wizard_can_execute_selected_actions(tmp_path):
    config_path = tmp_path / "wizard.json"
    answers = [
        "checkout",
        "sub1",
        str(tmp_path / "out"),
        "d",
        "r",
        "rg-app",
        "n",
        "n",
        "n",
        "n",
        "n",
        "n",
        "n",
        "y",
    ]
    executed = []

    result = run_wizard(
        str(config_path),
        input_fn=_input_fn(answers),
        echo=lambda _msg: None,
        execute_fn=lambda action, path: executed.append((action, path)),
    )

    assert result["executed"] is True
    assert executed == [("run", str(config_path))]
    cfg = json.loads(config_path.read_text())
    assert cfg["seedResourceGroups"] == ["rg-app"]
    assert cfg["migrationPlan"]["enabled"] is False
