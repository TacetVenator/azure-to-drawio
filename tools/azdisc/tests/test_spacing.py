"""Tests for the spacing configuration option."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config, VALID_SPACINGS
from tools.azdisc.drawio import (
    CELL_H,
    CELL_W,
    MSFT_CELL_H,
    MSFT_CELL_W,
    _spacing_factor,
    layout_nodes,
    layout_nodes_msft,
    layout_nodes_vnet,
    generate_drawio,
)
from tools.azdisc.graph import build_graph

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _seed(tmp_path: Path, fixture: str = "app_contoso.json") -> None:
    data = (FIXTURES / fixture).read_text()
    (tmp_path / "inventory.json").write_text(data)
    (tmp_path / "unresolved.json").write_text("[]")


def _make_config(tmp_path: Path, spacing: str = "compact", **kwargs) -> Config:
    return Config(
        app="spacing-test",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        spacing=spacing,
        **kwargs,
    )


def _build_nodes_edges(tmp_path, fixture="app_contoso.json"):
    """Build graph from fixture and return (nodes, edges)."""
    _seed(tmp_path, fixture)
    cfg = _make_config(tmp_path)
    graph = build_graph(cfg)
    return graph["nodes"], graph["edges"]


# ── Config tests ─────────────────────────────────────────────────────────


class TestSpacingConfig:
    """Verify spacing field on Config."""

    def test_compact_is_default(self):
        cfg = Config(
            app="test",
            subscriptions=["sub"],
            seedResourceGroups=["rg"],
            outputDir="/tmp/out",
        )
        assert cfg.spacing == "compact"

    def test_spacious_config_accepted(self):
        cfg = Config(
            app="test",
            subscriptions=["sub"],
            seedResourceGroups=["rg"],
            outputDir="/tmp/out",
            spacing="spacious",
        )
        assert cfg.spacing == "spacious"

    def test_invalid_spacing_raises(self, tmp_path):
        cfg_data = {
            "app": "test",
            "subscriptions": ["sub"],
            "seedResourceGroups": ["rg"],
            "outputDir": str(tmp_path),
            "spacing": "huge",
        }
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps(cfg_data))
        from tools.azdisc.config import load_config
        with pytest.raises(ValueError, match="Unsupported spacing"):
            load_config(str(cfg_path))

    def test_valid_spacings_set(self):
        assert "compact" in VALID_SPACINGS
        assert "spacious" in VALID_SPACINGS


# ── Spacing factor helper ────────────────────────────────────────────────


class TestSpacingFactor:

    def test_compact_returns_1(self):
        assert _spacing_factor("compact") == 1.0

    def test_spacious_returns_1_8(self):
        assert _spacing_factor("spacious") == 1.8

    def test_unknown_returns_1(self):
        assert _spacing_factor("unknown") == 1.0

    def test_spacing_1_0_equals_compact(self, tmp_path):
        """spacing=1.0 (compact) and default produce identical positions."""
        nodes, _ = _build_nodes_edges(tmp_path)
        pos_default, _ = layout_nodes(nodes)
        pos_compact, _ = layout_nodes(nodes, spacing=1.0)
        assert pos_default == pos_compact


# ── BANDS layout spacing tests ───────────────────────────────────────────


class TestBandsSpacing:
    """Verify spacing affects BANDS layout positions."""

    def test_compact_positions_unchanged(self, tmp_path):
        """Compact spacing (1.0) must produce the same positions as before."""
        nodes, _ = _build_nodes_edges(tmp_path)
        pos, _ = layout_nodes(nodes, spacing=1.0)
        # Just verify we get positions — exact values validated by existing tests
        assert len(pos) > 0
        for nid, (x, y, w, h) in pos.items():
            assert w == CELL_W
            assert h == CELL_H
            assert x >= 0
            assert y >= 0

    def test_spacious_increases_total_area(self, tmp_path):
        """Spacious mode should produce a larger bounding box."""
        nodes, _ = _build_nodes_edges(tmp_path)
        pos_compact, _ = layout_nodes(nodes, spacing=1.0)
        pos_spacious, _ = layout_nodes(nodes, spacing=1.8)

        def bbox(positions):
            max_x = max(x + w for x, y, w, h in positions.values())
            max_y = max(y + h for x, y, w, h in positions.values())
            return max_x, max_y

        compact_w, compact_h = bbox(pos_compact)
        spacious_w, spacious_h = bbox(pos_spacious)
        assert spacious_w > compact_w, "Spacious width should be larger"
        assert spacious_h > compact_h, "Spacious height should be larger"

    def test_cell_sizes_unchanged_in_spacious(self, tmp_path):
        """Cell sizes must remain constant regardless of spacing."""
        nodes, _ = _build_nodes_edges(tmp_path)
        pos, _ = layout_nodes(nodes, spacing=1.8)
        for nid, (x, y, w, h) in pos.items():
            assert w == CELL_W, f"Node {nid} has wrong width {w}"
            assert h == CELL_H, f"Node {nid} has wrong height {h}"

    def test_spacious_no_overlapping_nodes(self, tmp_path):
        """No nodes should overlap in spacious mode."""
        nodes, _ = _build_nodes_edges(tmp_path)
        pos, _ = layout_nodes(nodes, spacing=1.8)
        rects = list(pos.values())
        for i, (x1, y1, w1, h1) in enumerate(rects):
            for j, (x2, y2, w2, h2) in enumerate(rects):
                if i >= j:
                    continue
                overlap_x = x1 < x2 + w2 and x2 < x1 + w1
                overlap_y = y1 < y2 + h2 and y2 < y1 + h1
                assert not (overlap_x and overlap_y), (
                    f"Nodes {i} and {j} overlap: {(x1,y1,w1,h1)} vs {(x2,y2,w2,h2)}"
                )

    def test_spacious_label_gap_sufficient(self, tmp_path):
        """Vertical gap between adjacent rows should exceed label height (~25px)."""
        nodes, _ = _build_nodes_edges(tmp_path)
        pos, _ = layout_nodes(nodes, spacing=1.8)
        # Collect all unique y positions and sort them
        y_values = sorted({y for (x, y, w, h) in pos.values()})
        if len(y_values) < 2:
            return  # Only one row, nothing to check
        min_gap = min(y_values[i + 1] - (y_values[i] + CELL_H)
                      for i in range(len(y_values) - 1)
                      if y_values[i + 1] > y_values[i] + CELL_H)
        # Labels are ~20-25px; spacious mode should have at least 25px between rows
        assert min_gap >= 25, f"Min vertical gap {min_gap} too small for labels"


# ── VNET layout spacing tests ───────────────────────────────────────────


class TestVnetSpacing:
    """Verify spacing affects VNET>SUBNET layout."""

    def test_spacious_vnet_larger(self, tmp_path):
        nodes, edges = _build_nodes_edges(tmp_path)
        _, cont_compact = layout_nodes_vnet(nodes, edges, spacing=1.0)
        _, cont_spacious = layout_nodes_vnet(nodes, edges, spacing=1.8)

        # VNet containers should be wider/taller in spacious mode
        vnet_compact = [c for c in cont_compact if c["id"].startswith("vnet_")]
        vnet_spacious = [c for c in cont_spacious if c["id"].startswith("vnet_")]
        for cc, cs in zip(
            sorted(vnet_compact, key=lambda c: c["id"]),
            sorted(vnet_spacious, key=lambda c: c["id"]),
        ):
            assert cs["w"] > cc["w"] or cs["h"] > cc["h"], (
                f"Spacious VNet {cs['id']} not larger than compact"
            )

    def test_spacious_no_overlapping_nodes(self, tmp_path):
        nodes, edges = _build_nodes_edges(tmp_path)
        pos, _ = layout_nodes_vnet(nodes, edges, spacing=1.8)
        rects = list(pos.values())
        for i, (x1, y1, w1, h1) in enumerate(rects):
            for j, (x2, y2, w2, h2) in enumerate(rects):
                if i >= j:
                    continue
                overlap_x = x1 < x2 + w2 and x2 < x1 + w1
                overlap_y = y1 < y2 + h2 and y2 < y1 + h1
                assert not (overlap_x and overlap_y)


# ── MSFT layout spacing tests ───────────────────────────────────────────


class TestMsftSpacing:
    """Verify spacing affects MSFT layout."""

    def test_spacious_msft_larger(self, tmp_path):
        nodes, _ = _build_nodes_edges(tmp_path)
        pos_compact, _, _, _ = layout_nodes_msft(nodes, spacing=1.0)
        pos_spacious, _, _, _ = layout_nodes_msft(nodes, spacing=1.8)

        def bbox(positions):
            max_x = max(x + w for x, y, w, h in positions.values())
            max_y = max(y + h for x, y, w, h in positions.values())
            return max_x, max_y

        compact_w, compact_h = bbox(pos_compact)
        spacious_w, spacious_h = bbox(pos_spacious)
        assert spacious_w > compact_w or spacious_h > compact_h

    def test_msft_cell_sizes_unchanged(self, tmp_path):
        nodes, _ = _build_nodes_edges(tmp_path)
        pos, _, _, _ = layout_nodes_msft(nodes, spacing=1.8)
        for nid, (x, y, w, h) in pos.items():
            assert w == MSFT_CELL_W
            assert h == MSFT_CELL_H


# ── Full pipeline spacing integration ───────────────────────────────────


class TestSpacingIntegration:
    """Verify spacing option threads through the full pipeline."""

    def test_spacious_bands_generates_valid_xml(self, tmp_path):
        _seed(tmp_path)
        cfg = _make_config(tmp_path, spacing="spacious")
        build_graph(cfg)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"
        vertices = tree.findall(".//mxCell[@vertex='1']")
        assert len(vertices) >= 10

    def test_spacious_vnet_generates_valid_xml(self, tmp_path):
        _seed(tmp_path)
        cfg = _make_config(tmp_path, spacing="spacious", layout="VNET>SUBNET")
        build_graph(cfg)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"

    def test_spacious_msft_generates_valid_xml(self, tmp_path):
        _seed(tmp_path)
        cfg = _make_config(tmp_path, spacing="spacious", diagramMode="MSFT")
        build_graph(cfg)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"
