"""Tests for inventory explorer pagination/filtering service."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc_ui.services import inventory_explorer
from tools.azdisc_ui.services.inventory_explorer import get_inventory_facets, query_inventory


def _write_inventory(path: Path) -> None:
    rows = [
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
            "id": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Storage/storageAccounts/stdata",
            "name": "stdata",
            "type": "Microsoft.Storage/storageAccounts",
            "resourceGroup": "rg-data",
            "subscriptionId": "sub1",
            "location": "eastus2",
            "tags": {"Application": "Data"},
        },
        {
            "id": "/subscriptions/sub2/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet-hub",
            "name": "vnet-hub",
            "type": "Microsoft.Network/virtualNetworks",
            "resourceGroup": "rg-net",
            "subscriptionId": "sub2",
            "location": "westus",
            "tags": {"Environment": "prod"},
        },
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_query_inventory_paginates_and_reports_counts(tmp_path: Path) -> None:
    _write_inventory(tmp_path / "inventory.json")

    result = query_inventory(str(tmp_path), artifact="inventory", offset=1, limit=1)

    assert result["totalRows"] == 3
    assert result["filteredRows"] == 3
    assert result["offset"] == 1
    assert result["limit"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["name"] == "stdata"
    assert result["hasMore"] is True


def test_query_inventory_filters_by_query_and_exact_fields(tmp_path: Path) -> None:
    _write_inventory(tmp_path / "inventory.json")

    result = query_inventory(
        str(tmp_path),
        artifact="inventory",
        query="erp",
        resource_types=["microsoft.compute/virtualmachines"],
        resource_groups=["rg-app"],
        subscriptions=["sub1"],
    )

    assert result["filteredRows"] == 1
    assert len(result["rows"]) == 1
    assert result["rows"][0]["name"] == "vm-a"


def test_query_inventory_filters_by_tag_key_and_value(tmp_path: Path) -> None:
    _write_inventory(tmp_path / "inventory.json")

    by_key = query_inventory(
        str(tmp_path),
        artifact="inventory",
        tag_keys=["application"],
    )
    assert by_key["filteredRows"] == 2

    by_value = query_inventory(
        str(tmp_path),
        artifact="inventory",
        tag_values=["prod"],
    )
    assert by_value["filteredRows"] == 1
    assert by_value["rows"][0]["name"] == "vnet-hub"


def test_get_inventory_facets_returns_distinct_sorted_values(tmp_path: Path) -> None:
    _write_inventory(tmp_path / "inventory.json")

    result = get_inventory_facets(str(tmp_path), artifact="inventory")

    assert result["totalRows"] == 3
    assert result["artifactPath"] == "inventory.json"
    assert result["facets"]["resourceTypes"] == [
        "Microsoft.Compute/virtualMachines",
        "Microsoft.Network/virtualNetworks",
        "Microsoft.Storage/storageAccounts",
    ]
    assert result["facets"]["resourceGroups"] == ["rg-app", "rg-data", "rg-net"]
    assert result["facets"]["subscriptions"] == ["sub1", "sub2"]
    assert result["facets"]["tagKeys"] == ["Application", "Environment"]
    assert result["facets"]["tagValuesByKey"]["Application"] == ["Data", "ERP"]
    assert result["facets"]["tagValuesByKey"]["Environment"] == ["prod"]


def test_get_inventory_facets_uses_cache_for_unchanged_artifact(tmp_path: Path, monkeypatch) -> None:
    _write_inventory(tmp_path / "inventory.json")
    inventory_explorer._FACET_CACHE.clear()

    call_count = 0
    original_iter_rows = inventory_explorer._iter_rows

    def counting_iter_rows(path: Path):
        nonlocal call_count
        call_count += 1
        yield from original_iter_rows(path)

    monkeypatch.setattr(inventory_explorer, "_iter_rows", counting_iter_rows)

    first = get_inventory_facets(str(tmp_path), artifact="inventory")
    second = get_inventory_facets(str(tmp_path), artifact="inventory")

    assert first == second
    assert call_count == 1
