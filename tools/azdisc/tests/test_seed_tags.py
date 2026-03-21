"""Tests for tag-seeded discovery."""
from __future__ import annotations

import json

import pytest

from tools.azdisc.config import Config, load_config
from tools.azdisc.discover import _seed_query, run_seed
from tools.azdisc.drawio import _l2r_find_direct_network_items
from tools.azdisc.util import normalize_id


def test_load_config_accepts_tag_only_seed(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "app": "tag-seed",
        "subscriptions": ["sub1"],
        "outputDir": str(tmp_path / "out"),
        "seedTags": {"Application": "checkout"},
    }))

    cfg = load_config(str(cfg_file))

    assert cfg.seedResourceGroups == []
    assert cfg.seedTags == {"Application": "checkout"}
    assert cfg.seedTagKeys == []


def test_load_config_accepts_seed_tag_keys(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "app": "tag-key-seed",
        "subscriptions": ["sub1"],
        "outputDir": str(tmp_path / "out"),
        "seedTagKeys": ["Application", "Workload"],
    }))

    cfg = load_config(str(cfg_file))

    assert cfg.seedResourceGroups == []
    assert cfg.seedTagKeys == ["Application", "Workload"]


def test_load_config_requires_at_least_one_seed_scope(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "app": "missing-seed",
        "subscriptions": ["sub1"],
        "outputDir": str(tmp_path / "out"),
    }))

    with pytest.raises(ValueError, match="at least one of seedResourceGroups, seedTags, or seedTagKeys"):
        load_config(str(cfg_file))


def test_seed_query_supports_combined_rg_and_tag_scopes():
    cfg = Config(
        app="tag-seed",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir="/tmp/out",
        seedTags={"Application": "checkout"},
        seedTagKeys=["Workload"],
    )

    kusto = _seed_query(cfg)

    assert "resourceGroup in~ ('rg-app')" in kusto
    assert "tostring(tags['Application']) =~ 'checkout'" in kusto
    assert "isnotempty(tostring(tags['Workload']))" in kusto
    assert "| project id, name, type, location, subscriptionId, resourceGroup, tags, sku, kind, systemData, properties" in kusto


def test_run_seed_uses_tag_seed_query(monkeypatch, tmp_path):
    seen = {}

    def fake_query(kusto, subscriptions):
        seen["kusto"] = kusto
        seen["subscriptions"] = subscriptions
        return [{"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/sites/app1", "name": "app1"}]

    monkeypatch.setattr("tools.azdisc.discover.query", fake_query)

    cfg = Config(
        app="tag-seed",
        subscriptions=["sub1"],
        seedResourceGroups=[],
        outputDir=str(tmp_path),
        seedTags={"Application": "checkout"},
    )

    rows = run_seed(cfg)

    assert len(rows) == 1
    assert "tostring(tags['Application']) =~ 'checkout'" in seen["kusto"]
    assert seen["subscriptions"] == ["sub1"]
    assert json.loads((tmp_path / "seed.json").read_text())[0]["name"] == "app1"


def test_l2r_direct_network_items_respect_seed_tags():
    vm_id = "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm1"
    nic_id = "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/networkInterfaces/nic1"
    subnet_id = "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet1"
    vnet_id = "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1"

    nodes = [
        {
            "id": vm_id,
            "name": "vm1",
            "type": "microsoft.compute/virtualmachines",
            "resourceGroup": "rg-app",
            "subscriptionId": "sub1",
            "location": "eastus",
            "tags": {"Application": "checkout"},
        },
        {
            "id": nic_id,
            "name": "nic1",
            "type": "microsoft.network/networkinterfaces",
            "resourceGroup": "rg-net",
            "subscriptionId": "sub1",
            "location": "eastus",
            "tags": {},
        },
        {
            "id": subnet_id,
            "name": "snet1",
            "type": "microsoft.network/virtualnetworks/subnets",
            "resourceGroup": "rg-net",
            "subscriptionId": "sub1",
            "location": "eastus",
            "tags": {},
        },
        {
            "id": vnet_id,
            "name": "vnet1",
            "type": "microsoft.network/virtualnetworks",
            "resourceGroup": "rg-net",
            "subscriptionId": "sub1",
            "location": "eastus",
            "tags": {},
        },
    ]
    edges = [
        {"source": vm_id, "target": nic_id, "kind": "vm->nic"},
        {"source": nic_id, "target": subnet_id, "kind": "nic->subnet"},
        {"source": subnet_id, "target": vnet_id, "kind": "subnet->vnet"},
    ]

    direct_net_ids, indirect_lines = _l2r_find_direct_network_items(
        nodes,
        edges,
        seed_rgs=[],
        seed_tags={"Application": "checkout"},
        seed_tag_keys=[],
    )

    assert normalize_id(nic_id) in direct_net_ids
    assert normalize_id(subnet_id) in direct_net_ids
    assert normalize_id(vnet_id) in direct_net_ids
    assert indirect_lines == []
