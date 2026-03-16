"""Tests for the AI chatbot (Container Apps + OpenAI + hub-spoke) fixture.

Validates graph construction, edge extraction, and diagram generation across
all three layout modes for a production-grade Azure AI architecture.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config
from tools.azdisc.drawio import (
    CELL_H,
    CELL_W,
    _spacing_factor,
    generate_drawio,
    layout_nodes,
    layout_nodes_msft,
    layout_nodes_vnet,
)
from tools.azdisc.graph import build_graph

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_NAME = "app_ai_chatbot.json"
SUB_ID = "00000000-0000-0000-0000-000000000002"


def _seed(tmp_path: Path) -> None:
    data = (FIXTURES / FIXTURE_NAME).read_text()
    (tmp_path / "inventory.json").write_text(data)
    (tmp_path / "unresolved.json").write_text("[]")


def _make_config(tmp_path: Path, **kwargs) -> Config:
    return Config(
        app="ai-chatbot",
        subscriptions=[SUB_ID],
        seedResourceGroups=["rg-ai-chat-prod", "rg-ai-chat-hub"],
        outputDir=str(tmp_path),
        **kwargs,
    )


def _build(tmp_path: Path, **kwargs):
    _seed(tmp_path)
    cfg = _make_config(tmp_path, **kwargs)
    graph = build_graph(cfg)
    return graph, cfg


# ── Graph construction tests ─────────────────────────────────────────────


class TestAiChatbotGraph:
    """Verify graph construction from the AI chatbot fixture."""

    def test_graph_produces_nodes(self, tmp_path):
        graph, _ = _build(tmp_path)
        # 30+ resources after child merging (subnets are children of VNets)
        assert len(graph["nodes"]) >= 25, (
            f"Expected >= 25 nodes, got {len(graph['nodes'])}"
        )

    def test_graph_produces_edges(self, tmp_path):
        graph, _ = _build(tmp_path)
        assert len(graph["edges"]) >= 10

    def test_expected_ai_resource_types_present(self, tmp_path):
        graph, _ = _build(tmp_path)
        types = {n["type"] for n in graph["nodes"]}
        expected = {
            "microsoft.cognitiveservices/accounts",
            "microsoft.documentdb/databaseaccounts",
            "microsoft.search/searchservices",
            "microsoft.app/managedenvironments",
            "microsoft.app/containerapps",
            "microsoft.containerregistry/registries",
            "microsoft.keyvault/vaults",
            "microsoft.storage/storageaccounts",
            "microsoft.managedidentity/userassignedidentities",
            "microsoft.insights/components",
            "microsoft.operationalinsights/workspaces",
        }
        for t in expected:
            assert t in types, f"Missing AI resource type: {t}"

    def test_expected_networking_types_present(self, tmp_path):
        graph, _ = _build(tmp_path)
        types = {n["type"] for n in graph["nodes"]}
        expected = {
            "microsoft.network/virtualnetworks",
            "microsoft.network/virtualnetworks/subnets",
            "microsoft.network/networksecuritygroups",
            "microsoft.network/routetables",
            "microsoft.network/privateendpoints",
            "microsoft.network/azurefirewalls",
            "microsoft.network/bastionhosts",
            "microsoft.network/publicipaddresses",
        }
        for t in expected:
            assert t in types, f"Missing networking type: {t}"

    def test_two_vnets_present(self, tmp_path):
        graph, _ = _build(tmp_path)
        vnets = [n for n in graph["nodes"]
                 if n["type"] == "microsoft.network/virtualnetworks"]
        assert len(vnets) == 2, f"Expected 2 VNets, got {len(vnets)}"
        names = {v["name"] for v in vnets}
        assert "vnet-ai-chat" in names
        assert "vnet-hub" in names

    def test_private_endpoint_count(self, tmp_path):
        graph, _ = _build(tmp_path)
        pes = [n for n in graph["nodes"]
               if n["type"] == "microsoft.network/privateendpoints"]
        assert len(pes) == 5, f"Expected 5 private endpoints, got {len(pes)}"

    def test_container_apps_count(self, tmp_path):
        graph, _ = _build(tmp_path)
        cas = [n for n in graph["nodes"]
               if n["type"] == "microsoft.app/containerapps"]
        assert len(cas) == 2

    def test_cross_rg_resources(self, tmp_path):
        graph, _ = _build(tmp_path)
        rgs = {n["resourceGroup"] for n in graph["nodes"]}
        assert "rg-ai-chat-prod" in rgs
        assert "rg-ai-chat-hub" in rgs


# ── Edge extraction tests ────────────────────────────────────────────────


class TestAiChatbotEdges:
    """Verify edge extraction for AI chatbot relationships."""

    def test_private_endpoint_subnet_edges(self, tmp_path):
        graph, _ = _build(tmp_path)
        pe_subnet = [e for e in graph["edges"]
                     if e["kind"] == "privateEndpoint->subnet"]
        assert len(pe_subnet) == 5, (
            f"Expected 5 PE->subnet edges, got {len(pe_subnet)}"
        )

    def test_private_endpoint_target_edges(self, tmp_path):
        graph, _ = _build(tmp_path)
        pe_target = [e for e in graph["edges"]
                     if e["kind"] == "privateEndpoint->target"]
        assert len(pe_target) == 5, (
            f"Expected 5 PE->target edges, got {len(pe_target)}"
        )
        # Verify targets include the expected services
        targets = {e["target"].split("/")[-1] for e in pe_target}
        for svc in ["oai-chat", "acraichat", "cosmos-chat",
                     "srch-ai-chat", "staichat"]:
            assert svc in targets, f"Missing PE target: {svc}"

    def test_vnet_peering_edges(self, tmp_path):
        graph, _ = _build(tmp_path)
        peering = [e for e in graph["edges"]
                   if e["kind"] == "vnet->peeredVnet"]
        assert len(peering) == 2, (
            f"Expected 2 VNet peering edges (bidirectional), got {len(peering)}"
        )

    def test_subnet_nsg_edges(self, tmp_path):
        graph, _ = _build(tmp_path)
        nsg_edges = [e for e in graph["edges"]
                     if e["kind"] == "subnet->nsg"]
        assert len(nsg_edges) >= 3, (
            f"Expected >= 3 subnet->NSG edges, got {len(nsg_edges)}"
        )

    def test_subnet_route_table_edge(self, tmp_path):
        graph, _ = _build(tmp_path)
        rt_edges = [e for e in graph["edges"]
                    if e["kind"] == "subnet->routeTable"]
        assert len(rt_edges) >= 1
        # The apps subnet should have a route table
        sources = {e["source"].split("/")[-1] for e in rt_edges}
        assert "snet-apps" in sources

    def test_subnet_vnet_edges(self, tmp_path):
        graph, _ = _build(tmp_path)
        sv_edges = [e for e in graph["edges"]
                    if e["kind"] == "subnet->vnet"]
        # 3 spoke subnets + 2 hub subnets = 5
        assert len(sv_edges) >= 5, (
            f"Expected >= 5 subnet->vnet edges, got {len(sv_edges)}"
        )


# ── BANDS layout tests ──────────────────────────────────────────────────


class TestAiChatbotBandsLayout:
    """Test BANDS layout mode with the AI chatbot fixture."""

    def test_generates_valid_xml(self, tmp_path):
        graph, cfg = _build(tmp_path)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"

    def test_has_sufficient_vertices(self, tmp_path):
        graph, cfg = _build(tmp_path)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        assert len(vertices) >= 20

    def test_has_edge_cells(self, tmp_path):
        graph, cfg = _build(tmp_path)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        edges = tree.findall(".//mxCell[@edge='1']")
        assert len(edges) >= 5

    def test_expected_labels_present(self, tmp_path):
        graph, cfg = _build(tmp_path)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        vertices = tree.findall(".//mxCell[@vertex='1']")
        labels = {v.get("value") for v in vertices if v.get("value")}
        for name in ["ca-chat-api", "ca-chat-ui", "oai-chat",
                      "cosmos-chat", "kv-ai-chat", "fw-hub", "bastion-hub"]:
            assert name in labels, f"Missing label: {name}"


# ── VNET>SUBNET layout tests ────────────────────────────────────────────


class TestAiChatbotVnetLayout:
    """Test VNET>SUBNET layout mode with the AI chatbot fixture."""

    def test_generates_valid_xml(self, tmp_path):
        graph, cfg = _build(tmp_path, layout="VNET>SUBNET")
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"

    def test_two_vnet_containers(self, tmp_path):
        graph, _ = _build(tmp_path)
        nodes, edges = graph["nodes"], graph["edges"]
        _, containers = layout_nodes_vnet(nodes, edges)
        vnet_containers = [c for c in containers
                           if c["id"].startswith("vnet_") and not c["id"].startswith("vnet_region_")]
        assert len(vnet_containers) == 2, (
            f"Expected 2 VNet containers, got {len(vnet_containers)}"
        )

    def test_subnet_containers(self, tmp_path):
        graph, _ = _build(tmp_path)
        nodes, edges = graph["nodes"], graph["edges"]
        _, containers = layout_nodes_vnet(nodes, edges)
        subnet_containers = [c for c in containers
                             if c["id"].startswith("subnet_")]
        # 3 spoke subnets + 2 hub subnets = 5
        assert len(subnet_containers) == 5, (
            f"Expected 5 subnet containers, got {len(subnet_containers)}"
        )

    def test_container_labels(self, tmp_path):
        graph, _ = _build(tmp_path)
        nodes, edges = graph["nodes"], graph["edges"]
        _, containers = layout_nodes_vnet(nodes, edges)
        labels = {c["label"] for c in containers}
        for name in ["vnet-ai-chat", "vnet-hub", "snet-apps",
                      "snet-private-endpoints", "AzureFirewallSubnet"]:
            assert name in labels, f"Missing container label: {name}"


# ── MSFT layout tests ───────────────────────────────────────────────────


class TestAiChatbotMsftLayout:
    """Test MSFT layout mode with the AI chatbot fixture."""

    def test_generates_valid_xml(self, tmp_path):
        graph, cfg = _build(tmp_path, diagramMode="MSFT")
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"

    def test_has_rg_containers(self, tmp_path):
        graph, cfg = _build(tmp_path, diagramMode="MSFT")
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        containers = tree.findall(".//mxCell[@connectable='0']")
        # At least region + 2 RGs
        assert len(containers) >= 3


# ── Spacious mode tests ─────────────────────────────────────────────────


class TestAiChatbotSpacious:
    """Test spacious spacing with the AI chatbot fixture."""

    def test_spacious_no_overlap(self, tmp_path):
        graph, _ = _build(tmp_path)
        sp = _spacing_factor("spacious")
        pos = layout_nodes(graph["nodes"], spacing=sp)
        rects = list(pos.values())
        for i, (x1, y1, w1, h1) in enumerate(rects):
            for j, (x2, y2, w2, h2) in enumerate(rects):
                if i >= j:
                    continue
                overlap_x = x1 < x2 + w2 and x2 < x1 + w1
                overlap_y = y1 < y2 + h2 and y2 < y1 + h1
                assert not (overlap_x and overlap_y)

    def test_spacious_vnet_no_overlap(self, tmp_path):
        graph, _ = _build(tmp_path)
        sp = _spacing_factor("spacious")
        pos, _ = layout_nodes_vnet(graph["nodes"], graph["edges"], spacing=sp)
        rects = list(pos.values())
        for i, (x1, y1, w1, h1) in enumerate(rects):
            for j, (x2, y2, w2, h2) in enumerate(rects):
                if i >= j:
                    continue
                overlap_x = x1 < x2 + w2 and x2 < x1 + w1
                overlap_y = y1 < y2 + h2 and y2 < y1 + h1
                assert not (overlap_x and overlap_y)

    def test_spacious_generates_valid_drawio(self, tmp_path):
        _seed(tmp_path)
        cfg = _make_config(tmp_path, spacing="spacious")
        build_graph(cfg)
        generate_drawio(cfg)
        tree = ET.parse(str(tmp_path / "diagram.drawio"))
        assert tree.getroot().tag == "mxfile"


# ── Determinism tests ────────────────────────────────────────────────────


class TestAiChatbotDeterminism:
    """Verify deterministic output from the AI chatbot fixture."""

    def test_deterministic_graph(self, tmp_path):
        graph1, _ = _build(tmp_path)
        # Re-seed and rebuild
        _seed(tmp_path)
        cfg = _make_config(tmp_path)
        graph2 = build_graph(cfg)
        assert graph1["nodes"] == graph2["nodes"]
        assert graph1["edges"] == graph2["edges"]

    def test_deterministic_layout(self, tmp_path):
        graph, _ = _build(tmp_path)
        pos1 = layout_nodes(graph["nodes"])
        pos2 = layout_nodes(graph["nodes"])
        assert pos1 == pos2

    def test_deterministic_xml(self, tmp_path):
        _seed(tmp_path)
        cfg = _make_config(tmp_path)
        build_graph(cfg)
        generate_drawio(cfg)
        xml1 = (tmp_path / "diagram.drawio").read_text()

        # Regenerate
        generate_drawio(cfg)
        xml2 = (tmp_path / "diagram.drawio").read_text()
        assert xml1 == xml2
