"""Tests for the VNET>SUBNET layout mode."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config
from tools.azdisc.drawio import (
    CELL_H,
    CELL_W,
    layout_nodes_vnet,
)
from tools.azdisc.graph import build_graph, build_node, extract_edges

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _build_contoso_graph():
    """Build graph from contoso fixture and return nodes + edges."""
    inventory = _load_fixture("app_contoso.json")
    from tools.azdisc.graph import (
        _is_child_resource,
        _find_parent_id,
        _collect_attributes,
    )
    from tools.azdisc.util import normalize_id

    parent_resources = []
    child_resources = []
    for r in inventory:
        rtype = (r.get("type") or "").lower()
        if _is_child_resource(rtype):
            child_resources.append(r)
        else:
            parent_resources.append(r)

    nodes = [build_node(r) for r in parent_resources]
    node_map = {n["id"]: n for n in nodes}

    for child in child_resources:
        parent_id = _find_parent_id(child.get("id", ""), child.get("type", ""))
        if parent_id and parent_id in node_map:
            node_map[parent_id]["childResources"].append({
                "name": child.get("name", ""),
                "type": (child.get("type") or "").lower(),
                "properties": child.get("properties") or {},
            })
        else:
            nodes.append(build_node(child))

    for node in nodes:
        node["attributes"] = _collect_attributes(node)

    nodes.sort(key=lambda n: (n["resourceGroup"], n["type"], n["name"], n["id"]))
    edges = extract_edges(nodes)
    return nodes, edges


# ── layout_nodes_vnet basic tests ────────────────────────────────────────


class TestVnetLayout:
    """Verify VNet/subnet container-based layout."""

    def test_returns_positions_and_containers(self):
        nodes, edges = _build_contoso_graph()
        positions, containers = layout_nodes_vnet(nodes, edges)
        assert isinstance(positions, dict)
        assert isinstance(containers, list)
        assert len(containers) > 0

    def test_all_resource_nodes_have_positions(self):
        """Every non-VNet non-subnet node should be placed."""
        nodes, edges = _build_contoso_graph()
        positions, _ = layout_nodes_vnet(nodes, edges)

        skip_types = {
            "microsoft.network/virtualnetworks",
            "microsoft.network/virtualnetworks/subnets",
        }
        for n in nodes:
            if n["type"] in skip_types:
                continue
            assert n["id"] in positions, f"Node {n['name']} ({n['type']}) has no position"

    def test_vnet_container_exists(self):
        nodes, edges = _build_contoso_graph()
        _, containers = layout_nodes_vnet(nodes, edges)

        vnet_containers = [c for c in containers if c["id"].startswith("vnet_")]
        assert len(vnet_containers) >= 1, "Expected at least one VNet container"

    def test_subnet_containers_exist(self):
        nodes, edges = _build_contoso_graph()
        _, containers = layout_nodes_vnet(nodes, edges)

        subnet_containers = [c for c in containers if c["id"].startswith("subnet_")]
        assert len(subnet_containers) >= 3, "Expected at least 3 subnet containers (web, app, data)"

    def test_subnet_containers_have_vnet_parent(self):
        nodes, edges = _build_contoso_graph()
        _, containers = layout_nodes_vnet(nodes, edges)

        container_ids = {c["id"] for c in containers}
        for c in containers:
            if "subnet_" in c["id"]:
                assert c["parent"].startswith("vnet_"), (
                    f"Subnet container {c['id']} should have a VNet parent, got {c['parent']}"
                )
                assert c["parent"] in container_ids, (
                    f"Subnet parent {c['parent']} not found in containers"
                )

    def test_no_overlapping_nodes(self):
        nodes, edges = _build_contoso_graph()
        positions, _ = layout_nodes_vnet(nodes, edges)
        rects = list(positions.values())
        for i, (x1, y1, w1, h1) in enumerate(rects):
            for j, (x2, y2, w2, h2) in enumerate(rects):
                if i >= j:
                    continue
                overlap_x = x1 < x2 + w2 and x2 < x1 + w1
                overlap_y = y1 < y2 + h2 and y2 < y1 + h1
                assert not (overlap_x and overlap_y), (
                    f"Nodes {i} and {j} overlap: {(x1,y1,w1,h1)} vs {(x2,y2,w2,h2)}"
                )

    def test_positions_are_non_negative(self):
        nodes, edges = _build_contoso_graph()
        positions, _ = layout_nodes_vnet(nodes, edges)
        for nid, (x, y, w, h) in positions.items():
            assert x >= 0, f"Node {nid} has negative x={x}"
            assert y >= 0, f"Node {nid} has negative y={y}"
            assert w == CELL_W
            assert h == CELL_H

    def test_layout_is_deterministic(self):
        nodes, edges = _build_contoso_graph()
        pos1, cont1 = layout_nodes_vnet(nodes, edges)
        pos2, cont2 = layout_nodes_vnet(nodes, edges)
        assert pos1 == pos2
        assert len(cont1) == len(cont2)
        for c1, c2 in zip(cont1, cont2):
            assert c1 == c2

    def test_container_labels_match_resource_names(self):
        nodes, edges = _build_contoso_graph()
        _, containers = layout_nodes_vnet(nodes, edges)

        labels = {c["label"] for c in containers}
        assert "vnet-contoso" in labels, "VNet container should be labeled with resource name"
        for subnet_name in ["snet-web", "snet-app", "snet-data"]:
            assert subnet_name in labels, f"Subnet container '{subnet_name}' missing"


# ── Integration with generate_drawio ─────────────────────────────────────


def _seed_output_files(tmp_path: Path) -> None:
    fixture = FIXTURES / "app_contoso.json"
    (tmp_path / "inventory.json").write_text(fixture.read_text())
    (tmp_path / "unresolved.json").write_text("[]")


def _make_vnet_config(tmp_path: Path) -> Config:
    return Config(
        app="contoso-vnet",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        layout="VNET>SUBNET",
    )


class TestVnetDrawioGeneration:
    """Integration tests for the full VNET>SUBNET pipeline."""

    def _generate(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_vnet_config(tmp_path)
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        return cfg

    def test_drawio_file_created(self, tmp_path):
        cfg = self._generate(tmp_path)
        drawio_path = tmp_path / "diagram.drawio"
        assert drawio_path.exists()
        assert drawio_path.stat().st_size > 0

    def test_drawio_is_valid_xml(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        root = tree.getroot()
        assert root.tag == "mxfile"

    def test_drawio_has_container_cells(self, tmp_path):
        """VNET>SUBNET mode should produce container cells with connectable=0."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        assert len(containers) >= 4, (
            f"Expected >=4 containers (1 VNet + 3 subnets), got {len(containers)}"
        )

    def test_drawio_no_vnet_subnet_icon_cells(self, tmp_path):
        """VNet and subnet nodes should not appear as full icon cells (decorations OK)."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        for v in vertices:
            style = v.get("style", "")
            # Container cells use our VNET_STYLE/SUBNET_STYLE, not image-based icon styles
            if "connectable" in v.attrib:
                continue
            # Allow small subnet icon decorations (id ends with _icon)
            if v.get("id", "").endswith("_icon"):
                continue
            # Icon cells should not be for VNets or subnets
            if "Virtual_Networks.svg" in style or "Subnet.svg" in style:
                pytest.fail(
                    f"Found VNet/subnet icon cell in VNET>SUBNET mode: {v.get('value')}"
                )

    def test_subnet_containers_have_icon_decoration(self, tmp_path):
        """Each subnet container in VNET>SUBNET mode should have a small icon decoration."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")

        # Find subnet containers
        subnet_containers = [
            v for v in vertices
            if v.get("id", "").startswith("subnet_") and v.get("connectable") == "0"
            and not v.get("id", "").endswith("_icon")
        ]
        assert len(subnet_containers) >= 1, "Expected at least one subnet container"

        # Find subnet icon decorations
        icon_decorations = [
            v for v in vertices
            if v.get("id", "").endswith("_icon") and "Subnet.svg" in v.get("style", "")
        ]
        assert len(icon_decorations) == len(subnet_containers), (
            f"Expected {len(subnet_containers)} subnet icon decorations, got {len(icon_decorations)}"
        )

        # Each icon should be small (24x24)
        for icon in icon_decorations:
            geo = icon.find("mxGeometry")
            assert geo is not None
            assert geo.get("width") == "24"
            assert geo.get("height") == "24"

    def test_drawio_contains_vertex_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        # Count non-container vertex cells
        vertices = [
            v for v in tree.findall(".//mxCell[@vertex='1']")
            if v.get("connectable") != "0"
        ]
        assert len(vertices) >= 10, f"Expected >=10 resource vertex cells, got {len(vertices)}"

    def test_drawio_contains_edge_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        assert len(edges) >= 5, f"Expected >=5 edge cells, got {len(edges)}"

    def test_drawio_vertex_cells_have_geometry(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        for v in vertices:
            geo = v.find("mxGeometry")
            assert geo is not None, f"Vertex {v.get('id')} missing geometry"

    def test_expected_resource_labels(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        # These resources should appear as icons or container labels
        for name in ["vm-web-01", "vm-app-01", "sql-contoso", "kv-contoso"]:
            assert name in labels, f"Missing resource label '{name}'"
        # VNet and subnet names should appear as container labels
        for name in ["vnet-contoso", "snet-web", "snet-app", "snet-data"]:
            assert name in labels, f"Missing container label '{name}'"
