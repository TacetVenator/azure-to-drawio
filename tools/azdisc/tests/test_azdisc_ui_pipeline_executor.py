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