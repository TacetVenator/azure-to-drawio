"""Regression tests for the optional azdisc_ui FastAPI app."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
testclient = pytest.importorskip("fastapi.testclient")

from tools.azdisc_ui.__main__ import create_app
from tools.azdisc.config import Config
from tools.azdisc_ui.services import pipeline_runner as pipeline_runner_module
from tools.azdisc_ui.services.pipeline_runner import PipelineRunner


def test_ui_index_renders_html_response() -> None:
    """The index route should render successfully across Starlette versions."""
    client = testclient.TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Azure Discovery Web UI" in response.text


def test_artifact_preview_json_endpoint_returns_structured_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "preview-json-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "seed.json").write_text(
        json.dumps([
            {"id": "1", "name": "resource-a"},
            {"id": "2", "name": "resource-b"},
        ]),
        encoding="utf-8",
    )

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="preview-json",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["seed.json"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.get(f"/api/artifacts/preview/{run_id}/seed.json?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "json"
    assert payload["topLevelType"] == "array"
    assert payload["sampleCount"] == 1


def test_artifact_preview_drawio_endpoint_returns_xml_snippet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "preview-drawio-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    drawio_text = """<mxfile><diagram id=\"d1\" name=\"Page-1\"><mxGraphModel><root><mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/></root></mxGraphModel></diagram></mxfile>"""
    (output_dir / "diagram.drawio").write_text(drawio_text, encoding="utf-8")

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="preview-drawio",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["diagram.drawio"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.get(f"/api/artifacts/preview/{run_id}/diagram.drawio?limit=50")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "xml"
    assert payload["lineCount"] >= 1
    assert "mxfile" in payload["previewText"]


def test_artifact_preview_rejects_unsupported_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "preview-unsupported-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "notes.txt").write_text("hello", encoding="utf-8")

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="preview-unsupported",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["notes.txt"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.get(f"/api/artifacts/preview/{run_id}/notes.txt?limit=50")

    assert response.status_code == 400
    assert "Preview is supported" in response.json()["detail"]


def test_config_presets_endpoint_lists_scoped_presets() -> None:
    client = testclient.TestClient(create_app())

    response = client.get("/api/config/presets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 2
    names = {item["name"] for item in payload["presets"]}
    assert "rg-scoped" in names
    assert "single-vm-deterministic-min-noise" in names

    vm_preset = next(item for item in payload["presets"] if item["name"] == "single-vm-deterministic-min-noise")
    assert vm_preset["config"]["diagramFocus"]["networkScope"] == "immediate-vm-network"
