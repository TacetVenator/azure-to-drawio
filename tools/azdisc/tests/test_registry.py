"""Tests for Azure type registry helpers."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.registry import enrich_catalog_with_registry, load_registry, refresh_registry


def _write_icon_map(assets_dir: Path, payload: dict[str, str]) -> None:
    (assets_dir / "azure_icon_map.json").write_text(json.dumps(payload, indent=2) + "\n")


def _write_registry(assets_dir: Path, payload: list[dict]) -> None:
    (assets_dir / "azure_type_registry.json").write_text(json.dumps(payload, indent=2) + "\n")


def test_load_registry_reads_expected_shape(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    _write_registry(
        assets_dir,
        [
            {
                "type": "microsoft.compute/virtualmachines",
                "category": "Compute",
                "hasExplicitIcon": True,
            },
            {
                "type": "microsoft.storage/storageaccounts",
                "category": "Storage",
                "hasExplicitIcon": False,
            },
        ],
    )

    registry = load_registry(assets_dir)

    assert "microsoft.compute/virtualmachines" in registry
    assert registry["microsoft.compute/virtualmachines"]["category"] == "Compute"
    assert registry["microsoft.compute/virtualmachines"]["hasExplicitIcon"] is True
    assert registry["microsoft.storage/storageaccounts"]["hasExplicitIcon"] is False


def test_enrich_catalog_with_registry_adds_registry_metadata():
    catalog = {
        "summary": {
            "resourceCount": 2,
            "typeCount": 2,
            "mappedTypeCount": 1,
            "fallbackTypeCount": 0,
            "unknownTypeCount": 1,
            "edgeStats": {"network-flow": 1},
        },
        "types": [
            {
                "type": "microsoft.compute/virtualmachines",
                "count": 1,
                "category": "Compute",
                "description": "Microsoft.Compute - virtualMachines",
                "iconStatus": "mapped",
            },
            {
                "type": "microsoft.foo/widgets",
                "count": 1,
                "category": "Foo",
                "description": "Microsoft.Foo - widgets",
                "iconStatus": "unknown",
            },
        ],
    }
    registry = {
        "microsoft.compute/virtualmachines": {
            "type": "microsoft.compute/virtualmachines",
            "category": "Compute",
            "hasExplicitIcon": True,
        },
        "microsoft.storage/storageaccounts": {
            "type": "microsoft.storage/storageaccounts",
            "category": "Storage",
            "hasExplicitIcon": True,
        },
    }
    icon_map = {"microsoft.compute/virtualmachines": "shape=image;"}

    enriched = enrich_catalog_with_registry(catalog, registry, icon_map)

    assert "registry" in enriched
    assert enriched["registry"]["knownTypeCount"] == 2
    assert enriched["registry"]["discoveredKnownTypeCount"] == 1
    assert enriched["registry"]["discoveredUnknownToRegistryCount"] == 1
    assert enriched["registry"]["registryOnlyTypeCount"] == 1

    row_known = next(r for r in enriched["types"] if r["type"] == "microsoft.compute/virtualmachines")
    row_unknown = next(r for r in enriched["types"] if r["type"] == "microsoft.foo/widgets")
    assert row_known["inRegistry"] is True
    assert row_known["hasExplicitIcon"] is True
    assert row_unknown["inRegistry"] is False
    assert row_unknown["hasExplicitIcon"] is False

    assert len(enriched["registryOnlyTypes"]) == 1
    assert enriched["registryOnlyTypes"][0]["type"] == "microsoft.storage/storageaccounts"


def test_refresh_registry_writes_file_when_arg_unavailable(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    _write_icon_map(
        assets_dir,
        {
            "microsoft.compute/virtualmachines": "shape=image;",
            "microsoft.storage/storageaccounts": "shape=image;",
        },
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("arg unavailable")

    monkeypatch.setattr("tools.azdisc.registry.run_az_json", _raise)

    summary = refresh_registry(assets_dir=assets_dir)

    assert summary["totalTypes"] >= 2
    assert summary["iconMappedTypes"] >= 2
    assert summary["argTypesDiscovered"] == 0
    assert summary["argQueryError"] is not None

    registry_path = assets_dir / "azure_type_registry.json"
    assert registry_path.exists()
    rows = json.loads(registry_path.read_text())
    types = {row["type"] for row in rows}
    assert "microsoft.compute/virtualmachines" in types
    assert "microsoft.storage/storageaccounts" in types
