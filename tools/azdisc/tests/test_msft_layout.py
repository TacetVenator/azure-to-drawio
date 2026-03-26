"""Tests for the MSFT (Microsoft Architecture Center) diagram mode."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config
from tools.azdisc.drawio import (
    MSFT_CELL_H,
    MSFT_CELL_W,
    MSFT_REGION_STYLE,
    MSFT_RG_STYLE,
    extract_route_summaries,
    layout_nodes_msft,
)
from tools.azdisc.graph import (
    _collect_attributes,
    _find_parent_id,
    _is_child_resource,
    build_graph,
    build_node,
    extract_edges,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _build_graph_from_fixture(name: str = "app_contoso.json"):
    """Build graph nodes + edges from a fixture file."""
    inventory = _load_fixture(name)

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


# ── layout_nodes_msft tests ─────────────────────────────────────────────


class TestMsftLayout:
    """Verify MSFT layout geometry and container structure."""

    def test_returns_expected_tuple(self):
        nodes, edges = _build_graph_from_fixture()
        positions, containers, type_headers, node_parents = layout_nodes_msft(nodes)
        assert isinstance(positions, dict)
        assert isinstance(containers, list)
        assert isinstance(type_headers, list)
        assert isinstance(node_parents, dict)

    def test_all_nodes_have_positions(self):
        nodes, _ = _build_graph_from_fixture()
        positions, _, _, _ = layout_nodes_msft(nodes)
        for n in nodes:
            assert n["id"] in positions, f"Node {n['name']} ({n['type']}) missing position"

    def test_positions_are_non_negative(self):
        nodes, _ = _build_graph_from_fixture()
        positions, _, _, _ = layout_nodes_msft(nodes)
        for nid, (x, y, w, h) in positions.items():
            assert x >= 0, f"Node {nid} has negative x={x}"
            assert y >= 0, f"Node {nid} has negative y={y}"
            assert w == MSFT_CELL_W
            assert h == MSFT_CELL_H

    def test_no_overlapping_nodes_within_same_rg(self):
        """Nodes sharing the same RG parent must not overlap."""
        nodes, _ = _build_graph_from_fixture()
        positions, _, _, node_parents = layout_nodes_msft(nodes)

        # Group by parent RG
        by_parent = {}
        for nid, pos in positions.items():
            parent = node_parents.get(nid, "1")
            by_parent.setdefault(parent, []).append((nid, pos))

        for parent, items in by_parent.items():
            rects = [pos for _, pos in items]
            for i, (x1, y1, w1, h1) in enumerate(rects):
                for j, (x2, y2, w2, h2) in enumerate(rects):
                    if i >= j:
                        continue
                    overlap_x = x1 < x2 + w2 and x2 < x1 + w1
                    overlap_y = y1 < y2 + h2 and y2 < y1 + h1
                    assert not (overlap_x and overlap_y), (
                        f"Overlap in parent {parent}: "
                        f"({x1},{y1},{w1},{h1}) vs ({x2},{y2},{w2},{h2})"
                    )

    def test_layout_is_deterministic(self):
        nodes, _ = _build_graph_from_fixture()
        pos1, cont1, th1, np1 = layout_nodes_msft(nodes)
        pos2, cont2, th2, np2 = layout_nodes_msft(nodes)
        assert pos1 == pos2
        assert len(cont1) == len(cont2)
        for c1, c2 in zip(cont1, cont2):
            assert c1 == c2
        assert len(th1) == len(th2)
        for h1, h2 in zip(th1, th2):
            assert h1 == h2
        assert np1 == np2

    def test_stable_positions_across_runs(self):
        """Positions must be identical for the same input across separate builds."""
        nodes1, _ = _build_graph_from_fixture()
        nodes2, _ = _build_graph_from_fixture()
        pos1, _, _, _ = layout_nodes_msft(nodes1)
        pos2, _, _, _ = layout_nodes_msft(nodes2)
        assert pos1 == pos2

    def test_region_containers_exist(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_msft(nodes)
        region_containers = [c for c in containers if c["parent"] == "1"]
        assert len(region_containers) >= 1

    def test_region_container_has_correct_style(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_msft(nodes)
        region_containers = [c for c in containers if c["parent"] == "1"]
        for rc in region_containers:
            assert rc["style"] == MSFT_REGION_STYLE

    def test_rg_containers_exist(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_msft(nodes)
        rg_containers = [c for c in containers if c["parent"] != "1"]
        assert len(rg_containers) >= 1

    def test_rg_containers_have_region_parent(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_msft(nodes)
        region_ids = {c["id"] for c in containers if c["parent"] == "1"}
        rg_containers = [c for c in containers if c["parent"] != "1"]
        for rg in rg_containers:
            assert rg["parent"] in region_ids, (
                f"RG container {rg['id']} parent {rg['parent']} not a region"
            )

    def test_rg_container_has_correct_style(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_msft(nodes)
        rg_containers = [c for c in containers if c["parent"] != "1"]
        for rg in rg_containers:
            assert rg["style"] == MSFT_RG_STYLE

    def test_all_nodes_have_rg_parent(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, node_parents = layout_nodes_msft(nodes)
        rg_ids = {c["id"] for c in containers if c["parent"] != "1"}
        for n in nodes:
            parent = node_parents.get(n["id"])
            assert parent in rg_ids, (
                f"Node {n['name']} parent {parent} is not an RG container"
            )

    def test_type_headers_exist(self):
        nodes, _ = _build_graph_from_fixture()
        _, _, type_headers, _ = layout_nodes_msft(nodes)
        assert len(type_headers) > 0

    def test_type_headers_have_rg_parent(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, type_headers, _ = layout_nodes_msft(nodes)
        rg_ids = {c["id"] for c in containers if c["parent"] != "1"}
        for th in type_headers:
            assert th["parent"] in rg_ids, (
                f"Type header {th['label']} parent {th['parent']} not an RG"
            )

    def test_container_labels(self):
        nodes, _ = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_msft(nodes)
        labels = {c["label"] for c in containers}
        assert "eastus2" in labels, "Region label 'eastus2' not found"
        assert "rg-contoso-prod" in labels, "RG label 'rg-contoso-prod' not found"


# ── Route table parsing tests ────────────────────────────────────────────


class TestRouteTableParsing:
    """Verify route extraction, ordering, and UDR panel generation."""

    def test_extract_route_summaries_returns_subnets(self):
        nodes, edges = _build_graph_from_fixture()
        subnet_udr, vnet_rollup = extract_route_summaries(nodes, edges)
        assert len(subnet_udr) >= 1, "Expected at least one subnet with UDR"

    def test_route_ordering_is_deterministic(self):
        nodes, edges = _build_graph_from_fixture()
        s1, _ = extract_route_summaries(nodes, edges)
        s2, _ = extract_route_summaries(nodes, edges)
        for subnet_id in s1:
            routes1 = s1[subnet_id]["routes"]
            routes2 = s2[subnet_id]["routes"]
            assert routes1 == routes2

    def test_routes_are_sorted_by_prefix(self):
        nodes, edges = _build_graph_from_fixture()
        subnet_udr, _ = extract_route_summaries(nodes, edges)
        for subnet_id, summary in subnet_udr.items():
            routes = summary["routes"]
            prefixes = [r["addressPrefix"] for r in routes]
            assert prefixes == sorted(prefixes), (
                f"Routes not sorted by prefix: {prefixes}"
            )

    def test_each_subnet_has_exactly_one_udr_panel(self):
        nodes, edges = _build_graph_from_fixture()
        subnet_udr, _ = extract_route_summaries(nodes, edges)

        # Build the expected subnet->routeTable set
        subnet_to_rt = {}
        for e in edges:
            if e["kind"] == "subnet->routeTable":
                subnet_to_rt[e["source"]] = e["target"]

        # Each subnet with a route table should have exactly one entry
        for subnet_id in subnet_to_rt:
            assert subnet_id in subnet_udr, (
                f"Subnet {subnet_id} has route table but no UDR summary"
            )

    def test_route_summary_contains_expected_fields(self):
        nodes, edges = _build_graph_from_fixture()
        subnet_udr, _ = extract_route_summaries(nodes, edges)
        for subnet_id, summary in subnet_udr.items():
            assert "rt_name" in summary
            assert "rt_id" in summary
            assert "routes" in summary
            assert isinstance(summary["routes"], list)
            for route in summary["routes"]:
                assert "name" in route
                assert "addressPrefix" in route
                assert "nextHopType" in route
                assert "nextHopIpAddress" in route

    def test_vnet_rollup_has_subnet_names(self):
        nodes, edges = _build_graph_from_fixture()
        _, vnet_rollup = extract_route_summaries(nodes, edges)
        assert len(vnet_rollup) >= 1
        for vnet_id, subnet_names in vnet_rollup.items():
            assert len(subnet_names) >= 1
            for name in subnet_names:
                assert isinstance(name, str)

    def test_contoso_fixture_routes(self):
        """Verify the specific route table from the contoso fixture."""
        nodes, edges = _build_graph_from_fixture()
        subnet_udr, _ = extract_route_summaries(nodes, edges)

        # Find the snet-app subnet
        snet_app_entries = [
            (sid, s) for sid, s in subnet_udr.items()
            if "snet-app" in sid
        ]
        assert len(snet_app_entries) == 1, "Expected exactly one snet-app UDR"
        _, summary = snet_app_entries[0]
        assert summary["rt_name"] == "rt-app"
        assert len(summary["routes"]) == 2

        # First route (sorted by prefix): 0.0.0.0/0
        assert summary["routes"][0]["addressPrefix"] == "0.0.0.0/0"
        assert summary["routes"][0]["nextHopType"] == "VirtualAppliance"
        assert summary["routes"][0]["nextHopIpAddress"] == "10.10.0.4"

        # Second route: 10.10.3.0/24
        assert summary["routes"][1]["addressPrefix"] == "10.10.3.0/24"
        assert summary["routes"][1]["nextHopType"] == "VnetLocal"


# ── MSFT mode integration tests ──────────────────────────────────────────


def _seed_output_files(tmp_path: Path) -> None:
    fixture = FIXTURES / "app_contoso.json"
    (tmp_path / "inventory.json").write_text(fixture.read_text())
    (tmp_path / "unresolved.json").write_text("[]")


def _make_msft_config(tmp_path: Path) -> Config:
    return Config(
        app="contoso-msft",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        diagramMode="MSFT",
    )


class TestMsftDrawioGeneration:
    """Integration tests for the full MSFT mode pipeline."""

    def _generate(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_msft_config(tmp_path)
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

    def test_drawio_has_region_containers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        region_containers = [
            c for c in containers
            if "dashed=1" in (c.get("style") or "")
            and (c.get("id") or "").startswith("msft_region_")
        ]
        assert len(region_containers) >= 1

    def test_drawio_has_rg_containers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        rg_containers = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_rg_")
        ]
        assert len(rg_containers) >= 1

    def test_hierarchical_parenting(self, tmp_path):
        """RG containers should be children of region containers."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")

        region_ids = {
            c.get("id") for c in containers
            if (c.get("id") or "").startswith("msft_region_")
        }
        rg_containers_list = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_rg_")
        ]

        for rg in rg_containers_list:
            assert rg.get("parent") in region_ids, (
                f"RG {rg.get('id')} parent={rg.get('parent')} not a region"
            )

    def test_resource_nodes_use_resources_layer(self, tmp_path):
        """Resource cells should be emitted on the Resources layer."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))

        # Non-container vertex cells (excluding id=0, id=1, containers, headers)
        all_vertices = tree.findall(".//mxCell[@vertex='1']")
        # Boundary nodes (Internet, On-Premises) are parented to root, not RGs
        boundary_labels = {"Internet", "On-Premises"}
        resource_cells = [
            v for v in all_vertices
            if v.get("connectable") != "0"
            and v.get("id") not in ("0", "1")
            and not v.get("id", "").startswith("msft_th_")
            and not v.get("id", "").startswith("msft_udr_")
            and not v.get("id", "").startswith("msft_nsg_")
            and not v.get("id", "").startswith("attr_")
            and not v.get("id", "").endswith("inventory_box")
            and not v.get("id", "").endswith("network_legend")
            and v.get("value") not in boundary_labels
        ]

        for cell in resource_cells:
            assert cell.get("parent") == "layer_resources", (
                f"Resource {cell.get('value')} parent={cell.get('parent')} not Resources layer"
            )

    def test_drawio_contains_vertex_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = [
            v for v in tree.findall(".//mxCell[@vertex='1']")
            if v.get("connectable") != "0"
        ]
        assert len(vertices) >= 15, f"Expected >=15 vertex cells, got {len(vertices)}"

    def test_drawio_contains_edge_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        assert len(edges) >= 5, f"Expected >=5 edge cells, got {len(edges)}"

    def test_drawio_has_type_section_headers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        all_vertices = tree.findall(".//mxCell[@vertex='1']")
        headers = [
            v for v in all_vertices
            if v.get("id", "").startswith("msft_th_")
        ]
        assert len(headers) > 0, "Expected type section headers in MSFT mode"
        # Check that typical categories exist
        labels = {h.get("value") for h in headers}
        assert "Compute" in labels or "Networking" in labels, (
            f"Expected Compute or Networking header, got {labels}"
        )

    def test_drawio_has_udr_panels(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        all_vertices = tree.findall(".//mxCell[@vertex='1']")
        udr_panels = [
            v for v in all_vertices
            if v.get("id", "").startswith("msft_udr_")
        ]
        assert len(udr_panels) >= 1, "Expected at least one UDR panel"
        # Verify panel content
        panel_text = udr_panels[0].get("value", "")
        assert "UDR:" in panel_text

    def test_drawio_has_udr_edges(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        udr_edges = [e for e in edges if "udr_detail" in (e.get("value") or "")]
        assert len(udr_edges) >= 1

    def test_icons_used_json(self, tmp_path):
        self._generate(tmp_path)
        icons_path = tmp_path / "icons_used.json"
        assert icons_path.exists()
        data = json.loads(icons_path.read_text())
        assert "mapped" in data
        assert "unknown" in data
        assert isinstance(data["mapped"], dict)
        assert isinstance(data["unknown"], list)

    def test_expected_labels_present(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        for name in ["vm-web-01", "vm-app-01", "sql-contoso", "kv-contoso"]:
            assert name in labels, f"Missing resource label '{name}'"

    def test_orthogonal_edge_style(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        for e in edges:
            style = e.get("style", "")
            assert "orthogonalEdgeStyle" in style, (
                f"Edge {e.get('id')} missing orthogonal style"
            )


# ── Snapshot test ─────────────────────────────────────────────────────────


class TestMsftSnapshot:
    """Verify stable XML output from fixture data (idempotent generation)."""

    def _generate_xml(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_msft_config(tmp_path)
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        return (tmp_path / "diagram.drawio").read_text()

    def test_stable_xml_across_runs(self, tmp_path):
        """Two generations from the same input must produce identical XML."""
        import tempfile

        xml1 = self._generate_xml(tmp_path)

        with tempfile.TemporaryDirectory() as tmp2:
            xml2 = self._generate_xml(Path(tmp2))

        assert xml1 == xml2, "MSFT mode output is not deterministic"

    def test_stable_hash(self, tmp_path):
        """The hash of the output XML must be stable."""
        xml1 = self._generate_xml(tmp_path)
        h1 = hashlib.sha256(xml1.encode()).hexdigest()

        import tempfile
        with tempfile.TemporaryDirectory() as tmp2:
            xml2 = self._generate_xml(Path(tmp2))
        h2 = hashlib.sha256(xml2.encode()).hexdigest()

        assert h1 == h2, "XML hash not stable across runs"
