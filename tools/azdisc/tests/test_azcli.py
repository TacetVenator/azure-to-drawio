"""Tests for the shared Azure CLI JSON helper."""
from __future__ import annotations

import pytest

from tools.azdisc.azcli import run_az_json


class _Result:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_az_json_returns_parsed_json(monkeypatch):
    monkeypatch.setattr(
        "tools.azdisc.azcli.subprocess.run",
        lambda *args, **kwargs: _Result(returncode=0, stdout='{"ok": true}'),
    )

    assert run_az_json(["account", "show"], expected_type=dict) == {"ok": True}


def test_run_az_json_raises_on_non_zero_exit(monkeypatch):
    monkeypatch.setattr(
        "tools.azdisc.azcli.subprocess.run",
        lambda *args, **kwargs: _Result(returncode=1, stderr="permission denied"),
    )

    with pytest.raises(RuntimeError, match="permission denied"):
        run_az_json(["account", "show"])


def test_run_az_json_rejects_empty_stdout(monkeypatch):
    monkeypatch.setattr(
        "tools.azdisc.azcli.subprocess.run",
        lambda *args, **kwargs: _Result(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="empty stdout"):
        run_az_json(["account", "show"])


def test_run_az_json_surfaces_json_shape_mismatch(monkeypatch):
    monkeypatch.setattr(
        "tools.azdisc.azcli.subprocess.run",
        lambda *args, **kwargs: _Result(returncode=0, stdout="[]"),
    )

    with pytest.raises(RuntimeError, match="expected dict, got list"):
        run_az_json(["account", "show"], expected_type=dict)


def test_run_az_json_surfaces_invalid_json_context(monkeypatch):
    monkeypatch.setattr(
        "tools.azdisc.azcli.subprocess.run",
        lambda *args, **kwargs: _Result(returncode=0, stdout="{bad json"),
    )

    with pytest.raises(RuntimeError, match="invalid JSON"):
        run_az_json(["account", "show"], context="Azure CLI JSON output")
