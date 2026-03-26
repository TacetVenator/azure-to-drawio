"""Tests for deep-discovery related resource workflows."""
from __future__ import annotations

import json

import pytest

from tools.azdisc.config import Config, load_config
from tools.azdisc.discover import (
    _DEEP_MATCH_FIELD,
    _deep_discovery_query,
    prepare_related_extended_inventory,
    run_related_candidates,
)


def test_load_config_deep_discovery(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "app": "sap-app",
        "subscriptions": ["sub1", "sub2"],
        "seedResourceGroups": ["rg-app"],
        "outputDir": str(tmp_path / "out"),
        "deepDiscovery": {
            "enabled": True,
            "searchStrings": ["SAP", "bpc"],
            "candidateFile": "candidates.json",
            "promotedFile": "promoted.json",
            "outputDirName": "deep-check",
            "extendedOutputDirName": "extended-pack"
        }
    }))

    cfg = load_config(str(cfg_file))

    assert cfg.deepDiscovery.enabled is True
    assert cfg.deepDiscovery.searchStrings == ["SAP", "bpc"]
    assert cfg.deepDiscovery.candidateFile == "candidates.json"
    assert cfg.deepDiscovery.promotedFile == "promoted.json"
    assert cfg.deep_out("candidates.json") == tmp_path / "out" / "deep-check" / "candidates.json"
    assert cfg.extended_output_dir() == tmp_path / "out" / "deep-check" / "extended-pack"


def test_load_config_rejects_enabled_deep_discovery_without_search_strings(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "app": "sap-app",
        "subscriptions": ["sub1"],
        "seedResourceGroups": ["rg-app"],
        "outputDir": str(tmp_path / "out"),
        "deepDiscovery": {"enabled": True, "searchStrings": []},
    }))

    with pytest.raises(ValueError, match="deepDiscovery.searchStrings"):
        load_config(str(cfg_file))


def test_deep_discovery_query_escapes_terms_and_ors_clauses():
    cfg = Config(
        app="sap-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir="/tmp/out",
    )
    cfg.deepDiscovery.enabled = True
    cfg.deepDiscovery.searchStrings = ["SAP", "bpc's"]

    query = _deep_discovery_query(cfg)

    assert "name contains 'SAP'" in query
    assert "name contains 'bpc''s'" in query
    assert " or " in query


def test_run_related_candidates_writes_candidate_and_promoted_files(tmp_path, monkeypatch):
    base_inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/sap-core-app",
            "name": "sap-core-app",
            "type": "Microsoft.Web/sites",
            "resourceGroup": "rg-app",
            "subscriptionId": "sub1",
            "location": "eastus",
            "properties": {},
        }
    ]
    (tmp_path / "inventory.json").write_text(json.dumps(base_inventory))

    cfg = Config(
        app="sap-app",
        subscriptions=["sub1", "sub2"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.deepDiscovery.enabled = True
    cfg.deepDiscovery.searchStrings = ["SAP", "bpc"]

    def fake_query(_kusto, _subscriptions):
        return [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/sap-core-app",
                "name": "sap-core-app",
                "type": "Microsoft.Web/sites",
                "resourceGroup": "rg-app",
                "subscriptionId": "sub1",
                "location": "eastus",
                "properties": {},
            },
            {
                "id": "/subscriptions/sub2/resourceGroups/rg-monitor/providers/Microsoft.Logic/workflows/bpc-sap-sync",
                "name": "bpc-sap-sync",
                "type": "Microsoft.Logic/workflows",
                "resourceGroup": "rg-monitor",
                "subscriptionId": "sub2",
                "location": "eastus2",
                "properties": {},
            },
            {
                "id": "/subscriptions/sub2/resourceGroups/rg-monitor/providers/Microsoft.Logic/workflows/bpc-sap-sync",
                "name": "bpc-sap-sync",
                "type": "Microsoft.Logic/workflows",
                "resourceGroup": "rg-monitor",
                "subscriptionId": "sub2",
                "location": "eastus2",
                "properties": {},
            },
            {
                "id": "/subscriptions/sub2/resourceGroups/rg-ops/providers/Microsoft.Insights/dataCollectionRules/sap-bpc-dcr",
                "name": "sap-bpc-dcr",
                "type": "Microsoft.Insights/dataCollectionRules",
                "resourceGroup": "rg-ops",
                "subscriptionId": "sub2",
                "location": "eastus2",
                "properties": {},
            },
        ]

    monkeypatch.setattr("tools.azdisc.discover.query", fake_query)

    candidates = run_related_candidates(cfg)

    assert len(candidates) == 2
    assert candidates[0]["subscriptionId"] == "sub2"
    assert candidates[0][_DEEP_MATCH_FIELD] == ["bpc", "SAP"]
    assert candidates[1][_DEEP_MATCH_FIELD] == ["bpc", "SAP"]

    candidate_path = cfg.deep_out(cfg.deepDiscovery.candidateFile)
    promoted_path = cfg.deep_out(cfg.deepDiscovery.promotedFile)
    assert json.loads(candidate_path.read_text()) == candidates
    assert json.loads(promoted_path.read_text()) == candidates


def test_prepare_related_extended_inventory_merges_promoted_resources(tmp_path):
    base_inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "name": "app1",
            "type": "Microsoft.Web/sites",
            "resourceGroup": "rg-app",
            "subscriptionId": "sub1",
            "location": "eastus",
            "properties": {},
        }
    ]
    promoted = [
        {
            "id": "/subscriptions/sub2/resourceGroups/rg-ops/providers/Microsoft.Logic/workflows/sap-sync",
            "name": "sap-sync",
            "type": "Microsoft.Logic/workflows",
            "resourceGroup": "rg-ops",
            "subscriptionId": "sub2",
            "location": "eastus2",
            "properties": {},
            _DEEP_MATCH_FIELD: ["SAP"],
        }
    ]
    (tmp_path / "inventory.json").write_text(json.dumps(base_inventory))
    (tmp_path / "unresolved.json").write_text(json.dumps([
        "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Network/virtualNetworks/vnet-shared"
    ]))

    cfg = Config(
        app="sap-app",
        subscriptions=["sub1", "sub2"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.deepDiscovery.enabled = True
    cfg.deepDiscovery.searchStrings = ["SAP"]
    cfg.ensure_deep_output_dir()
    cfg.deep_out(cfg.deepDiscovery.promotedFile).write_text(json.dumps(promoted))

    extended_cfg = prepare_related_extended_inventory(cfg)

    assert extended_cfg.outputDir == str(cfg.extended_output_dir())
    extended_inventory = json.loads(extended_cfg.out("inventory.json").read_text())
    assert [item["name"] for item in extended_inventory] == ["app1", "sap-sync"]
    assert extended_inventory[1][_DEEP_MATCH_FIELD] == ["SAP"]
    assert json.loads(extended_cfg.out("unresolved.json").read_text()) == [
        "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Network/virtualNetworks/vnet-shared"
    ]
