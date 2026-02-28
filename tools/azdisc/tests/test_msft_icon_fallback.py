"""Tests for the Microsoft icon ZIP fallback mechanism."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from tools.azdisc.drawio import (
    _load_msft_icon_index,
    _match_msft_icon,
    _msft_svg_style,
    _normalize_name,
    _node_style,
    _rebuild_fallback_library,
    UNKNOWN_STYLE,
    EXTERNAL_STYLE,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------


def test_normalize_name_strips_special_chars():
    assert _normalize_name("Azure-Functions") == "azurefunctions"


def test_normalize_name_lowercases():
    assert _normalize_name("COSMOS DB") == "cosmosdb"


def test_normalize_name_empty():
    assert _normalize_name("") == ""


# ---------------------------------------------------------------------------
# _load_msft_icon_index
# ---------------------------------------------------------------------------


def test_load_msft_icon_index_missing_dir(tmp_path):
    """Returns empty dict when the directory does not exist."""
    index = _load_msft_icon_index(tmp_path)
    assert index == {}


def test_load_msft_icon_index_empty_dir(tmp_path):
    """Returns empty dict when the directory is empty."""
    (tmp_path / "microsoft-azure-icons").mkdir()
    assert _load_msft_icon_index(tmp_path) == {}


def test_load_msft_icon_index_builds_keys(tmp_path):
    """Index is built from SVG filenames with numeric prefix stripped."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10120-icon-service-Azure-Functions.svg"
    svg.write_bytes(b"<svg/>")

    index = _load_msft_icon_index(tmp_path)

    assert "azurefunctions" in index
    assert index["azurefunctions"] == svg


def test_load_msft_icon_index_token_keys(tmp_path):
    """Short token keys (≥3 chars) are also added to the index."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    (icons_dir / "10065-icon-service-Storage-Accounts.svg").write_bytes(b"<svg/>")

    index = _load_msft_icon_index(tmp_path)

    assert "storage" in index
    assert "accounts" in index


def test_load_msft_icon_index_recursive(tmp_path):
    """SVGs in subdirectories are indexed."""
    icons_dir = tmp_path / "microsoft-azure-icons" / "Compute"
    icons_dir.mkdir(parents=True)
    svg = icons_dir / "10021-icon-service-Virtual-Machine.svg"
    svg.write_bytes(b"<svg/>")

    index = _load_msft_icon_index(tmp_path)
    assert "virtualmachine" in index


# ---------------------------------------------------------------------------
# _match_msft_icon
# ---------------------------------------------------------------------------


def test_match_msft_icon_empty_index():
    assert _match_msft_icon("microsoft.storage/storageaccounts", {}) is None


def test_match_msft_icon_by_resource_part(tmp_path):
    """Matches on the full normalized resource-type part."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10065-icon-service-Storage-Accounts.svg"
    svg.write_bytes(b"<svg/>")
    index = _load_msft_icon_index(tmp_path)

    result = _match_msft_icon("microsoft.storage/storageaccounts", index)
    assert result == svg


def test_match_msft_icon_by_provider(tmp_path):
    """Falls back to provider name when resource part has no match."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10229-icon-service-Databricks.svg"
    svg.write_bytes(b"<svg/>")
    index = _load_msft_icon_index(tmp_path)

    # ARM type: microsoft.databricks/workspaces
    # resource part "workspaces" won't match; provider "databricks" will
    result = _match_msft_icon("microsoft.databricks/workspaces", index)
    assert result == svg


def test_match_msft_icon_suffix_stripped(tmp_path):
    """Tries stripping common suffixes like 'accounts' from the resource part."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10100-icon-service-Batch.svg"
    svg.write_bytes(b"<svg/>")
    index = _load_msft_icon_index(tmp_path)

    # "batchaccounts" → strip "accounts" → "batch" → match
    result = _match_msft_icon("microsoft.batch/batchaccounts", index)
    assert result == svg


def test_match_msft_icon_no_match(tmp_path):
    """Returns None when no suitable SVG is found."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    (icons_dir / "99999-icon-service-Completely-Unrelated.svg").write_bytes(b"<svg/>")
    index = _load_msft_icon_index(tmp_path)

    result = _match_msft_icon("microsoft.obscure/unknowntype", index)
    assert result is None


# ---------------------------------------------------------------------------
# _msft_svg_style
# ---------------------------------------------------------------------------


def test_msft_svg_style_contains_base64(tmp_path):
    svg_file = tmp_path / "test.svg"
    svg_content = b"<svg><rect/></svg>"
    svg_file.write_bytes(svg_content)

    style = _msft_svg_style(svg_file)

    expected_b64 = base64.b64encode(svg_content).decode("ascii")
    assert f"data:image/svg+xml;base64,{expected_b64}" in style


def test_msft_svg_style_has_shape_image(tmp_path):
    svg_file = tmp_path / "test.svg"
    svg_file.write_bytes(b"<svg/>")

    style = _msft_svg_style(svg_file)
    assert "shape=image" in style
    assert "verticalLabelPosition=bottom" in style


# ---------------------------------------------------------------------------
# _node_style with MSFT fallback
# ---------------------------------------------------------------------------


def test_node_style_uses_icon_map_first(tmp_path):
    """icon_map takes precedence over MSFT fallback."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    (icons_dir / "10065-icon-service-Storage-Accounts.svg").write_bytes(b"<svg/>")
    msft_icons = _load_msft_icon_index(tmp_path)

    mapped_style = "sketch=0;shape=image;image=img/lib/azure2/storage/Storage.svg;"
    icon_map = {"microsoft.storage/storageaccounts": mapped_style}
    node = {"id": "/sub/rg/storage", "type": "microsoft.storage/storageaccounts"}

    style = _node_style(node, icon_map, msft_icons)
    assert style == mapped_style


def test_node_style_falls_back_to_msft_icon(tmp_path):
    """Returns MSFT embedded SVG style when type is not in icon_map."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10065-icon-service-Storage-Accounts.svg"
    svg.write_bytes(b"<svg><rect/></svg>")
    msft_icons = _load_msft_icon_index(tmp_path)

    node = {"id": "/sub/rg/storage", "type": "microsoft.storage/storageaccounts"}
    style = _node_style(node, {}, msft_icons)

    assert "data:image/svg+xml;base64," in style
    assert style != UNKNOWN_STYLE


def test_node_style_unknown_when_no_match():
    """Falls back to UNKNOWN_STYLE when neither icon_map nor MSFT icon matches."""
    node = {"id": "/sub/rg/thing", "type": "microsoft.obscure/unknowntype"}
    style = _node_style(node, {}, {})
    assert style == UNKNOWN_STYLE


def test_node_style_external_node():
    node = {"id": "ext1", "type": "external", "isExternal": True}
    assert _node_style(node, {}, {}) == EXTERNAL_STYLE


# ---------------------------------------------------------------------------
# _rebuild_fallback_library
# ---------------------------------------------------------------------------


def test_rebuild_fallback_library_empty_icons(tmp_path):
    """Does nothing when msft_icons is empty."""
    lib_path = tmp_path / "azure-fallback.mxlibrary"
    _rebuild_fallback_library(tmp_path, {})
    assert not lib_path.exists()


def test_rebuild_fallback_library_writes_json(tmp_path):
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10120-icon-service-Azure-Functions.svg"
    svg.write_bytes(b"<svg/>")
    msft_icons = _load_msft_icon_index(tmp_path)

    _rebuild_fallback_library(tmp_path, msft_icons)

    lib_path = tmp_path / "azure-fallback.mxlibrary"
    assert lib_path.exists()
    data = json.loads(lib_path.read_text())
    assert isinstance(data, list)
    assert len(data) >= 1


def test_rebuild_fallback_library_entry_format(tmp_path):
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    (icons_dir / "10120-icon-service-Azure-Functions.svg").write_bytes(b"<svg/>")
    msft_icons = _load_msft_icon_index(tmp_path)

    _rebuild_fallback_library(tmp_path, msft_icons)

    data = json.loads((tmp_path / "azure-fallback.mxlibrary").read_text())
    entry = data[0]
    assert "xml" in entry
    assert "w" in entry and "h" in entry
    assert "aspect" in entry and entry["aspect"] == "fixed"
    assert "title" in entry


def test_rebuild_fallback_library_deduplicates(tmp_path):
    """Multiple index keys pointing to the same SVG produce one library entry."""
    icons_dir = tmp_path / "microsoft-azure-icons"
    icons_dir.mkdir()
    svg = icons_dir / "10120-icon-service-Azure-Functions.svg"
    svg.write_bytes(b"<svg/>")
    msft_icons = _load_msft_icon_index(tmp_path)

    # Many keys may point to the same file
    assert len(set(str(p) for p in msft_icons.values())) == 1

    _rebuild_fallback_library(tmp_path, msft_icons)
    data = json.loads((tmp_path / "azure-fallback.mxlibrary").read_text())
    assert len(data) == 1


# ---------------------------------------------------------------------------
# icons_used tracking in generate_drawio (integration-style)
# ---------------------------------------------------------------------------


def test_icons_used_fallback_tracked(tmp_path, monkeypatch):
    """generate_drawio tracks fallback-sourced icons in icons_used['fallback']."""
    import json as jsonmod
    import tools.azdisc.drawio as drawio_mod
    from tools.azdisc.config import Config
    from tools.azdisc.graph import build_graph
    from tools.azdisc.drawio import generate_drawio

    # Create a minimal inventory with a type NOT in azure_icon_map.json
    FAKE_TYPE = "microsoft.obscure/widgethubs"
    inventory = [
        {
            "id": f"/subscriptions/sub1/resourceGroups/rg-test/providers/{FAKE_TYPE}/wh1",
            "name": "wh1",
            "type": FAKE_TYPE,
            "location": "eastus",
            "resourceGroup": "rg-test",
            "subscriptionId": "sub1",
            "properties": {},
        }
    ]

    out = tmp_path / "output"
    out.mkdir()
    (out / "inventory.json").write_text(json.dumps(inventory))
    (out / "unresolved.json").write_text("[]")

    cfg = Config(
        app="test-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-test"],
        outputDir=str(out),
    )
    build_graph(cfg)

    # Build a fake MSFT icon index in tmp_path (never touches the real assets dir)
    fake_svg = tmp_path / "99999-icon-service-Widget-Hubs.svg"
    fake_svg.write_bytes(b"<svg><rect/></svg>")
    fake_msft_icons = {"widgethubs": fake_svg, "widget": fake_svg, "hubs": fake_svg}

    # Patch _load_msft_icon_index to return the fake index
    monkeypatch.setattr(drawio_mod, "_load_msft_icon_index",
                        lambda _assets_dir: fake_msft_icons)
    # Patch _rebuild_fallback_library to be a no-op (avoid touching assets/)
    monkeypatch.setattr(drawio_mod, "_rebuild_fallback_library",
                        lambda *_a, **_kw: None)

    generate_drawio(cfg)
    icons_path = out / "icons_used.json"
    data = jsonmod.loads(icons_path.read_text())
    assert FAKE_TYPE in data["fallback"], (
        f"Expected {FAKE_TYPE!r} in fallback, got: {data}"
    )
