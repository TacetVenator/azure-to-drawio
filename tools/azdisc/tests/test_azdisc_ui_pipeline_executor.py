"""Tests for Web UI pipeline executor behavior."""
from __future__ import annotations

import asyncio
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.pipeline import PipelineStage
from tools.azdisc_ui.services.pipeline_executor import PipelineExecutor


def _make_config(tmp_path: Path) -> Config:
    return Config(
        app="executor-test",
        subscriptions=["sub-1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )


def test_pipeline_executor_fails_fast_when_continue_on_error_disabled(monkeypatch, tmp_path: Path) -> None:
    executor = PipelineExecutor()
    config = _make_config(tmp_path)
    calls: list[str] = []

    def stage_one() -> None:
        calls.append("seed")

    def stage_two() -> None:
        calls.append("expand")
        raise RuntimeError("boom")

    def stage_three() -> None:
        calls.append("graph")

    monkeypatch.setattr(
        "tools.azdisc_ui.services.pipeline_executor.build_pipeline_stages",
        lambda cfg: [
            PipelineStage("seed", stage_one),
            PipelineStage("expand", stage_two),
            PipelineStage("graph", stage_three),
        ],
    )

    result = asyncio.run(executor.execute_full_pipeline(config, continue_on_error=False))

    assert result["status"] == "failed"
    assert calls == ["seed", "expand"]
    assert [stage["status"] for stage in result["stages"]] == ["completed", "failed"]


def test_pipeline_executor_continues_when_continue_on_error_enabled(monkeypatch, tmp_path: Path) -> None:
    executor = PipelineExecutor()
    config = _make_config(tmp_path)
    calls: list[str] = []

    def stage_one() -> None:
        calls.append("seed")

    def stage_two() -> None:
        calls.append("expand")
        raise RuntimeError("boom")

    def stage_three() -> None:
        calls.append("graph")

    monkeypatch.setattr(
        "tools.azdisc_ui.services.pipeline_executor.build_pipeline_stages",
        lambda cfg: [
            PipelineStage("seed", stage_one),
            PipelineStage("expand", stage_two),
            PipelineStage("graph", stage_three),
        ],
    )

    result = asyncio.run(executor.execute_full_pipeline(config, continue_on_error=True))

    assert result["status"] == "completed-with-errors"
    assert calls == ["seed", "expand", "graph"]
    assert [stage["status"] for stage in result["stages"]] == ["completed", "failed", "completed"]


def test_pipeline_executor_auto_mode_falls_back_to_cli_when_token_missing(monkeypatch, tmp_path: Path) -> None:
    executor = PipelineExecutor()
    config = _make_config(tmp_path)

    monkeypatch.setattr(
        "tools.azdisc_ui.services.pipeline_executor.build_pipeline_stages",
        lambda cfg: [PipelineStage("seed", lambda: None)],
    )

    result = asyncio.run(
        executor.execute_full_pipeline(
            config,
            auth_mode="auto",
            token_available=False,
        )
    )

    assert result["status"] == "success"
    assert result["auth_mode_effective"] == "cli"
    assert result["fallback_triggered"] is True
    assert result["fallback_stage"] == "pipeline-start"


def test_pipeline_executor_token_mode_fails_when_token_missing(tmp_path: Path) -> None:
    executor = PipelineExecutor()
    config = _make_config(tmp_path)

    result = asyncio.run(
        executor.execute_full_pipeline(
            config,
            auth_mode="token",
            token_available=False,
        )
    )

    assert result["status"] == "failed"
    assert "token is not available" in str(result["error"]).lower()


def test_pipeline_executor_switches_to_cli_after_token_auth_failure(monkeypatch, tmp_path: Path) -> None:
    executor = PipelineExecutor()
    config = _make_config(tmp_path)
    calls: list[str] = []

    def stage_one() -> None:
        calls.append("seed")

    def stage_two() -> None:
        calls.append("expand")
        raise RuntimeError("401 unauthorized: token expired")

    def stage_three() -> None:
        calls.append("graph")

    monkeypatch.setattr(
        "tools.azdisc_ui.services.pipeline_executor.build_pipeline_stages",
        lambda cfg: [
            PipelineStage("seed", stage_one),
            PipelineStage("expand", stage_two),
            PipelineStage("graph", stage_three),
        ],
    )

    result = asyncio.run(
        executor.execute_full_pipeline(
            config,
            continue_on_error=False,
            auth_mode="token",
            token_available=True,
            allow_authorization_fallback=False,
        )
    )

    assert result["status"] == "failed"
    assert calls == ["seed", "expand", "graph"]
    assert result["auth_mode_effective"] == "cli"
    assert result["fallback_triggered"] is True
    assert result["fallback_stage"] == "expand"