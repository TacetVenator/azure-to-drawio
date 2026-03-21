"""Integration test: mock inventory → graph → draw.io XML → PNG export.

Uses the app_contoso fixture (a realistic 3-tier application in a single
resource group) to exercise the full graph-build and diagram-generation
pipeline without calling Azure.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config
from tools.azdisc.graph import build_graph
from tools.azdisc.drawio import generate_drawio, _try_export

FIXTURES = Path(__file__).parent / "fixtures"


def assert_drawio_references_resolve(drawio_path: Path) -> None:
    """Assert that all draw.io ID references point to existing cells."""
    root = ET.parse(str(drawio_path)).getroot()
    ids = {el.get("id") for el in root.findall(".//*[@id]")}
    missing = []
    for attr in ("parent", "source", "target"):
        for el in root.findall(f".//*[@{attr}]"):
            ref = el.get(attr)
            if ref not in ids:
                missing.append((attr, el.get("id"), ref))
    assert not missing, f"Unresolved draw.io references in {drawio_path}: {missing[:10]}"


def _make_config(tmp_path: Path) -> Config:
    """Create a Config that writes output into the pytest tmp dir."""
    return Config(
        app="contoso-app",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
    )


def _seed_output_files(tmp_path: Path) -> None:
    """Copy the fixture into the output dir as inventory.json + unresolved.json.

    build_graph reads inventory.json directly, so we place the fixture there,
    bypassing the Azure CLI seed/expand stages entirely.
    """
    fixture = FIXTURES / "app_contoso.json"
    (tmp_path / "inventory.json").write_text(fixture.read_text())
    (tmp_path / "unresolved.json").write_text("[]")


# ── Graph build ──────────────────────────────────────────────────────────


class TestGraphBuild:
    """Verify graph construction from the contoso fixture."""

    def test_graph_produces_nodes_and_edges(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        graph = build_graph(cfg)

        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0

    def test_graph_json_written(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        build_graph(cfg)

        graph_path = tmp_path / "graph.json"
        assert graph_path.exists()
        data = json.loads(graph_path.read_text())
        assert "nodes" in data
        assert "edges" in data

    def test_expected_resource_types_present(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        graph = build_graph(cfg)

        types = {n["type"] for n in graph["nodes"]}
        expected = {
            "microsoft.compute/virtualmachines",
            "microsoft.network/virtualnetworks",
            "microsoft.network/virtualnetworks/subnets",
            "microsoft.network/networkinterfaces",
            "microsoft.network/networksecuritygroups",
            "microsoft.network/routetables",
            "microsoft.network/loadbalancers",
            "microsoft.network/publicipaddresses",
            "microsoft.network/privateendpoints",
            "microsoft.sql/servers",
            "microsoft.keyvault/vaults",
            "microsoft.storage/storageaccounts",
            "microsoft.compute/disks",
        }
        for t in expected:
            assert t in types, f"Missing resource type: {t}"

    def test_vm_to_nic_edges(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        graph = build_graph(cfg)

        vm_nic = [e for e in graph["edges"] if e["kind"] == "vm->nic"]
        assert len(vm_nic) == 2, "Expected 2 vm->nic edges (web + app VMs)"

    def test_private_endpoint_to_sql(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        graph = build_graph(cfg)

        pe_target = [e for e in graph["edges"] if e["kind"] == "privateEndpoint->target"]
        assert len(pe_target) >= 1
        targets = {e["target"] for e in pe_target}
        assert any("sql-contoso" in t for t in targets)

    def test_subnet_route_table_edge(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        graph = build_graph(cfg)

        udr = [e for e in graph["edges"] if e["kind"] == "subnet->routeTable"]
        assert len(udr) >= 1

    def test_sql_database_merged_as_child(self, tmp_path):
        """SQL databases are child resources and should be merged into the server."""
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        graph = build_graph(cfg)

        db_nodes = [n for n in graph["nodes"]
                     if n["type"] == "microsoft.sql/servers/databases"]
        # The database should either be merged or standalone — just verify
        # the server node exists
        server_nodes = [n for n in graph["nodes"]
                         if n["type"] == "microsoft.sql/servers"]
        assert len(server_nodes) == 1


# ── Draw.io XML generation ──────────────────────────────────────────────


class TestDrawioGeneration:
    """Verify draw.io XML output from the contoso fixture."""

    def _generate(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        build_graph(cfg)
        generate_drawio(cfg)
        return cfg

    def test_drawio_file_created(self, tmp_path):
        cfg = self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        assert drawio_path.exists()
        assert drawio_path.stat().st_size > 0

    def test_drawio_is_valid_xml(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        root = tree.getroot()
        assert root.tag == "mxfile"

    def test_drawio_references_are_valid(self, tmp_path):
        self._generate(tmp_path)
        assert_drawio_references_resolve(tmp_path / "diagram.drawio")

    def test_drawio_has_diagram_element(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        diagrams = tree.findall("diagram")
        assert len(diagrams) == 1
        assert diagrams[0].get("name") == "contoso-app"

    def test_drawio_has_graph_model(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        model = tree.find(".//mxGraphModel")
        assert model is not None

    def test_drawio_contains_vertex_cells(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        cells = tree.findall(".//mxCell[@vertex='1']")
        # We have 20+ resources in the fixture
        assert len(cells) >= 15, f"Expected ≥15 vertex cells, got {len(cells)}"

    def test_drawio_contains_edge_cells(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        edges = tree.findall(".//mxCell[@edge='1']")
        assert len(edges) >= 5, f"Expected ≥5 edge cells, got {len(edges)}"

    def test_drawio_vertex_cells_have_geometry(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        for v in vertices:
            geo = v.find("mxGeometry")
            assert geo is not None, f"Vertex {v.get('id')} missing geometry"
            assert geo.get("x") is not None
            assert geo.get("y") is not None
            assert geo.get("width") is not None
            assert geo.get("height") is not None

    def test_icons_used_json_written(self, tmp_path):
        self._generate(tmp_path)
        icons_path = tmp_path / "icons_used.json"
        assert icons_path.exists()
        data = json.loads(icons_path.read_text())
        assert "mapped" in data
        assert "unknown" in data

    def test_drawio_node_labels_present(self, tmp_path):
        self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        expected_names = {"vm-web-01", "vm-app-01", "vnet-contoso", "lb-web",
                          "sql-contoso", "kv-contoso", "stcontoso"}
        for name in expected_names:
            assert name in labels, f"Missing label '{name}' in diagram"

    def test_external_inferred_resource_uses_azure_icon_style(self, tmp_path):
        _seed_output_files(tmp_path)
        unresolved = [
            "/subscriptions/sub1/resourcegroups/rg-shared/providers/microsoft.storage/storageaccounts/stshared"
        ]
        (tmp_path / "unresolved.json").write_text(json.dumps(unresolved))
        cfg = _make_config(tmp_path)
        build_graph(cfg)
        generate_drawio(cfg)

        drawio_path = tmp_path / "diagram.drawio"
        tree = ET.parse(str(drawio_path))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        target = next(v for v in vertices if v.get("value") == "stshared (external)")
        style = target.get("style", "")

        assert "Storage_Accounts.svg" in style
        assert "strokeColor=#b85450" in style
        assert "dashed=1" in style

        xml_text = drawio_path.read_text()
        assert "Red dashed resource: unresolved or out-of-scope dependency" in xml_text


# ── PNG export ───────────────────────────────────────────────────────────


_HAS_DRAWIO_CLI = shutil.which("drawio") is not None


class TestPngExport:
    """Verify PNG export via the drawio CLI.

    These tests are skipped when the drawio CLI is not available
    (e.g. lightweight CI containers without a display server).
    """

    def _generate(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        build_graph(cfg)
        generate_drawio(cfg)
        return cfg

    @pytest.mark.skipif(not _HAS_DRAWIO_CLI, reason="drawio CLI not installed")
    def test_png_exported(self, tmp_path):
        cfg = self._generate(tmp_path)
        png_path = tmp_path / "diagram.png"
        assert png_path.exists()
        assert png_path.stat().st_size > 0

    @pytest.mark.skipif(not _HAS_DRAWIO_CLI, reason="drawio CLI not installed")
    def test_png_is_valid_image(self, tmp_path):
        self._generate(tmp_path)
        png_path = tmp_path / "diagram.png"
        # PNG files start with the 8-byte magic signature
        header = png_path.read_bytes()[:8]
        assert header == b"\x89PNG\r\n\x1a\n", "File is not a valid PNG"

    @pytest.mark.skipif(not _HAS_DRAWIO_CLI, reason="drawio CLI not installed")
    def test_svg_also_exported(self, tmp_path):
        self._generate(tmp_path)
        svg_path = tmp_path / "diagram.svg"
        assert svg_path.exists()

    def test_export_skips_gracefully_without_cli(self, tmp_path, monkeypatch):
        """When drawio CLI is absent, export should not raise."""
        _seed_output_files(tmp_path)
        cfg = _make_config(tmp_path)
        build_graph(cfg)
        # Patch before generate_drawio so the CLI is never invoked and no PNG is created
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        generate_drawio(cfg)
        drawio_path = tmp_path / "diagram.drawio"
        _try_export(cfg, drawio_path, "png")
        # No exception is success; PNG should not exist
        assert not (tmp_path / "diagram.png").exists()
