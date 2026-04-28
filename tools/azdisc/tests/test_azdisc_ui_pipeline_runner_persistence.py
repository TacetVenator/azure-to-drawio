"""Tests for persisted run metadata and recovery behavior."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc_ui.services.pipeline_runner import PipelineRunner


def _valid_config(output_dir: str) -> dict:
    return {
        "app": "persisted-app",
        "subscriptions": ["sub1"],
        "seedResourceGroups": ["rg-app"],
        "outputDir": output_dir,
    }


def test_runner_persists_imported_run_and_recovers_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output_dir = tmp_path / "run-a"
    output_dir.mkdir(parents=True, exist_ok=True)

    state_runner = PipelineRunner()

    run_cfg = Config(
        app="imported-app",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    state_runner.register_imported_run("run-1", run_cfg, imported_artifacts=["seed.json"])

    recovered = PipelineRunner()
    job = recovered.get_job("run-1")

    assert job is not None
    assert job["source_mode"] == "imported"
    assert job["status"] == "completed"
    assert job["imported_artifacts"] == ["seed.json"]
    assert job["auth_mode_effective"] == "cli"


def test_runner_marks_inflight_runs_as_failed_on_recovery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    state_file = tmp_path / ".azdisc_ui_runs" / "runner-state" / "jobs.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "run-b"
    output_dir.mkdir(parents=True, exist_ok=True)

    state_payload = {
        "jobs": [
            {
                "id": "run-inflight",
                "status": "running",
                "config": _valid_config(str(output_dir)),
                "created_at": "2026-01-01T00:00:00",
                "completed_at": None,
                "error": None,
                "output_dir": str(output_dir),
                "stages": [{"name": "seed", "status": "running"}],
                "continue_on_error": False,
                "source_mode": "pipeline",
                "imported_artifacts": [],
                "auth_mode_requested": "auto",
                "auth_mode_effective": "cli",
                "allow_authorization_fallback": False,
                "fallback_triggered": True,
                "fallback_reason": "Token unavailable at run start",
                "fallback_stage": "pipeline-start",
            }
        ]
    }
    state_file.write_text(json.dumps(state_payload), encoding="utf-8")

    recovered = PipelineRunner()
    job = recovered.get_job("run-inflight")

    assert job is not None
    assert job["status"] == "failed"
    assert "Recovered after process restart" in str(job["error"])
    assert job["fallback_triggered"] is True
    assert job["fallback_stage"] == "pipeline-start"
