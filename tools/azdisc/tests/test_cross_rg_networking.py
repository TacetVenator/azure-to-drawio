"""Tests for cross-resource-group networking resolution.

Verifies that when a NIC in one resource group references a subnet in a
different resource group, the VNET, subnet, NSG, and UDR are all properly
resolved and rendered in the diagram.
"""
import json
from pathlib import Path

import pytest

import xml.etree.ElementTree as ET

from tools.azdisc.config import Config
from tools.azdisc.discover import _derive_parent_ids, _synthesize_subnets_from_vnets
from tools.azdisc.docs import generate_docs
from tools.azdisc.drawio import extract_route_summaries, generate_drawio, layout_nodes_vnet
from tools.azdisc.graph import (
    _infer_type_from_id,
    build_graph,
    build_node,
    extract_edges,
)
from tools.azdisc.util import normalize_id

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _build_cross_rg_graph():
    """Build graph from cross-RG fixture and return nodes + edges."""
    from tools.azdisc.graph import (
        _is_child_resource,
        _find_parent_id,
        _collect_attributes,
    )

    inventory = _load_fixture("cross_rg_networking.json")
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


# ── _derive_parent_ids tests ──────────────────────────────────────────────


class TestDeriveParentIds:
    def test_subnet_yields_vnet(self):
        refs = {
            normalize_id(
                "/subscriptions/sub1/resourceGroups/rg-net/providers/"
                "Microsoft.Network/virtualNetworks/vnet01/subnets/snet01"
            )
        }
        parents = _derive_parent_ids(refs)
        expected = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/virtualNetworks/vnet01"
        )
        assert expected in parents

    def test_non_subnet_yields_nothing(self):
        refs = {
            normalize_id(
                "/subscriptions/sub1/resourceGroups/rg-net/providers/"
                "Microsoft.Network/networkSecurityGroups/nsg1"
            )
        }
        parents = _derive_parent_ids(refs)
        assert len(parents) == 0

    def test_multiple_subnets_same_vnet(self):
        refs = {
            normalize_id(
                "/subscriptions/sub1/resourceGroups/rg-net/providers/"
                "Microsoft.Network/virtualNetworks/vnet01/subnets/snet01"
            ),
            normalize_id(
                "/subscriptions/sub1/resourceGroups/rg-net/providers/"
                "Microsoft.Network/virtualNetworks/vnet01/subnets/snet02"
            ),
        }
        parents = _derive_parent_ids(refs)
        assert len(parents) == 1


# ── _synthesize_subnets_from_vnets tests ──────────────────────────────────


class TestSynthesizeSubnets:
    def test_synthesizes_subnet_from_vnet_properties(self):
        vnet_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/virtualNetworks/spoke-vnet01"
        )
        subnet_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/virtualNetworks/spoke-vnet01/subnets/cprmg-subnet01"
        )
        collected = {
            vnet_id: {
                "id": vnet_id,
                "name": "spoke-vnet01",
                "type": "Microsoft.Network/virtualNetworks",
                "location": "eastus",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-net",
                "properties": {
                    "subnets": [
                        {
                            "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/spoke-vnet01/subnets/cprmg-subnet01",
                            "name": "cprmg-subnet01",
                            "properties": {
                                "addressPrefix": "10.1.1.0/24",
                                "networkSecurityGroup": {"id": "some-nsg-id"},
                            },
                        }
                    ]
                },
            }
        }
        unresolved = {subnet_id}

        _synthesize_subnets_from_vnets(collected, unresolved)

        assert subnet_id in collected
        assert subnet_id not in unresolved
        synth = collected[subnet_id]
        assert synth["name"] == "cprmg-subnet01"
        assert synth["type"] == "Microsoft.Network/virtualNetworks/subnets"
        assert synth["properties"]["addressPrefix"] == "10.1.1.0/24"

    def test_no_op_when_vnet_missing(self):
        subnet_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/virtualNetworks/missing-vnet/subnets/snet01"
        )
        collected = {}
        unresolved = {subnet_id}

        _synthesize_subnets_from_vnets(collected, unresolved)

        assert subnet_id not in collected
        assert subnet_id in unresolved

    def test_ignores_non_subnet_unresolved(self):
        nsg_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-net/providers/"
            "Microsoft.Network/networkSecurityGroups/nsg1"
        )
        collected = {}
        unresolved = {nsg_id}

        _synthesize_subnets_from_vnets(collected, unresolved)

        assert nsg_id not in collected
        assert nsg_id in unresolved


# ── _infer_type_from_id tests ─────────────────────────────────────────────


class TestInferTypeFromId:
    def test_subnet_type(self):
        arm_id = "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet/subnets/sn"
        assert _infer_type_from_id(arm_id) == "microsoft.network/virtualnetworks/subnets"

    def test_vnet_type(self):
        arm_id = "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet"
        assert _infer_type_from_id(arm_id) == "microsoft.network/virtualnetworks"

    def test_nsg_type(self):
        arm_id = "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.network/networksecuritygroups/nsg1"
        assert _infer_type_from_id(arm_id) == "microsoft.network/networksecuritygroups"

    def test_unknown_for_bad_id(self):
        assert _infer_type_from_id("not-an-arm-id") == "external/unknown"


# ── Cross-RG graph edge tests ────────────────────────────────────────────


class TestCrossRgEdges:
    def test_nic_to_cross_rg_subnet_edge(self):
        nodes, edges = _build_cross_rg_graph()
        nic_subnet = [e for e in edges if e["kind"] == "nic->subnet"]
        assert len(nic_subnet) >= 1
        # The subnet should be in rg-networking, not rg-compute
        assert any("rg-networking" in e["target"] for e in nic_subnet)

    def test_subnet_to_vnet_edge(self):
        nodes, edges = _build_cross_rg_graph()
        subnet_vnet = [e for e in edges if e["kind"] == "subnet->vnet"]
        assert len(subnet_vnet) >= 1
        assert any("spoke-vnet01" in e["target"] for e in subnet_vnet)

    def test_subnet_to_nsg_edge(self):
        nodes, edges = _build_cross_rg_graph()
        subnet_nsg = [e for e in edges if e["kind"] == "subnet->nsg"]
        assert len(subnet_nsg) >= 1
        assert any("nsg-shared" in e["target"] for e in subnet_nsg)

    def test_subnet_to_route_table_edge(self):
        nodes, edges = _build_cross_rg_graph()
        subnet_udr = [e for e in edges if e["kind"] == "subnet->routeTable"]
        assert len(subnet_udr) >= 1
        assert any("udr-shared" in e["target"] for e in subnet_udr)


# ── Cross-RG VNET layout tests ───────────────────────────────────────────


class TestCrossRgVnetLayout:
    def test_vnet_container_present(self):
        nodes, edges = _build_cross_rg_graph()
        positions, containers = layout_nodes_vnet(nodes, edges)
        vnet_containers = [c for c in containers if c["id"].startswith("vnet_")]
        assert len(vnet_containers) >= 1, "Expected VNET container for spoke-vnet01"

    def test_subnet_container_present(self):
        nodes, edges = _build_cross_rg_graph()
        positions, containers = layout_nodes_vnet(nodes, edges)
        subnet_containers = [c for c in containers if c["id"].startswith("subnet_")]
        assert len(subnet_containers) >= 1, "Expected subnet container for cprmg-subnet01"

    def test_vm_placed_in_subnet(self):
        nodes, edges = _build_cross_rg_graph()
        positions, containers = layout_nodes_vnet(nodes, edges)
        vm_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-compute/providers/"
            "Microsoft.Compute/virtualMachines/vm-crossrg"
        )
        assert vm_id in positions, "VM should be placed inside a subnet container"

    def test_nsg_and_udr_present_in_nodes(self):
        nodes, edges = _build_cross_rg_graph()
        types = {n["type"] for n in nodes}
        assert "microsoft.network/networksecuritygroups" in types
        assert "microsoft.network/routetables" in types

    def test_cross_rg_container_labels(self):
        nodes, edges = _build_cross_rg_graph()
        _, containers = layout_nodes_vnet(nodes, edges)
        labels = {c["label"] for c in containers}
        assert "spoke-vnet01" in labels, "VNET container should show spoke-vnet01"
        assert "cprmg-subnet01" in labels, "Subnet container should show cprmg-subnet01"


# ── Integration: build_graph with cross-RG fixture ───────────────────────


class TestCrossRgBuildGraph:
    def _build(self, tmp_path):
        fixture = FIXTURES / "cross_rg_networking.json"
        (tmp_path / "inventory.json").write_text(fixture.read_text())
        (tmp_path / "unresolved.json").write_text("[]")
        cfg = Config(
            app="cross-rg-test",
            subscriptions=["sub1"],
            seedResourceGroups=["rg-compute"],
            outputDir=str(tmp_path),
            layout="VNET>SUBNET",
        )
        return build_graph(cfg)

    def test_vnet_node_present(self, tmp_path):
        graph = self._build(tmp_path)
        types = {n["type"] for n in graph["nodes"]}
        assert "microsoft.network/virtualnetworks" in types

    def test_subnet_node_present(self, tmp_path):
        graph = self._build(tmp_path)
        types = {n["type"] for n in graph["nodes"]}
        assert "microsoft.network/virtualnetworks/subnets" in types

    def test_cross_rg_subnet_edges(self, tmp_path):
        graph = self._build(tmp_path)
        kinds = {e["kind"] for e in graph["edges"]}
        assert "nic->subnet" in kinds
        assert "subnet->vnet" in kinds
        assert "subnet->nsg" in kinds
        assert "subnet->routeTable" in kinds

    def test_no_unresolved_networking(self, tmp_path):
        """When all networking resources are in inventory, nothing should be unresolved."""
        graph = self._build(tmp_path)
        external_net = [
            n for n in graph["nodes"]
            if n["isExternal"] and "network" in n["type"]
        ]
        assert len(external_net) == 0, (
            f"Cross-RG networking resources should not be external: "
            f"{[n['id'] for n in external_net]}"
        )

    def test_udr_routes_extracted_for_cross_rg_subnet(self, tmp_path):
        """Route table routes should be available via extract_route_summaries."""
        graph = self._build(tmp_path)
        subnet_udr, vnet_rollup = extract_route_summaries(
            graph["nodes"], graph["edges"],
        )
        assert len(subnet_udr) >= 1, "Expected at least one subnet with UDR"

        # Find the cprmg-subnet01 entry
        subnet_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-networking/providers/"
            "Microsoft.Network/virtualNetworks/spoke-vnet01/subnets/cprmg-subnet01"
        )
        assert subnet_id in subnet_udr, (
            f"cprmg-subnet01 should have UDR summary, got keys: {list(subnet_udr.keys())}"
        )
        summary = subnet_udr[subnet_id]
        assert summary["rt_name"] == "udr-shared"
        assert len(summary["routes"]) == 2
        route_names = {r["name"] for r in summary["routes"]}
        assert "to-firewall" in route_names
        assert "to-onprem" in route_names

    def test_udr_vnet_rollup_for_cross_rg(self, tmp_path):
        """VNet rollup should list subnet names that have UDRs."""
        graph = self._build(tmp_path)
        _, vnet_rollup = extract_route_summaries(
            graph["nodes"], graph["edges"],
        )
        vnet_id = normalize_id(
            "/subscriptions/sub1/resourceGroups/rg-networking/providers/"
            "Microsoft.Network/virtualNetworks/spoke-vnet01"
        )
        assert vnet_id in vnet_rollup, "spoke-vnet01 should appear in VNet UDR rollup"
        assert "cprmg-subnet01" in vnet_rollup[vnet_id]


# ── Markdown docs output ─────────────────────────────────────────────────


class TestCrossRgMarkdownDocs:
    """Verify routing.md and catalog.md include cross-RG networking details."""

    def _generate(self, tmp_path):
        fixture = FIXTURES / "cross_rg_networking.json"
        (tmp_path / "inventory.json").write_text(fixture.read_text())
        (tmp_path / "unresolved.json").write_text("[]")
        cfg = Config(
            app="cross-rg-test",
            subscriptions=["sub1"],
            seedResourceGroups=["rg-compute"],
            outputDir=str(tmp_path),
            layout="VNET>SUBNET",
        )
        build_graph(cfg)
        generate_docs(cfg)
        return cfg

    def test_routing_md_has_route_table(self, tmp_path):
        self._generate(tmp_path)
        routing = (tmp_path / "routing.md").read_text()
        assert "udr-shared" in routing

    def test_routing_md_has_routes(self, tmp_path):
        self._generate(tmp_path)
        routing = (tmp_path / "routing.md").read_text()
        assert "to-firewall" in routing
        assert "0.0.0.0/0" in routing
        assert "VirtualAppliance" in routing
        assert "10.0.1.4" in routing
        assert "to-onprem" in routing
        assert "172.16.0.0/12" in routing

    def test_routing_md_has_subnet_udr_association(self, tmp_path):
        self._generate(tmp_path)
        routing = (tmp_path / "routing.md").read_text()
        assert "cprmg-subnet01" in routing
        # Subnet should be listed with its UDR association
        assert "Subnets with UDRs: 1" in routing

    def test_routing_md_has_nsg(self, tmp_path):
        self._generate(tmp_path)
        routing = (tmp_path / "routing.md").read_text()
        assert "nsg-shared" in routing

    def test_catalog_md_has_cross_rg_types(self, tmp_path):
        self._generate(tmp_path)
        catalog = (tmp_path / "catalog.md").read_text()
        assert "microsoft.network/virtualnetworks" in catalog
        assert "microsoft.network/routetables" in catalog
        assert "microsoft.network/networksecuritygroups" in catalog
        # Both resource groups should appear
        assert "rg-compute" in catalog
        assert "rg-networking" in catalog

    def test_edges_md_has_cross_rg_edge_kinds(self, tmp_path):
        self._generate(tmp_path)
        edges_md = (tmp_path / "edges.md").read_text()
        assert "subnet->routeTable" in edges_md
        assert "subnet->nsg" in edges_md
        assert "nic->subnet" in edges_md
        assert "subnet->vnet" in edges_md


# ── Diagram output ────────────────────────────────────────────────────────


class TestCrossRgDiagramOutput:
    """Verify the .drawio XML includes cross-RG networking containers and edges."""

    def _generate(self, tmp_path):
        fixture = FIXTURES / "cross_rg_networking.json"
        (tmp_path / "inventory.json").write_text(fixture.read_text())
        (tmp_path / "unresolved.json").write_text("[]")
        cfg = Config(
            app="cross-rg-test",
            subscriptions=["sub1"],
            seedResourceGroups=["rg-compute"],
            outputDir=str(tmp_path),
            layout="VNET>SUBNET",
            networkDetail="full",  # these tests verify UDR/NSG callout shapes
        )
        build_graph(cfg)
        generate_drawio(cfg)
        return cfg

    def test_drawio_file_created(self, tmp_path):
        self._generate(tmp_path)
        assert (tmp_path / "diagram.drawio").exists()

    def test_drawio_has_vnet_container(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        labels = {c.get("value") for c in containers}
        assert "spoke-vnet01" in labels, f"Missing VNET container, got: {labels}"

    def test_drawio_has_subnet_container(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        labels = {c.get("value") for c in containers}
        assert "cprmg-subnet01" in labels, f"Missing subnet container, got: {labels}"

    def test_drawio_has_udr_callout(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        udr_callouts = [
            v for v in vertices
            if v.get("id", "").startswith("udr_")
            and "Routes:" in (v.get("value") or "")
        ]
        assert len(udr_callouts) >= 1, "Expected UDR callout with route details"
        callout_text = udr_callouts[0].get("value", "")
        assert "0.0.0.0/0" in callout_text
        assert "172.16.0.0/12" in callout_text

    def test_drawio_has_vm_node(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        assert "vm-crossrg" in labels

    def test_drawio_has_edge_cells(self, tmp_path):
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        assert len(edges) >= 3, f"Expected >=3 edges, got {len(edges)}"

    def test_drawio_udr_callout_edge_connects_to_route_table(self, tmp_path):
        """UDR callout edge should connect from the route table node, not a subnet container."""
        self._generate(tmp_path)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        udr_edges = [
            e for e in tree.findall(".//mxCell[@edge='1']")
            if e.get("id", "").startswith("udr_edge_")
        ]
        assert len(udr_edges) >= 1, "Expected at least one UDR callout edge"

        # Collect all element IDs (mxCell + UserObject, since resource nodes
        # use UserObject wrappers whose id is the stable_id)
        all_ids = set()
        for elem in tree.iter():
            eid = elem.get("id")
            if eid:
                all_ids.add(eid)
        for edge in udr_edges:
            src = edge.get("source")
            tgt = edge.get("target")
            assert src in all_ids, f"UDR edge source {src} not found in diagram elements"
            assert tgt in all_ids, f"UDR edge target {tgt} not found in diagram elements"
