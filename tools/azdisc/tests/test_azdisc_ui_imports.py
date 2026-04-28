"""Tests for Web UI artifact import and preview behavior."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc_ui.services.artifact_importer import import_artifacts
from tools.azdisc_ui.services.json_preview import preview_json_artifact
from tools.azdisc_ui.services.pipeline_runner import PipelineRunner


def test_import_artifacts_registers_imported_run_and_supports_preview(tmp_path: Path) -> None:
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(
        json.dumps(
            [
                {"id": "/subscriptions/sub-1/resourceGroups/rg-a/providers/Microsoft.Web/sites/app-a", "name": "app-a"},
                {"id": "/subscriptions/sub-1/resourceGroups/rg-a/providers/Microsoft.Sql/servers/sql-a", "name": "sql-a"},
            ]
        ),
        encoding="utf-8",
    )
    run_id = "import123"
    output_dir = tmp_path / run_id

    imported = import_artifacts(
        output_dir=output_dir,
        sources=[{"artifactType": "seed", "path": str(seed_path)}],
    )
    assert len(imported) == 1
    assert imported[0].target_name == "seed.json"

    preview_payload = preview_json_artifact(output_dir / "seed.json", sample_limit=1)
    assert preview_payload["topLevelType"] == "array"
    assert preview_payload["totalItems"] == 2
    assert preview_payload["sampleCount"] == 1
    assert preview_payload["truncated"] is True

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="imported-demo",
        subscriptions=[],
        seedResourceGroups=[],
        outputDir=str(output_dir),
    )
    job = runner.register_imported_run(
        run_id,
        cfg,
        imported_artifacts=[item.target_name for item in imported],
    )
    assert job["status"] == "completed"
    assert job["source_mode"] == "imported"
    assert set(job["imported_artifacts"]) == {"seed.json"}
    assert runner.get_job(run_id) is not None


def test_import_artifacts_rejects_unsupported_artifact_type(tmp_path: Path) -> None:
    source_path = tmp_path / "graph.json"
    source_path.write_text("[]", encoding="utf-8")

    try:
        import_artifacts(
            output_dir=tmp_path / "out",
            sources=[{"artifactType": "graph", "path": str(source_path)}],
        )
    except ValueError as exc:
        assert "Unsupported artifactType" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsupported artifact type")