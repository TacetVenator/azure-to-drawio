"""Tests for the SUB>REGION>RG>NET layout and new edge extraction."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config
from tools.azdisc.drawio import (
    MSFT_CELL_H,
    MSFT_CELL_W,
    MSFT_RG_STYLE,
    MSFT_REGION_STYLE,
    MSFT_SUB_STYLE,
    layout_nodes_sub_rg_net,
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


def _build_graph_from_fixture(name: str = "app_landing_zone.json"):
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


# ── Edge extraction tests for new resource types ────────────────────────


class TestNewEdges:
    """Verify edge extraction for firewall, bastion, container apps, app insights."""

    def test_firewall_subnet_edge(self):
        nodes, edges = _build_graph_from_fixture()
        fw_subnet = [e for e in edges if e["kind"] == "firewall->subnet"]
        assert len(fw_subnet) >= 1, "Expected firewall->subnet edge"

    def test_firewall_publicip_edge(self):
        nodes, edges = _build_graph_from_fixture()
        fw_pip = [e for e in edges if e["kind"] == "firewall->publicIp"]
        assert len(fw_pip) >= 1, "Expected firewall->publicIp edge"

    def test_bastion_subnet_edge(self):
        nodes, edges = _build_graph_from_fixture()
        bastion_subnet = [e for e in edges if e["kind"] == "bastion->subnet"]
        assert len(bastion_subnet) >= 1, "Expected bastion->subnet edge"

    def test_bastion_publicip_edge(self):
        nodes, edges = _build_graph_from_fixture()
        bastion_pip = [e for e in edges if e["kind"] == "bastion->publicIp"]
        assert len(bastion_pip) >= 1, "Expected bastion->publicIp edge"

    def test_container_app_environment_edge(self):
        nodes, edges = _build_graph_from_fixture()
        ca_env = [e for e in edges if e["kind"] == "containerApp->environment"]
        assert len(ca_env) >= 2, "Expected at least 2 containerApp->environment edges"

    def test_container_env_subnet_edge(self):
        nodes, edges = _build_graph_from_fixture()
        env_subnet = [e for e in edges if e["kind"] == "containerEnv->subnet"]
        assert len(env_subnet) >= 1, "Expected containerEnv->subnet edge"

    def test_app_insights_workspace_edge(self):
        nodes, edges = _build_graph_from_fixture()
        ai_ws = [e for e in edges if e["kind"] == "appInsights->workspace"]
        assert len(ai_ws) >= 1, "Expected appInsights->workspace edge"

    def test_vnet_peering_edges(self):
        """Hub should peer to both spokes; spokes should peer back to hub."""
        nodes, edges = _build_graph_from_fixture()
        peerings = [e for e in edges if e["kind"] == "vnet->peeredVnet"]
        # hub -> app-spoke, hub -> data-spoke, app-spoke -> hub, data-spoke -> hub
        assert len(peerings) >= 4, f"Expected >=4 vnet peering edges, got {len(peerings)}"

    def test_private_endpoint_edges(self):
        nodes, edges = _build_graph_from_fixture()
        pe_subnet = [e for e in edges if e["kind"] == "privateEndpoint->subnet"]
        pe_target = [e for e in edges if e["kind"] == "privateEndpoint->target"]
        assert len(pe_subnet) >= 4, f"Expected >=4 PE->subnet edges, got {len(pe_subnet)}"
        assert len(pe_target) >= 4, f"Expected >=4 PE->target edges, got {len(pe_target)}"


# ── layout_nodes_sub_rg_net tests ───────────────────────────────────────


class TestSubRgNetLayout:
    """Verify SUB>REGION>RG>NET layout geometry and container hierarchy."""

    def test_returns_expected_tuple(self):
        nodes, edges = _build_graph_from_fixture()
        positions, containers, type_headers, node_parents = layout_nodes_sub_rg_net(nodes, edges)
        assert isinstance(positions, dict)
        assert isinstance(containers, list)
        assert isinstance(type_headers, list)
        assert isinstance(node_parents, dict)

    def test_all_nodes_have_positions(self):
        nodes, edges = _build_graph_from_fixture()
        positions, _, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        for n in nodes:
            assert n["id"] in positions, f"Node {n['name']} ({n['type']}) missing position"

    def test_positions_are_non_negative(self):
        nodes, edges = _build_graph_from_fixture()
        positions, _, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        for nid, (x, y, w, h) in positions.items():
            assert x >= 0, f"Node {nid} has negative x={x}"
            assert y >= 0, f"Node {nid} has negative y={y}"
            assert w == MSFT_CELL_W
            assert h == MSFT_CELL_H

    def test_no_overlapping_nodes_within_same_rg(self):
        nodes, edges = _build_graph_from_fixture()
        positions, _, _, node_parents = layout_nodes_sub_rg_net(nodes, edges)

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
        nodes, edges = _build_graph_from_fixture()
        pos1, cont1, th1, np1 = layout_nodes_sub_rg_net(nodes, edges)
        pos2, cont2, th2, np2 = layout_nodes_sub_rg_net(nodes, edges)
        assert pos1 == pos2
        assert len(cont1) == len(cont2)
        for c1, c2 in zip(cont1, cont2):
            assert c1 == c2
        assert np1 == np2

    def test_subscription_containers_exist(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        sub_containers = [c for c in containers if c["parent"] == "1"]
        # 3 subscriptions in the landing zone fixture
        assert len(sub_containers) == 3, f"Expected 3 subscription containers, got {len(sub_containers)}"

    def test_subscription_container_style(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        sub_containers = [c for c in containers if c["parent"] == "1"]
        for sc in sub_containers:
            assert sc["style"] == MSFT_SUB_STYLE

    def test_region_containers_exist(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        sub_ids = {c["id"] for c in containers if c["parent"] == "1"}
        region_containers = [c for c in containers if c["parent"] in sub_ids]
        assert len(region_containers) >= 1

    def test_region_containers_have_sub_parent(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        sub_ids = {c["id"] for c in containers if c["parent"] == "1"}
        region_containers = [
            c for c in containers
            if c["style"] == MSFT_REGION_STYLE
        ]
        for rc in region_containers:
            assert rc["parent"] in sub_ids, (
                f"Region container {rc['id']} parent {rc['parent']} not a subscription"
            )

    def test_rg_containers_have_region_parent(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        sub_ids = {c["id"] for c in containers if c["parent"] == "1"}
        region_ids = {c["id"] for c in containers if c["parent"] in sub_ids}
        rg_containers = [c for c in containers if c["style"] == MSFT_RG_STYLE]
        for rg in rg_containers:
            assert rg["parent"] in region_ids, (
                f"RG container {rg['id']} parent {rg['parent']} not a region"
            )

    def test_all_nodes_have_rg_parent(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, node_parents = layout_nodes_sub_rg_net(nodes, edges)
        rg_ids = {c["id"] for c in containers if c["style"] == MSFT_RG_STYLE}
        for n in nodes:
            parent = node_parents.get(n["id"])
            assert parent in rg_ids, (
                f"Node {n['name']} parent {parent} is not an RG container"
            )

    def test_networking_section_headers_exist(self):
        nodes, edges = _build_graph_from_fixture()
        _, _, type_headers, _ = layout_nodes_sub_rg_net(nodes, edges)
        networking_headers = [th for th in type_headers if th["label"] == "Networking"]
        # At least connectivity RG and app RG should have networking sections
        assert len(networking_headers) >= 2, (
            f"Expected >=2 Networking headers, got {len(networking_headers)}"
        )

    def test_resources_section_headers_exist(self):
        nodes, edges = _build_graph_from_fixture()
        _, _, type_headers, _ = layout_nodes_sub_rg_net(nodes, edges)
        resource_headers = [th for th in type_headers if th["label"] == "Resources"]
        assert len(resource_headers) >= 1

    def test_container_labels_include_subscription(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        sub_containers = [c for c in containers if c["parent"] == "1"]
        labels = {c["label"] for c in sub_containers}
        # All should start with "Subscription"
        for label in labels:
            assert "Subscription" in label, f"Subscription label missing: {label}"

    def test_container_labels_include_rg_names(self):
        nodes, edges = _build_graph_from_fixture()
        _, containers, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        labels = {c["label"] for c in containers}
        assert "rg-connectivity-prod" in labels
        assert "rg-app-prod" in labels
        assert "rg-data-prod" in labels

    def test_works_with_single_subscription(self):
        """Should also work with the contoso fixture (single subscription)."""
        nodes, edges = _build_graph_from_fixture("app_contoso.json")
        positions, containers, _, node_parents = layout_nodes_sub_rg_net(nodes, edges)
        sub_containers = [c for c in containers if c["parent"] == "1"]
        assert len(sub_containers) == 1
        assert len(positions) == len(nodes)

    def test_works_with_ai_chatbot_fixture(self):
        """Should also work with the ai_chatbot fixture (hub-spoke, single sub)."""
        nodes, edges = _build_graph_from_fixture("app_ai_chatbot.json")
        positions, containers, _, node_parents = layout_nodes_sub_rg_net(nodes, edges)
        assert len(positions) == len(nodes)
        # Should have subscription + region + 2 RGs
        sub_containers = [c for c in containers if c["parent"] == "1"]
        assert len(sub_containers) >= 1


# ── Full pipeline integration tests ─────────────────────────────────────


def _seed_output_files(tmp_path: Path, fixture: str = "app_landing_zone.json"):
    f = FIXTURES / fixture
    (tmp_path / "inventory.json").write_text(f.read_text())
    (tmp_path / "unresolved.json").write_text("[]")


def _make_sub_rg_net_config(tmp_path: Path) -> Config:
    return Config(
        app="landing-zone",
        subscriptions=[
            "00000000-aaaa-0000-0000-000000000001",
            "00000000-bbbb-0000-0000-000000000002",
            "00000000-cccc-0000-0000-000000000003",
        ],
        seedResourceGroups=["rg-connectivity-prod", "rg-app-prod", "rg-data-prod"],
        outputDir=str(tmp_path),
        layout="SUB>REGION>RG>NET",
        diagramMode="MSFT",
    )


class TestSubRgNetDrawioGeneration:
    """Integration tests for the full SUB>REGION>RG>NET pipeline."""

    def _generate(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_sub_rg_net_config(tmp_path)
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

    def test_drawio_has_subscription_containers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        sub_containers = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_sub_")
        ]
        assert len(sub_containers) == 3, (
            f"Expected 3 subscription containers, got {len(sub_containers)}"
        )

    def test_drawio_has_region_containers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        region_containers = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_region_")
        ]
        assert len(region_containers) >= 3

    def test_drawio_has_rg_containers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        rg_containers = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_rg_")
        ]
        assert len(rg_containers) >= 3

    def test_hierarchical_parenting_sub_to_region(self, tmp_path):
        """Region containers should be children of subscription containers."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")

        sub_ids = {
            c.get("id") for c in containers
            if (c.get("id") or "").startswith("msft_sub_")
        }
        region_containers = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_region_")
        ]

        for rc in region_containers:
            assert rc.get("parent") in sub_ids, (
                f"Region {rc.get('id')} parent={rc.get('parent')} not a subscription"
            )

    def test_hierarchical_parenting_region_to_rg(self, tmp_path):
        """RG containers should be children of region containers."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")

        region_ids = {
            c.get("id") for c in containers
            if (c.get("id") or "").startswith("msft_region_")
        }
        rg_containers = [
            c for c in containers
            if (c.get("id") or "").startswith("msft_rg_")
        ]

        for rg in rg_containers:
            assert rg.get("parent") in region_ids, (
                f"RG {rg.get('id')} parent={rg.get('parent')} not a region"
            )

    def test_drawio_contains_vertex_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = [
            v for v in tree.findall(".//mxCell[@vertex='1']")
            if v.get("connectable") != "0"
        ]
        assert len(vertices) >= 20, f"Expected >=20 vertex cells, got {len(vertices)}"

    def test_drawio_contains_edge_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        assert len(edges) >= 5, f"Expected >=5 edge cells, got {len(edges)}"

    def test_expected_labels_present(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        for name in ["fw-hub", "bastion-hub", "vnet-hub", "ca-api", "sql-data", "kv-app"]:
            assert name in labels, f"Missing resource label '{name}'"

    def test_icons_used_json(self, tmp_path):
        self._generate(tmp_path)
        icons_path = tmp_path / "icons_used.json"
        assert icons_path.exists()
        data = json.loads(icons_path.read_text())
        assert "mapped" in data
        assert "unknown" in data

    def test_stable_xml_across_runs(self, tmp_path):
        """Two generations must produce identical XML."""
        import tempfile

        _seed_output_files(tmp_path)
        cfg = _make_sub_rg_net_config(tmp_path)
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        xml1 = (tmp_path / "diagram.drawio").read_text()

        with tempfile.TemporaryDirectory() as tmp2:
            tmp2_path = Path(tmp2)
            _seed_output_files(tmp2_path)
            cfg2 = _make_sub_rg_net_config(tmp2_path)
            build_graph(cfg2)
            generate_drawio(cfg2)
            xml2 = (tmp2_path / "diagram.drawio").read_text()

        assert xml1 == xml2, "SUB>REGION>RG>NET output is not deterministic"

    def test_bands_mode_also_works(self, tmp_path):
        """SUB>REGION>RG>NET layout should also work with BANDS mode."""
        _seed_output_files(tmp_path)
        cfg = Config(
            app="landing-zone-bands",
            subscriptions=["00000000-aaaa-0000-0000-000000000001"],
            seedResourceGroups=["rg-connectivity-prod"],
            outputDir=str(tmp_path),
            layout="SUB>REGION>RG>NET",
            diagramMode="BANDS",
        )
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        assert (tmp_path / "diagram.drawio").exists()
