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


def test_config_load_endpoint_round_trips_existing_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "existing-config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "app": "from-file",
                "subscriptions": ["sub-1"],
                "seedResourceGroups": ["rg-a"],
                "outputDir": str(tmp_path / "out"),
            }
        ),
        encoding="utf-8",
    )

    client = testclient.TestClient(create_app())
    response = client.post("/api/config/load", json={"config_path": str(cfg_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["config_path"] == str(cfg_path.resolve())
    assert payload["config"]["app"] == "from-file"
    assert payload["config"]["outputDir"] == str(tmp_path / "out")


def test_config_save_endpoint_writes_normalized_config_file(tmp_path: Path) -> None:
    save_path = tmp_path / "saved" / "config.saved.json"

    client = testclient.TestClient(create_app())
    response = client.post(
        "/api/config/save",
        json={
            "save_path": str(save_path),
            "create_parent": True,
            "config_data": {
                "app": "saved-config",
                "subscriptions": ["sub-1"],
                "seedResourceGroups": ["rg-a"],
                "outputDir": str(tmp_path / "out-saved"),
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["save_path"] == str(save_path.resolve())
    assert save_path.exists()

    saved = json.loads(save_path.read_text(encoding="utf-8"))
    assert saved["app"] == "saved-config"
    assert saved["outputDir"] == str(tmp_path / "out-saved")


def test_inventory_explore_supports_tag_key_value_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "inventory-tag-filter-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "inventory.json").write_text(
        json.dumps(
            [
                {
                    "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a",
                    "name": "vm-a",
                    "type": "Microsoft.Compute/virtualMachines",
                    "resourceGroup": "rg-app",
                    "subscriptionId": "sub1",
                    "location": "eastus",
                    "tags": {"Application": "ERP"},
                },
                {
                    "id": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Storage/storageAccounts/st-a",
                    "name": "st-a",
                    "type": "Microsoft.Storage/storageAccounts",
                    "resourceGroup": "rg-data",
                    "subscriptionId": "sub1",
                    "location": "eastus",
                    "tags": {"Application": "Data"},
                },
            ]
        ),
        encoding="utf-8",
    )

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="inventory-tag-filter",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["inventory.json"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.get(f"/api/inventory/explore/{run_id}?artifact=inventory&tag_key=Application&tag_value=ERP")
    assert response.status_code == 200
    payload = response.json()
    assert payload["filteredRows"] == 1
    assert payload["rows"][0]["name"] == "vm-a"


def test_diagram_scope_options_supports_resourcegroup_tag_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "scope-options-rg-tag-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "inventory.json").write_text(
        json.dumps(
            [
                {
                    "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a",
                    "name": "vm-a",
                    "type": "Microsoft.Compute/virtualMachines",
                    "resourceGroup": "rg-app",
                    "subscriptionId": "sub1",
                    "location": "eastus",
                    "tags": {"Application": "ERP"},
                },
                {
                    "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/virtualNetworks/vnet-a",
                    "name": "vnet-a",
                    "type": "Microsoft.Network/virtualNetworks",
                    "resourceGroup": "rg-app",
                    "subscriptionId": "sub1",
                    "location": "eastus",
                    "tags": {"Application": "ERP"},
                },
            ]
        ),
        encoding="utf-8",
    )

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="scope-options-rg-tag",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["inventory.json"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.get(
        f"/api/diagram/scope-options/{run_id}?target=resourcegroup-tag&tag_key=Application&tag_value=ERP"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == "resourcegroup-tag"
    assert payload["options"]
    assert payload["options"][0]["value"] == "rg-app"


def test_diagram_scope_options_type_filter_returns_only_matching_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "scope-options-type-filter-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "inventory.json").write_text(
        json.dumps(
            [
                {
                    "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm-a",
                    "name": "vm-a",
                    "type": "Microsoft.Compute/virtualMachines",
                    "resourceGroup": "rg1",
                },
                {
                    "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic-a",
                    "name": "nic-a",
                    "type": "Microsoft.Network/networkInterfaces",
                    "resourceGroup": "rg1",
                },
            ]
        ),
        encoding="utf-8",
    )
    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="type-filter-test",
        subscriptions=[],
        seedResourceGroups=["rg1"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["inventory.json"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    # Without filter: both resources are returned
    response_all = client.get(f"/api/diagram/scope-options/{run_id}?target=resource")
    assert response_all.status_code == 200
    all_options = response_all.json()["options"]
    assert len(all_options) == 2

    # With type_filter: only the VM is returned
    response_vms = client.get(
        f"/api/diagram/scope-options/{run_id}?target=resource&type_filter=microsoft.compute/virtualmachines"
    )
    assert response_vms.status_code == 200
    vm_options = response_vms.json()["options"]
    assert len(vm_options) == 1
    assert vm_options[0]["name"] == "vm-a"
    assert vm_options[0]["resourceGroup"] == "rg1"
    assert "virtualMachines/vm-a" in vm_options[0]["value"]


def test_generate_selection_diagram_supports_low_noise_no_expansion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "selection-diagram-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a",
                        "name": "vm-a",
                        "type": "microsoft.compute/virtualmachines",
                        "resourceGroup": "rg-app",
                        "location": "eastus",
                        "tags": {"Application": "ERP"},
                        "properties": {},
                        "isExternal": False,
                        "childResources": [],
                        "attributes": [],
                    },
                    {
                        "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/networkInterfaces/nic-a",
                        "name": "nic-a",
                        "type": "microsoft.network/networkinterfaces",
                        "resourceGroup": "rg-app",
                        "location": "eastus",
                        "tags": {"Application": "ERP"},
                        "properties": {},
                        "isExternal": False,
                        "childResources": [],
                        "attributes": [],
                    },
                ],
                "edges": [
                    {
                        "source": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a",
                        "target": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/networkInterfaces/nic-a",
                        "kind": "vm->nic",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="selection-diagram",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["graph.json"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.post(
        "/api/diagram/generate-selection",
        json={
            "run_id": run_id,
            "resource_ids": [
                "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a"
            ],
            "include_neighbors": False,
            "relationship_depth": 0,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["selectedCount"] == 1
    assert payload["nodeCount"] == 1
    assert payload["edgeCount"] == 0


def test_list_diagram_artifacts_includes_hover_and_scoped_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "diagram-artifacts-hover-run"
    output_dir = tmp_path / run_id
    scoped_dir = output_dir / "diagram-beta" / "selection-1-abcd"
    scoped_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "diagram.drawio").write_text("<mxfile></mxfile>", encoding="utf-8")
    (scoped_dir / "diagram.drawio").write_text("<mxfile></mxfile>", encoding="utf-8")
    (scoped_dir / "diagram_meta.json").write_text(
        json.dumps({"target": "selection", "scope": "selected:1", "diagramMode": "MSFT"}),
        encoding="utf-8",
    )

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="diagram-artifacts-hover",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["diagram.drawio"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.get(f"/api/artifacts/diagrams/{run_id}")
    assert response.status_code == 200
    diagrams = response.json()["diagrams"]

    root_entry = next(item for item in diagrams if item["path"] == "diagram.drawio")
    scoped_entry = next(item for item in diagrams if item["path"].endswith("selection-1-abcd/diagram.drawio"))

    assert root_entry["label"] == "Global Topology (root)"
    assert "Path: diagram.drawio" in root_entry["hover"]
    assert scoped_entry["label"].startswith("Scoped (selection):")
    assert "Scope: selected:1" in scoped_entry["hover"]


def test_generate_vm_quick_diagram_uses_single_vm_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "vm-quick-run"
    output_dir = tmp_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    vm_id = "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-a"
    nic_id = "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/networkInterfaces/nic-a"

    (output_dir / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": vm_id,
                        "name": "vm-a",
                        "type": "microsoft.compute/virtualmachines",
                        "resourceGroup": "rg-app",
                        "location": "eastus",
                        "tags": {},
                        "properties": {},
                        "isExternal": False,
                        "childResources": [],
                        "attributes": [],
                    },
                    {
                        "id": nic_id,
                        "name": "nic-a",
                        "type": "microsoft.network/networkinterfaces",
                        "resourceGroup": "rg-app",
                        "location": "eastus",
                        "tags": {},
                        "properties": {},
                        "isExternal": False,
                        "childResources": [],
                        "attributes": [],
                    },
                ],
                "edges": [
                    {
                        "source": vm_id,
                        "target": nic_id,
                        "kind": "vm->nic",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = PipelineRunner(state_dir=tmp_path / "runner-state")
    cfg = Config(
        app="vm-quick",
        subscriptions=[],
        seedResourceGroups=["imported-artifact"],
        outputDir=str(output_dir),
    )
    runner.register_imported_run(run_id, cfg, imported_artifacts=["graph.json"])
    monkeypatch.setattr(pipeline_runner_module, "_runner", runner)

    client = testclient.TestClient(create_app())
    response = client.post(
        "/api/diagram/generate-vm-quick",
        json={"run_id": run_id, "vm_resource_id": vm_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == "vm-quick"
    assert payload["scope"].lower() == vm_id.lower()
    assert payload["selectedCount"] == 1
    assert payload["nodeCount"] >= 1
