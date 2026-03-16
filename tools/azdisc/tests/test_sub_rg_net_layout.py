"""Tests for the SUB>REGION>RG>NET layout and new edge extraction."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config, load_config
from tools.azdisc.drawio import (
    MSFT_CELL_H,
    MSFT_CELL_W,
    MSFT_NET_SECTION_STYLE,
    MSFT_RG_STYLE,
    MSFT_REGION_STYLE,
    MSFT_SUB_STYLE,
    NSG_CALLOUT_STYLE,
    _NETWORK_TYPES,
    _edge_style,
    _inject_boundary_nodes,
    _subscription_label,
    extract_nsg_summaries,
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


def _make_sub_rg_net_config(tmp_path: Path, diagram_mode: str = "MSFT") -> Config:
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
        diagramMode=diagram_mode,
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

    def test_bands_and_msft_produce_different_output(self, tmp_path):
        """BANDS and MSFT modes should produce different diagrams for SUB>REGION>RG>NET."""
        import tempfile

        _seed_output_files(tmp_path)
        cfg_msft = _make_sub_rg_net_config(tmp_path)
        build_graph(cfg_msft)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg_msft)
        xml_msft = (tmp_path / "diagram.drawio").read_text()

        with tempfile.TemporaryDirectory() as tmp2:
            tmp2_path = Path(tmp2)
            _seed_output_files(tmp2_path)
            cfg_bands = Config(
                app="landing-zone-bands",
                subscriptions=cfg_msft.subscriptions,
                seedResourceGroups=cfg_msft.seedResourceGroups,
                outputDir=str(tmp2_path),
                layout="SUB>REGION>RG>NET",
                diagramMode="BANDS",
            )
            build_graph(cfg_bands)
            generate_drawio(cfg_bands)
            xml_bands = (tmp2_path / "diagram.drawio").read_text()

        assert xml_msft != xml_bands, (
            "BANDS and MSFT modes should produce different XML for SUB>REGION>RG>NET"
        )

    def test_bands_mode_has_flat_containers(self, tmp_path):
        """BANDS mode containers should all be parented to root (flat)."""
        _seed_output_files(tmp_path)
        cfg = Config(
            app="landing-zone-bands",
            subscriptions=["00000000-aaaa-0000-0000-000000000001",
                           "00000000-bbbb-0000-0000-000000000002",
                           "00000000-cccc-0000-0000-000000000003"],
            seedResourceGroups=["rg-connectivity-prod", "rg-app-prod", "rg-data-prod"],
            outputDir=str(tmp_path),
            layout="SUB>REGION>RG>NET",
            diagramMode="BANDS",
        )
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)

        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        valid_parents = {"1", "layer_containers"}
        for c in containers:
            assert c.get("parent") in valid_parents, (
                f"BANDS container {c.get('id')} should have parent in {valid_parents}, "
                f"got '{c.get('parent')}'"
            )


# ── _subscription_label unit tests ───────────────────────────────────────


class TestSubscriptionLabel:
    """Verify the _subscription_label helper produces correct labels."""

    def test_normal_guid(self):
        label = _subscription_label("00000000-aaaa-0000-0000-000000000001", [])
        assert label == "Subscription ...00000001"

    def test_short_id(self):
        label = _subscription_label("abc", [])
        assert label == "Subscription ...abc"

    def test_empty_string(self):
        label = _subscription_label("", [])
        assert label == "Unknown Subscription"

    def test_unknown_string(self):
        label = _subscription_label("unknown", [])
        assert label == "Unknown Subscription"

    def test_none_value(self):
        label = _subscription_label(None, [])
        assert label == "Unknown Subscription"


# ── _NETWORK_TYPES classification tests ──────────────────────────────────


class TestNetworkTypesClassification:
    """Verify that _NETWORK_TYPES correctly classifies resources."""

    def test_all_expected_types_present(self):
        expected = {
            "microsoft.network/virtualnetworks",
            "microsoft.network/virtualnetworks/subnets",
            "microsoft.network/networksecuritygroups",
            "microsoft.network/applicationsecuritygroups",
            "microsoft.network/routetables",
            "microsoft.network/azurefirewalls",
            "microsoft.network/bastionhosts",
            "microsoft.network/applicationgateways",
            "microsoft.network/loadbalancers",
            "microsoft.network/publicipaddresses",
            "microsoft.network/privateendpoints",
            "microsoft.network/networkinterfaces",
            "microsoft.network/natgateways",
            "microsoft.network/firewallpolicies",
            "microsoft.network/virtualnetworkgateways",
            "microsoft.network/localnetworkgateways",
            "microsoft.network/connections",
        }
        assert _NETWORK_TYPES == expected

    def test_non_network_types_excluded(self):
        non_network = [
            "microsoft.compute/virtualmachines",
            "microsoft.sql/servers",
            "microsoft.keyvault/vaults",
            "microsoft.app/containerapps",
            "microsoft.storage/storageaccounts",
            "microsoft.containerregistry/registries",
            "microsoft.insights/components",
        ]
        for t in non_network:
            assert t not in _NETWORK_TYPES, f"{t} should not be in _NETWORK_TYPES"

    def test_networking_resources_in_networking_section(self):
        """Networking resources should end up under 'Networking' headers in layout."""
        nodes, edges = _build_graph_from_fixture()
        _, _, type_headers, _ = layout_nodes_sub_rg_net(nodes, edges)

        net_headers = [th for th in type_headers if th["label"] == "Networking"]
        assert len(net_headers) >= 1

        # Check that sub-headers under networking have network type names
        net_parent_ids = {th["parent"] for th in net_headers}
        # For each RG that has networking, there should be sub-headers for specific types
        for rg_id in net_parent_ids:
            rg_sub_headers = [
                th for th in type_headers
                if th["parent"] == rg_id and th["label"] not in ("Networking", "Resources")
            ]
            assert len(rg_sub_headers) >= 1, f"No type sub-headers in RG {rg_id}"


# ── Cross-subscription edge tests ────────────────────────────────────────


class TestCrossSubscriptionEdges:
    """Verify edges that cross subscription boundaries."""

    def test_vnet_peering_crosses_subscriptions(self):
        nodes, edges = _build_graph_from_fixture()
        peerings = [e for e in edges if e["kind"] == "vnet->peeredVnet"]
        # Hub (sub aaaa) -> spoke-app (sub bbbb)
        cross_sub = [
            e for e in peerings
            if "aaaa" in e["source"] and "bbbb" in e["target"]
            or "bbbb" in e["source"] and "aaaa" in e["target"]
        ]
        assert len(cross_sub) >= 2, "Expected cross-sub peering edges between hub and app-spoke"

    def test_app_insights_crosses_subscriptions(self):
        """App Insights in sub bbbb -> Log Analytics workspace in sub aaaa."""
        nodes, edges = _build_graph_from_fixture()
        ai_ws = [e for e in edges if e["kind"] == "appInsights->workspace"]
        assert len(ai_ws) >= 1
        for e in ai_ws:
            assert "bbbb" in e["source"], "App Insights should be in sub bbbb"
            assert "aaaa" in e["target"], "Workspace should be in sub aaaa"

    def test_cross_sub_edges_in_xml(self):
        """Cross-subscription edges should appear as edge cells in the XML."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _seed_output_files(tmp_path)
            cfg = _make_sub_rg_net_config(tmp_path)
            build_graph(cfg)
            from tools.azdisc.drawio import generate_drawio
            generate_drawio(cfg)

            tree = ET.parse(str(tmp_path / "diagram.drawio"))
            edge_cells = tree.findall(".//mxCell[@edge='1']")
            assert len(edge_cells) >= 5, "Expected cross-subscription edge cells in XML"

            # Verify edges have source and target attributes
            for ec in edge_cells:
                assert ec.get("source"), f"Edge {ec.get('id')} missing source"
                assert ec.get("target"), f"Edge {ec.get('id')} missing target"


# ── Spacing parameter tests ──────────────────────────────────────────────


class TestSpacingParameter:
    """Verify spacing parameter affects layout dimensions."""

    def test_spacious_layout_is_larger(self):
        nodes, edges = _build_graph_from_fixture()
        pos_compact, cont_compact, _, _ = layout_nodes_sub_rg_net(nodes, edges, spacing=1.0)
        pos_spacious, cont_spacious, _, _ = layout_nodes_sub_rg_net(nodes, edges, spacing=1.8)

        # Spacious containers should be larger
        for cc, cs in zip(
            sorted(cont_compact, key=lambda c: c["id"]),
            sorted(cont_spacious, key=lambda c: c["id"]),
        ):
            assert cs["w"] >= cc["w"], f"Spacious container {cc['id']} should be wider"
            assert cs["h"] >= cc["h"], f"Spacious container {cc['id']} should be taller"

    def test_default_spacing_is_1(self):
        nodes, edges = _build_graph_from_fixture()
        pos1, cont1, _, _ = layout_nodes_sub_rg_net(nodes, edges)
        pos2, cont2, _, _ = layout_nodes_sub_rg_net(nodes, edges, spacing=1.0)
        assert pos1 == pos2
        assert len(cont1) == len(cont2)


# ── Config validation tests ──────────────────────────────────────────────


class TestConfigValidation:
    """Verify SUB>REGION>RG>NET is accepted in config."""

    def test_sub_rg_net_in_valid_layouts(self):
        from tools.azdisc.config import VALID_LAYOUTS
        assert "SUB>REGION>RG>NET" in VALID_LAYOUTS

    def test_config_accepts_sub_rg_net_layout(self):
        cfg = Config(
            app="test",
            subscriptions=["sub1"],
            seedResourceGroups=["rg1"],
            outputDir="/tmp/test",
            layout="SUB>REGION>RG>NET",
        )
        assert cfg.layout == "SUB>REGION>RG>NET"

    def test_config_file_with_sub_rg_net(self, tmp_path):
        config_data = {
            "app": "test-app",
            "subscriptions": ["sub1"],
            "seedResourceGroups": ["rg1"],
            "outputDir": str(tmp_path),
            "layout": "SUB>REGION>RG>NET",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        cfg = load_config(str(config_file))
        assert cfg.layout == "SUB>REGION>RG>NET"

    def test_invalid_layout_rejected(self, tmp_path):
        config_data = {
            "app": "test-app",
            "subscriptions": ["sub1"],
            "seedResourceGroups": ["rg1"],
            "outputDir": str(tmp_path),
            "layout": "INVALID>LAYOUT",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        with pytest.raises(ValueError, match="Unsupported layout"):
            load_config(str(config_file))


# ── Edge case tests ──────────────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases for the SUB>REGION>RG>NET layout."""

    def test_empty_inventory(self):
        """Layout should handle zero nodes gracefully."""
        positions, containers, type_headers, node_parents = layout_nodes_sub_rg_net([], [])
        assert positions == {}
        assert containers == []
        assert type_headers == []
        assert node_parents == {}

    def test_single_node(self):
        """Layout should handle a single node."""
        node = build_node({
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "name": "vm1",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "westeurope",
            "subscriptionId": "sub1",
            "resourceGroup": "rg1",
        })
        node["attributes"] = []
        positions, containers, type_headers, node_parents = layout_nodes_sub_rg_net([node], [])
        assert len(positions) == 1
        assert node["id"] in positions
        # Should have sub + region + RG = 3 containers
        assert len(containers) == 3
        sub_containers = [c for c in containers if c["parent"] == "1"]
        assert len(sub_containers) == 1

    def test_only_networking_resources(self):
        """An RG with only network resources should have Networking header but no Resources header."""
        # Build nodes from connectivity RG only (all networking)
        full_nodes, full_edges = _build_graph_from_fixture()
        conn_nodes = [n for n in full_nodes if n["resourceGroup"] == "rg-connectivity-prod"]

        # Filter edges to only those with both ends in conn_nodes
        conn_ids = {n["id"] for n in conn_nodes}
        conn_edges = [e for e in full_edges if e["source"] in conn_ids]

        positions, containers, type_headers, node_parents = layout_nodes_sub_rg_net(conn_nodes, conn_edges)

        # Get RG containers
        rg_containers = [c for c in containers if c["style"] == MSFT_RG_STYLE]
        assert len(rg_containers) >= 1

        # There should be a Networking header but check for Resources
        rg_ids = {c["id"] for c in rg_containers}
        net_headers = [th for th in type_headers if th["label"] == "Networking" and th["parent"] in rg_ids]

        # The connectivity RG has law-platform (non-network), so Resources header should exist
        # But the networking section should exist too
        assert len(net_headers) >= 1

    def test_missing_subscription_id(self):
        """Nodes without subscriptionId should be grouped under 'unknown'."""
        node = build_node({
            "id": "/subscriptions/unknown/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "name": "vm1",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "westeurope",
            "resourceGroup": "rg1",
        })
        node["attributes"] = []
        positions, containers, _, _ = layout_nodes_sub_rg_net([node], [])
        assert len(positions) == 1
        sub_containers = [c for c in containers if c["parent"] == "1"]
        assert len(sub_containers) == 1
        assert "Unknown Subscription" in sub_containers[0]["label"]

    def test_multiple_regions_in_one_subscription(self):
        """Nodes in different regions should create separate region containers."""
        nodes = []
        for region in ["westeurope", "eastus"]:
            n = build_node({
                "id": f"/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm-{region}",
                "name": f"vm-{region}",
                "type": "Microsoft.Compute/virtualMachines",
                "location": region,
                "subscriptionId": "sub1",
                "resourceGroup": "rg1",
            })
            n["attributes"] = []
            nodes.append(n)

        positions, containers, _, _ = layout_nodes_sub_rg_net(nodes, [])
        assert len(positions) == 2

        sub_ids = {c["id"] for c in containers if c["parent"] == "1"}
        assert len(sub_ids) == 1  # One subscription

        region_containers = [c for c in containers if c["parent"] in sub_ids]
        assert len(region_containers) == 2  # Two regions
        region_labels = {c["label"] for c in region_containers}
        assert "westeurope" in region_labels
        assert "eastus" in region_labels

    def test_networking_section_style(self):
        """Networking section headers should use MSFT_NET_SECTION_STYLE."""
        nodes, edges = _build_graph_from_fixture()
        _, _, type_headers, _ = layout_nodes_sub_rg_net(nodes, edges)
        net_headers = [th for th in type_headers if th["label"] == "Networking"]
        for nh in net_headers:
            assert nh.get("style") == MSFT_NET_SECTION_STYLE

    def test_type_sub_headers_under_resources(self):
        """Resources section should have category sub-headers."""
        nodes, edges = _build_graph_from_fixture()
        _, containers, type_headers, _ = layout_nodes_sub_rg_net(nodes, edges)

        # Find app RG which has both networking and non-networking resources
        app_rg = [c for c in containers if c["label"] == "rg-app-prod"]
        assert len(app_rg) == 1
        app_rg_id = app_rg[0]["id"]

        # Get headers for this RG
        rg_headers = [th for th in type_headers if th["parent"] == app_rg_id]
        labels = [th["label"] for th in rg_headers]
        assert "Networking" in labels
        assert "Resources" in labels

    def test_node_count_matches_positions(self):
        """Every node from fixture should have a position."""
        for fixture in ["app_landing_zone.json", "app_contoso.json", "app_ai_chatbot.json"]:
            nodes, edges = _build_graph_from_fixture(fixture)
            positions, _, _, _ = layout_nodes_sub_rg_net(nodes, edges)
            assert len(positions) == len(nodes), (
                f"Fixture {fixture}: {len(positions)} positions vs {len(nodes)} nodes"
            )

    def test_cols_parameter_limits_row_width(self):
        """Setting cols=3 should place at most 3 nodes per row."""
        nodes, edges = _build_graph_from_fixture()
        positions, _, _, node_parents = layout_nodes_sub_rg_net(nodes, edges, cols=3)

        # Group by parent
        by_parent = {}
        for nid, pos in positions.items():
            parent = node_parents.get(nid, "1")
            by_parent.setdefault(parent, []).append(pos)

        # No parent group should have >3 distinct x values in any y row
        for parent, pos_list in by_parent.items():
            y_groups = {}
            for x, y, w, h in pos_list:
                y_groups.setdefault(y, set()).add(x)
            for y, x_vals in y_groups.items():
                assert len(x_vals) <= 3, (
                    f"Parent {parent} has {len(x_vals)} columns at y={y}, expected <=3"
                )


# ── Edge style differentiation tests ──────────────────────────────────


class TestEdgeStyleDifferentiation:
    """Verify edges use different styles based on semantic type."""

    def test_traffic_edge_style(self):
        style = _edge_style("vm->nic", msft=False)
        assert "strokeColor=#333333" in style
        assert "dashed" not in style

    def test_association_edge_style(self):
        style = _edge_style("subnet->nsg", msft=False)
        assert "dashed=1" in style
        assert "strokeColor=#999999" in style

    def test_peering_edge_style(self):
        style = _edge_style("vnet->peeredVnet", msft=False)
        assert "strokeColor=#0078D4" in style
        assert "strokeWidth=2" in style

    def test_msft_traffic_edge_style(self):
        style = _edge_style("firewall->subnet", msft=True)
        assert "strokeColor=#333333" in style
        assert "html=1" in style

    def test_msft_association_edge_style(self):
        style = _edge_style("subnet->routeTable", msft=True)
        assert "dashed=1" in style
        assert "html=1" in style

    def test_msft_peering_edge_style(self):
        style = _edge_style("vnet->peeredVnet", msft=True)
        assert "strokeColor=#0078D4" in style
        assert "html=1" in style

    def test_edges_in_xml_have_differentiated_styles(self, tmp_path):
        """Generated XML should have different styles for different edge kinds."""
        _seed_output_files(tmp_path)
        cfg = _make_sub_rg_net_config(tmp_path)
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)

        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edge_cells = tree.findall(".//mxCell[@edge='1']")
        styles = {ec.get("style") for ec in edge_cells}
        # Should have at least 2 different edge styles
        assert len(styles) >= 2, f"Expected >= 2 edge styles, got {len(styles)}: {styles}"


# ── Boundary node tests ──────────────────────────────────────────────


class TestBoundaryNodes:
    """Verify Internet/On-Premises boundary nodes are injected correctly."""

    def test_internet_boundary_added_when_pip_exists(self):
        nodes, edges = _build_graph_from_fixture()
        new_nodes, new_edges = _inject_boundary_nodes(nodes, edges)
        internet_nodes = [n for n in new_nodes if n["type"] == "__boundary__/internet"]
        assert len(internet_nodes) == 1

    def test_internet_edges_connect_to_pips(self):
        nodes, edges = _build_graph_from_fixture()
        new_nodes, new_edges = _inject_boundary_nodes(nodes, edges)
        internet_edges = [e for e in new_edges if e["kind"] == "internet->publicIp"]
        pip_count = sum(1 for n in nodes if n["type"] == "microsoft.network/publicipaddresses")
        assert len(internet_edges) == pip_count

    def test_no_boundary_without_pip_or_gateway(self):
        """Nodes without PIPs or VPN gateways should not get boundary nodes."""
        nodes = [build_node({
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "name": "vm1",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "westeurope",
            "subscriptionId": "sub1",
            "resourceGroup": "rg1",
        })]
        new_nodes, new_edges = _inject_boundary_nodes(nodes, [])
        assert len(new_nodes) == 1  # No boundary nodes added
        assert len(new_edges) == 0

    def test_boundary_in_generated_xml(self, tmp_path):
        """Boundary nodes should appear in the generated draw.io XML."""
        _seed_output_files(tmp_path)
        cfg = _make_sub_rg_net_config(tmp_path)
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)

        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        assert "Internet" in labels, "Internet boundary node should be in diagram"


# ── NSG summary extraction tests ─────────────────────────────────────


class TestNsgSummaries:
    """Verify NSG rule extraction and formatting."""

    def test_nsg_summaries_from_landing_zone(self):
        """Landing zone fixture has NSGs with security rules."""
        nodes, edges = _build_graph_from_fixture()
        summaries = extract_nsg_summaries(nodes, edges)
        assert len(summaries) >= 4, f"Expected at least 4 NSGs, got {len(summaries)}"

    def test_nsg_summary_has_rules(self):
        nodes, edges = _build_graph_from_fixture()
        summaries = extract_nsg_summaries(nodes, edges)
        for nsg_id, summary in summaries.items():
            assert "nsg_name" in summary
            assert "rules" in summary
            assert isinstance(summary["rules"], list)

    def test_nsg_rules_sorted_by_direction_priority(self):
        nodes, edges = _build_graph_from_fixture()
        summaries = extract_nsg_summaries(nodes, edges)
        for nsg_id, summary in summaries.items():
            rules = summary["rules"]
            if len(rules) < 2:
                continue
            for i in range(len(rules) - 1):
                a, b = rules[i], rules[i + 1]
                assert (a["direction"], a["priority"]) <= (b["direction"], b["priority"]), \
                    f"Rules not sorted in NSG {summary['nsg_name']}"

    def test_nsg_attached_to_populated(self):
        """NSGs with subnet/NIC edges should have attached_to list."""
        nodes, edges = _build_graph_from_fixture()
        summaries = extract_nsg_summaries(nodes, edges)
        has_attached = any(s["attached_to"] for s in summaries.values())
        assert has_attached, "Expected at least one NSG to have attached_to entries"

    def test_nsg_panel_label_format(self):
        from tools.azdisc.drawio import _format_nsg_panel_label
        summary = {
            "nsg_name": "nsg-test",
            "attached_to": ["subnet-a"],
            "rules": [
                {"name": "r1", "priority": 100, "direction": "Inbound",
                 "access": "Allow", "protocol": "TCP", "src": "*",
                 "dst": "10.0.0.0/24", "dstPort": "443"},
            ],
        }
        label = _format_nsg_panel_label(summary)
        assert "NSG: nsg-test" in label
        assert "Attached: subnet-a" in label
        assert "443" in label


class TestNsgInDiagram:
    """Verify NSG callouts appear in generated diagrams."""

    def _generate_msft(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_sub_rg_net_config(tmp_path, diagram_mode="MSFT")
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        return ET.parse(str(tmp_path / "diagram.drawio"))

    def _generate_bands(self, tmp_path):
        _seed_output_files(tmp_path)
        cfg = _make_sub_rg_net_config(tmp_path, diagram_mode="BANDS")
        cfg = Config(
            app=cfg.app,
            subscriptions=cfg.subscriptions,
            seedResourceGroups=cfg.seedResourceGroups,
            outputDir=cfg.outputDir,
            layout=cfg.layout,
            diagramMode=cfg.diagramMode,
            networkDetail="full",  # test verifies BANDS NSG panel shapes
        )
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        return ET.parse(str(tmp_path / "diagram.drawio"))

    def test_msft_nsg_panels_present(self, tmp_path):
        tree = self._generate_msft(tmp_path)
        vertices = tree.findall(".//mxCell[@vertex='1']")
        nsg_panels = [v for v in vertices if v.get("id", "").startswith("msft_nsg_")]
        assert len(nsg_panels) >= 1, "Expected at least one NSG panel in MSFT mode"

    def test_msft_nsg_panel_has_rules_content(self, tmp_path):
        tree = self._generate_msft(tmp_path)
        vertices = tree.findall(".//mxCell[@vertex='1']")
        nsg_panels = [v for v in vertices if v.get("id", "").startswith("msft_nsg_")]
        for panel in nsg_panels:
            value = panel.get("value", "")
            assert "NSG:" in value, f"NSG panel should have 'NSG:' label: {value}"

    def test_msft_nsg_edges_exist(self, tmp_path):
        tree = self._generate_msft(tmp_path)
        edge_cells = tree.findall(".//mxCell[@edge='1']")
        nsg_edges = [e for e in edge_cells if e.get("id", "").startswith("msft_nsg_edge_")]
        assert len(nsg_edges) >= 1, "Expected NSG detail edges in MSFT mode"

    def test_bands_nsg_panels_present(self, tmp_path):
        tree = self._generate_bands(tmp_path)
        vertices = tree.findall(".//mxCell[@vertex='1']")
        nsg_panels = [v for v in vertices if v.get("id", "").startswith("nsg_panel_")]
        assert len(nsg_panels) >= 1, "Expected at least one NSG panel in BANDS mode"

    def test_bands_nsg_edges_exist(self, tmp_path):
        tree = self._generate_bands(tmp_path)
        edge_cells = tree.findall(".//mxCell[@edge='1']")
        nsg_edges = [e for e in edge_cells if e.get("id", "").startswith("nsg_edge_")]
        assert len(nsg_edges) >= 1, "Expected NSG detail edges in BANDS mode"
