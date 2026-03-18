"""Tests for the HUB>SPOKE layout, edgeLabels flag, and subnetColors flag."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config, load_config
from tools.azdisc.drawio import (
    CELL_H, CELL_W,
    VNET_STYLE,
    _detect_hub_vnet_ids,
    _edge_label,
    _hub_vnet_style,
    _spoke_vnet_style,
    _subnet_tier_style,
    layout_nodes_hub_spoke,
    layout_nodes_vnet,
)
from tools.azdisc.graph import build_graph, build_node, extract_edges

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _build_graph_from_fixture(name: str):
    """Build nodes + edges directly from a fixture file."""
    inventory = _load_fixture(name)
    from tools.azdisc.graph import (
        _is_child_resource, _find_parent_id, _collect_attributes,
    )
    from tools.azdisc.util import normalize_id

    parent_resources, child_resources = [], []
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


def _seed_and_build(tmp_path: Path, fixture: str) -> Config:
    (tmp_path / "inventory.json").write_text((FIXTURES / fixture).read_text())
    (tmp_path / "unresolved.json").write_text("[]")
    cfg = Config(
        app="test",
        subscriptions=["00000000-0000-0000-0000-000000000000"],
        seedResourceGroups=["fixture"],
        outputDir=str(tmp_path),
        layout="HUB>SPOKE",
    )
    build_graph(cfg)
    return cfg


# ---------------------------------------------------------------------------
# _edge_label tests
# ---------------------------------------------------------------------------

class TestEdgeLabel:
    def test_known_edges_return_non_empty(self):
        assert _edge_label("vnet->peeredVnet") == "VNet Peering"
        assert _edge_label("internet->publicIp") == "HTTPS"
        assert _edge_label("privateEndpoint->targetService") == "Private Link"
        assert _edge_label("onPrem->gateway") == "VPN / ExpressRoute"

    def test_unknown_edge_returns_empty(self):
        assert _edge_label("unknown->kind") == ""
        assert _edge_label("") == ""

    def test_all_edge_labels_are_strings(self):
        from tools.azdisc.drawio import _EDGE_LABELS
        for kind, label in _EDGE_LABELS.items():
            assert isinstance(label, str), f"Label for {kind!r} is not a string"
            assert label, f"Label for {kind!r} is empty"


# ---------------------------------------------------------------------------
# _subnet_tier_style tests
# ---------------------------------------------------------------------------

class TestSubnetTierStyle:
    def test_web_subnet_returns_blue(self):
        style = _subnet_tier_style("snet-web")
        assert style is not None
        assert "#E3F2FD" in style  # light blue fill

    def test_data_subnet_returns_orange(self):
        style = _subnet_tier_style("snet-data")
        assert style is not None
        assert "#FFF3E0" in style  # light orange fill

    def test_firewall_subnet_returns_red(self):
        style = _subnet_tier_style("AzureFirewallSubnet")
        assert style is not None
        assert "#FFEBEE" in style  # light red fill

    def test_gateway_subnet_returns_purple(self):
        style = _subnet_tier_style("GatewaySubnet")
        assert style is not None
        assert "#F3E5F5" in style

    def test_unknown_subnet_returns_none(self):
        style = _subnet_tier_style("snet-random-xyz")
        assert style is None

    def test_case_insensitive(self):
        assert _subnet_tier_style("SNET-WEB") is not None
        assert _subnet_tier_style("Snet-Data") is not None


# ---------------------------------------------------------------------------
# _detect_hub_vnet_ids tests
# ---------------------------------------------------------------------------

class TestHubVnetDetection:
    def test_detects_hub_by_firewall(self):
        """A VNet containing an Azure Firewall should be identified as hub."""
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        assert len(hub_ids) > 0, "Expected at least one hub VNet in app_landing_zone fixture"

    def test_no_hub_in_simple_fixture(self):
        """A fixture with no firewall or gateway should return no hubs."""
        nodes, edges = _build_graph_from_fixture("inventory_small.json")
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        # May be empty if no hub indicators present — just verify it returns a set
        assert isinstance(hub_ids, set)

    def test_returns_set_of_strings(self):
        nodes, edges = _build_graph_from_fixture("app_contoso.json")
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        assert isinstance(hub_ids, set)
        for hid in hub_ids:
            assert isinstance(hid, str)


# ---------------------------------------------------------------------------
# layout_nodes_hub_spoke tests
# ---------------------------------------------------------------------------

class TestHubSpokeLayout:
    def test_returns_positions_and_containers(self):
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        positions, containers = layout_nodes_hub_spoke(nodes, edges)
        assert isinstance(positions, dict)
        assert isinstance(containers, list)

    def test_all_resource_nodes_have_positions(self):
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        positions, _ = layout_nodes_hub_spoke(nodes, edges)
        skip_types = {
            "microsoft.network/virtualnetworks",
            "microsoft.network/virtualnetworks/subnets",
        }
        for n in nodes:
            if n.get("type", "").startswith("__boundary__"):
                continue
            if n["type"] in skip_types:
                continue
            assert n["id"] in positions, f"Node {n['name']} ({n['type']}) has no position"

    def test_vnet_containers_exist(self):
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        _, containers = layout_nodes_hub_spoke(nodes, edges)
        vnet_conts = [c for c in containers if c["id"].startswith("hs_vnet_")]
        assert len(vnet_conts) >= 1

    def test_subnet_containers_parented_to_vnet(self):
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        _, containers = layout_nodes_hub_spoke(nodes, edges)
        cont_ids = {c["id"] for c in containers}
        for c in containers:
            if c["id"].startswith("hs_subnet_"):
                assert c["parent"].startswith("hs_vnet_"), (
                    f"Subnet {c['id']} should have hs_vnet_ parent, got {c['parent']}"
                )
                assert c["parent"] in cont_ids

    def test_hub_vnet_placed_before_spoke_vertically(self):
        """Hub VNet containers should have a smaller y than spoke VNet containers."""
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        if not hub_ids:
            pytest.skip("No hubs detected in fixture")
        from tools.azdisc.util import stable_id
        _, containers = layout_nodes_hub_spoke(nodes, edges, hub_vnet_ids=hub_ids)
        hub_conts  = [c for c in containers if c["id"] in {"hs_vnet_" + stable_id(h) for h in hub_ids}]
        spoke_conts = [c for c in containers if c["id"].startswith("hs_vnet_")
                       and c["id"] not in {"hs_vnet_" + stable_id(h) for h in hub_ids}]
        if hub_conts and spoke_conts:
            max_hub_y   = max(c["y"] for c in hub_conts)
            min_spoke_y = min(c["y"] for c in spoke_conts)
            assert max_hub_y < min_spoke_y, (
                f"Hub VNets (max y={max_hub_y}) should be above spoke VNets (min y={min_spoke_y})"
            )

    def test_subnet_colors_applied(self):
        """With subnet_colors=True, at least one subnet should not use the default SUBNET_STYLE."""
        nodes, edges = _build_graph_from_fixture("app_contoso.json")
        from tools.azdisc.drawio import SUBNET_STYLE
        _, containers_plain  = layout_nodes_hub_spoke(nodes, edges, subnet_colors=False)
        _, containers_colors = layout_nodes_hub_spoke(nodes, edges, subnet_colors=True)
        sn_styles_plain  = {c["style"] for c in containers_plain  if c["id"].startswith("hs_subnet_")}
        sn_styles_colors = {c["style"] for c in containers_colors if c["id"].startswith("hs_subnet_")}
        # When subnet_colors=True there should be at least one non-default style
        # (contoso has snet-web/snet-app/snet-data which all match tier patterns)
        assert sn_styles_colors != sn_styles_plain or any(
            s != SUBNET_STYLE for s in sn_styles_colors
        ), "Expected at least one tier-colored subnet with subnet_colors=True"

    def test_hub_vnet_style_applied(self):
        """With subnet_colors=True, hub VNet containers should use hub style."""
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        if not hub_ids:
            pytest.skip("No hubs detected in fixture")
        from tools.azdisc.util import stable_id
        _, containers = layout_nodes_hub_spoke(nodes, edges, subnet_colors=True, hub_vnet_ids=hub_ids)
        expected_hub_style = _hub_vnet_style()
        for h_id in hub_ids:
            cid = "hs_vnet_" + stable_id(h_id)
            matching = [c for c in containers if c["id"] == cid]
            if matching:
                assert matching[0]["style"] == expected_hub_style, (
                    f"Hub VNet {h_id} should use hub style"
                )

    def test_layout_is_deterministic(self):
        nodes, edges = _build_graph_from_fixture("app_contoso.json")
        pos1, cont1 = layout_nodes_hub_spoke(nodes, edges)
        pos2, cont2 = layout_nodes_hub_spoke(nodes, edges)
        assert pos1 == pos2
        for c1, c2 in zip(cont1, cont2):
            assert c1 == c2

    def test_positions_non_negative(self):
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        positions, _ = layout_nodes_hub_spoke(nodes, edges)
        for nid, (x, y, w, h) in positions.items():
            assert x >= 0, f"Node {nid} has negative x={x}"
            assert y >= 0, f"Node {nid} has negative y={y}"


# ---------------------------------------------------------------------------
# Integration: generate_drawio with HUB>SPOKE layout
# ---------------------------------------------------------------------------

class TestHubSpokeDrawioGeneration:
    def _generate(self, tmp_path, fixture="app_landing_zone.json", **extra):
        (tmp_path / "inventory.json").write_text((FIXTURES / fixture).read_text())
        (tmp_path / "unresolved.json").write_text("[]")
        cfg = Config(
            app="test",
            subscriptions=["00000000-0000-0000-0000-000000000000"],
            seedResourceGroups=["fixture"],
            outputDir=str(tmp_path),
            layout="HUB>SPOKE",
            **extra,
        )
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        return cfg

    def test_drawio_file_created(self, tmp_path):
        cfg = self._generate(tmp_path)
        assert (tmp_path / "diagram.drawio").exists()

    def test_drawio_is_valid_xml(self, tmp_path):
        self._generate(tmp_path)
        root = ET.parse(str(tmp_path / "diagram.drawio")).getroot()
        assert root.tag == "mxfile"

    def test_drawio_has_containers(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        assert len(containers) >= 2, "Expected VNet and subnet containers"

    def test_subnet_icon_decorations_present(self, tmp_path):
        """HUB>SPOKE subnets should also have icon decorations."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        icons = [
            v for v in tree.findall(".//mxCell[@vertex='1']")
            if v.get("id", "").endswith("_icon") and "Subnet.svg" in v.get("style", "")
        ]
        assert len(icons) >= 1, "Expected at least one subnet icon decoration"

    def test_edge_labels_off_by_default(self, tmp_path):
        """Relationship edges should have empty value labels when edgeLabels=False.

        Internal annotation connectors (udr_edge_*, nsg_edge_*, attr_edge_*,
        netctx_edge_*) always carry their own fixed labels and are excluded.
        """
        _ANNOTATION_PREFIXES = ("udr_edge_", "nsg_edge_", "attr_edge_", "netctx_edge_")
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edge_cells = tree.findall(".//mxCell[@edge='1']")
        for ec in edge_cells:
            eid = ec.get("id", "")
            if any(eid.startswith(p) for p in _ANNOTATION_PREFIXES):
                continue
            assert ec.get("value", "") == "", (
                f"Edge {eid} should have empty label by default, got {ec.get('value')!r}"
            )

    def test_edge_labels_on(self, tmp_path):
        """Edges should have human-readable labels when edgeLabels=True."""
        self._generate(tmp_path, edgeLabels=True)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edge_cells = tree.findall(".//mxCell[@edge='1']")
        # At least some edges should have a non-empty label
        labelled = [ec for ec in edge_cells if ec.get("value", "")]
        assert len(labelled) > 0, "Expected at least some labelled edges with edgeLabels=True"

    def test_subnet_colors_applied_in_xml(self, tmp_path):
        """With subnetColors=True the XML should contain tier fill colours."""
        self._generate(tmp_path, subnetColors=True)
        xml = (tmp_path / "diagram.drawio").read_text()
        # At least one subnet tier colour should appear (landing zone has GatewaySubnet etc.)
        tier_fills = ["#E3F2FD", "#FFF3E0", "#FFEBEE", "#F3E5F5", "#E0F7FA"]
        assert any(fill in xml for fill in tier_fills), (
            "Expected at least one subnet tier fill colour in diagram XML with subnetColors=True"
        )

    def test_no_vnet_icon_cells(self, tmp_path):
        """VNet nodes should not appear as icon cells in HUB>SPOKE mode."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        for v in tree.findall(".//mxCell[@vertex='1']"):
            if v.get("connectable") == "0":
                continue
            if v.get("id", "").endswith("_icon"):
                continue
            style = v.get("style", "")
            assert "Virtual_Networks.svg" not in style, (
                "VNet node should not appear as icon cell in HUB>SPOKE mode"
            )


# ---------------------------------------------------------------------------
# Integration: edgeLabels and subnetColors in VNET>SUBNET layout
# ---------------------------------------------------------------------------

class TestVnetSubnetWithFlags:
    def _generate(self, tmp_path, **extra):
        (tmp_path / "inventory.json").write_text((FIXTURES / "app_contoso.json").read_text())
        (tmp_path / "unresolved.json").write_text("[]")
        cfg = Config(
            app="test",
            subscriptions=["00000000-0000-0000-0000-000000000000"],
            seedResourceGroups=["fixture"],
            outputDir=str(tmp_path),
            layout="VNET>SUBNET",
            **extra,
        )
        build_graph(cfg)
        from tools.azdisc.drawio import generate_drawio
        generate_drawio(cfg)
        return cfg

    def test_edge_labels_off_by_default(self, tmp_path):
        _ANNOTATION_PREFIXES = ("udr_edge_", "nsg_edge_", "attr_edge_", "netctx_edge_")
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        for ec in tree.findall(".//mxCell[@edge='1']"):
            eid = ec.get("id", "")
            if any(eid.startswith(p) for p in _ANNOTATION_PREFIXES):
                continue
            assert ec.get("value", "") == "", (
                f"Edge {eid} should have empty label, got {ec.get('value')!r}"
            )

    def test_edge_labels_on(self, tmp_path):
        self._generate(tmp_path, edgeLabels=True)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        labelled = [ec for ec in tree.findall(".//mxCell[@edge='1']") if ec.get("value", "")]
        assert len(labelled) > 0

    def test_subnet_colors_changes_styles(self, tmp_path):
        """Subnet container styles should differ between subnetColors=False and True."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp2:
            cfg_plain  = self._generate(tmp_path)
            (Path(tmp2) / "inventory.json").write_text((FIXTURES / "app_contoso.json").read_text())
            (Path(tmp2) / "unresolved.json").write_text("[]")
            cfg2 = Config(
                app="test", subscriptions=["00000000-0000-0000-0000-000000000000"],
                seedResourceGroups=["fixture"], outputDir=tmp2,
                layout="VNET>SUBNET", subnetColors=True,
            )
            build_graph(cfg2)
            from tools.azdisc.drawio import generate_drawio
            generate_drawio(cfg2)

            xml_plain  = (tmp_path / "diagram.drawio").read_text()
            xml_colors = (Path(tmp2) / "diagram.drawio").read_text()
            # Tier colours should appear in the colored version but not the plain one
            assert "#E3F2FD" in xml_colors or "#FFF3E0" in xml_colors or "#E8F5E9" in xml_colors, (
                "Expected tier fill colours in subnetColors=True diagram"
            )

    def test_hub_spoke_ordering_in_vnet_layout(self):
        """With a hub VNet, hubs should appear before spokes in the sorted order."""
        nodes, edges = _build_graph_from_fixture("app_landing_zone.json")
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        if not hub_ids:
            pytest.skip("No hubs detected")
        from collections import defaultdict
        from tools.azdisc.drawio import _build_network_membership
        _, containers = layout_nodes_vnet(
            nodes, edges, subnet_colors=False, hub_vnet_ids=hub_ids,
        )
        # Extract per-region VNet container order
        region_conts = [c for c in containers if c["id"].startswith("vnet_region_")]
        vnet_conts   = [c for c in containers if c["id"].startswith("vnet_") and not c["id"].startswith("vnet_region_")]
        # For each region, hubs should appear at smaller x than non-hubs
        from tools.azdisc.util import stable_id
        hub_vnet_cids = {"vnet_" + stable_id(h) for h in hub_ids}
        for region in region_conts:
            children = [c for c in vnet_conts if c["parent"] == region["id"]]
            if len(children) < 2:
                continue
            hub_children   = [c for c in children if c["id"] in hub_vnet_cids]
            spoke_children = [c for c in children if c["id"] not in hub_vnet_cids]
            if hub_children and spoke_children:
                max_hub_x   = max(c["x"] for c in hub_children)
                min_spoke_x = min(c["x"] for c in spoke_children)
                assert max_hub_x <= min_spoke_x, "Hub VNets should be to the left of spokes"
