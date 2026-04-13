from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.azdisc.config import load_config, Config
from tools.azdisc.docs import generate_docs
from tools.azdisc.insights import generate_vm_details_csv
from tools.azdisc.inventory import generate_inventory_by_type_csv


FIXTURES = Path(__file__).parent / "fixtures"


def test_load_config_accepts_management_groups_and_optional_flags(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "app": "ari-port",
        "subscriptions": [],
        "seedManagementGroups": ["mg-platform"],
        "outputDir": str(tmp_path / "out"),
        "includeAdvisor": True,
        "includeQuota": True,
        "includeVmDetails": True,
    }))

    cfg = load_config(str(config_path))

    assert cfg.seedManagementGroups == ["mg-platform"]
    assert cfg.includeAdvisor is True
    assert cfg.includeQuota is True
    assert cfg.includeVmDetails is True


def test_generate_inventory_by_type_csv_and_vm_details(tmp_path):
    inventory = json.loads((FIXTURES / "app_contoso.json").read_text())
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    cfg = Config(
        app="contoso-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        includeVmDetails=True,
    )

    manifest_path = generate_inventory_by_type_csv(cfg)
    vm_details_path = generate_vm_details_csv(cfg)

    manifest = json.loads(manifest_path.read_text())
    assert manifest["exports"]
    assert any(item["type"] == "microsoft.compute/virtualmachines" for item in manifest["exports"])

    with vm_details_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["Name"]
    assert "VmSize" in rows[0]


def test_generate_docs_writes_ari_style_reports(tmp_path):
    fixture = json.loads((FIXTURES / "app_contoso.json").read_text())
    (tmp_path / "inventory.json").write_text(json.dumps(fixture))
    graph = {
        "nodes": [
            {
                "id": item["id"],
                "name": item.get("name"),
                "type": item.get("type"),
                "location": item.get("location"),
                "resourceGroup": item.get("resourceGroup"),
                "subscriptionId": item.get("subscriptionId"),
                "properties": item.get("properties") or {},
                "attributes": [],
            }
            for item in fixture[:10]
        ],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "unresolved.json").write_text("[]")
    cfg = Config(
        app="contoso-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
    )

    generate_docs(cfg)

    assert (tmp_path / "organization.md").exists()
    assert (tmp_path / "resource_groups.md").exists()
    assert (tmp_path / "resource_types.md").exists()
    assert (tmp_path / "index.md").exists()
    assert (tmp_path / "inventory_by_type" / "manifest.json").exists()
    assert "Organization summary" in (tmp_path / "index.md").read_text()
