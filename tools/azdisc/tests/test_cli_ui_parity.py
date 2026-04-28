"""Parity tests for core artifacts between CLI-style and UI-style execution."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.pipeline import build_pipeline_stages
from tools.azdisc_ui.services.pipeline_executor import PipelineExecutor


FIXTURES = Path(__file__).parent / "fixtures"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _config(tmp_path: Path) -> Config:
    return Config(
        app="parity-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )


def test_cli_and_ui_execution_match_for_core_artifacts(monkeypatch, tmp_path: Path) -> None:
    fixture_inventory = json.loads((FIXTURES / "app_contoso.json").read_text(encoding="utf-8"))
    seed_subset = fixture_inventory[:8]

    def fake_run_seed(cfg: Config) -> None:
        cfg.out("seed.json").write_text(json.dumps(seed_subset, indent=2, sort_keys=True), encoding="utf-8")

    def fake_run_expand(
        cfg: Config,
        *,
        software_inventory_workspace=None,
        software_inventory_days=30,
    ) -> None:
        del software_inventory_workspace, software_inventory_days
        cfg.out("inventory.json").write_text(json.dumps(fixture_inventory, indent=2, sort_keys=True), encoding="utf-8")
        cfg.out("unresolved.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr("tools.azdisc.pipeline.run_seed", fake_run_seed)
    monkeypatch.setattr("tools.azdisc.pipeline.run_expand", fake_run_expand)
    monkeypatch.setattr("tools.azdisc.pipeline.generate_docs", lambda cfg: None)
    monkeypatch.setattr("tools.azdisc.pipeline.generate_vm_report_packs", lambda cfg: None)
    monkeypatch.setattr("tools.azdisc.pipeline.generate_master_report", lambda cfg: None)

    cli_dir = tmp_path / "cli"
    ui_dir = tmp_path / "ui"
    cli_dir.mkdir(parents=True, exist_ok=True)
    ui_dir.mkdir(parents=True, exist_ok=True)
    cli_cfg = _config(cli_dir)
    ui_cfg = _config(ui_dir)

    for stage in build_pipeline_stages(cli_cfg):
        stage.action()

    ui_result = asyncio.run(PipelineExecutor().execute_full_pipeline(ui_cfg, continue_on_error=False))
    assert ui_result["status"] == "success"

    for artifact in ["seed.json", "inventory.json", "graph.json", "diagram.drawio"]:
        assert _hash_file(cli_dir / artifact) == _hash_file(ui_dir / artifact), f"Artifact mismatch: {artifact}"
