"""Tests for the diagram focus filter feature."""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config, DiagramFocusConfig, load_config_from_dict
from tools.azdisc.drawio import _filter_graph_by_focus, generate_drawio
from tools.azdisc.graph import build_graph

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Unit tests for _filter_graph_by_focus
# ---------------------------------------------------------------------------

def _make_node(arm_id: str, arm_type: str) -> dict:
    return {"id": arm_id, "type": arm_type, "name": arm_id.split("/")[-1]}


def _make_edge(src: str, tgt: str, kind: str) -> dict:
    return {"source": src, "target": tgt, "kind": kind}


@pytest.fixture()
def sample_graph():
    """Small graph: VM → NIC → Subnet → VNet, plus an unrelated Storage account."""
    nodes = [
        _make_node("/subs/s1/rg/rg1/providers/microsoft.compute/virtualmachines/vm1",
                   "microsoft.compute/virtualmachines"),
        _make_node("/subs/s1/rg/rg1/providers/microsoft.network/networkinterfaces/nic1",
                   "microsoft.network/networkinterfaces"),
        _make_node("/subs/s1/rg/rg1/providers/microsoft.network/virtualnetworks/subnets/sub1",
                   "microsoft.network/virtualnetworks/subnets"),
        _make_node("/subs/s1/rg/rg1/providers/microsoft.network/virtualnetworks/vnet1",
                   "microsoft.network/virtualnetworks"),
        _make_node("/subs/s1/rg/rg1/providers/microsoft.storage/storageaccounts/sa1",
                   "microsoft.storage/storageaccounts"),
        _make_node("/subs/s1/rg/rg1/providers/microsoft.logic/workflows/la1",
                   "microsoft.logic/workflows"),
    ]
    edges = [
        _make_edge("/subs/s1/rg/rg1/providers/microsoft.compute/virtualmachines/vm1",
                   "/subs/s1/rg/rg1/providers/microsoft.network/networkinterfaces/nic1",
                   "vm->nic"),
        _make_edge("/subs/s1/rg/rg1/providers/microsoft.network/networkinterfaces/nic1",
                   "/subs/s1/rg/rg1/providers/microsoft.network/virtualnetworks/subnets/sub1",
                   "nic->subnet"),
        _make_edge("/subs/s1/rg/rg1/providers/microsoft.network/virtualnetworks/subnets/sub1",
                   "/subs/s1/rg/rg1/providers/microsoft.network/virtualnetworks/vnet1",
                   "subnet->vnet"),
    ]
    return nodes, edges


def test_filter_full_preset_passes_through(sample_graph):
    """preset='full' returns all nodes and edges unchanged."""
    nodes, edges = sample_graph
    focus = DiagramFocusConfig(preset="full")
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    assert len(fn) == len(nodes)
    assert len(fe) == len(edges)


def test_filter_vm_dependencies_includes_vm_and_nic(sample_graph):
    """preset='vm-dependencies' with depth=1 keeps VM and NIC, not storage."""
    nodes, edges = sample_graph
    focus = DiagramFocusConfig(preset="vm-dependencies", includeDependencies=True, dependencyDepth=1)
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    returned_types = {n["type"] for n in fn}
    assert "microsoft.compute/virtualmachines" in returned_types
    assert "microsoft.network/networkinterfaces" in returned_types
    assert "microsoft.storage/storageaccounts" not in returned_types
    # Logic App should not appear unless its type is an anchor or reachable
    assert "microsoft.logic/workflows" not in returned_types


def test_filter_vm_dependencies_depth2_includes_subnet(sample_graph):
    """Depth 2 follows VM→NIC→Subnet (two hops)."""
    nodes, edges = sample_graph
    focus = DiagramFocusConfig(preset="vm-dependencies", includeDependencies=True, dependencyDepth=2)
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    returned_types = {n["type"] for n in fn}
    assert "microsoft.network/virtualnetworks/subnets" in returned_types
    assert "microsoft.storage/storageaccounts" not in returned_types


def test_filter_vm_logicapp_integration(sample_graph):
    """preset='vm-logicapp-integration' anchors both VM and Logic App types."""
    nodes, edges = sample_graph
    focus = DiagramFocusConfig(preset="vm-logicapp-integration", includeDependencies=True, dependencyDepth=1)
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    returned_types = {n["type"] for n in fn}
    assert "microsoft.compute/virtualmachines" in returned_types
    assert "microsoft.logic/workflows" in returned_types
    # NIC is 1 hop from VM so also included
    assert "microsoft.network/networkinterfaces" in returned_types
    # Storage is unreachable → excluded
    assert "microsoft.storage/storageaccounts" not in returned_types


def test_filter_custom_preset_explicit_types(sample_graph):
    """preset='custom' with explicit resourceTypes filters to only those anchors + deps."""
    nodes, edges = sample_graph
    focus = DiagramFocusConfig(
        preset="custom",
        resourceTypes=["microsoft.storage/storageaccounts"],
        includeDependencies=False,
    )
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    assert len(fn) == 1
    assert fn[0]["type"] == "microsoft.storage/storageaccounts"
    assert len(fe) == 0


def test_filter_no_deps_only_anchor_types(sample_graph):
    """includeDependencies=False returns only anchor type nodes."""
    nodes, edges = sample_graph
    focus = DiagramFocusConfig(preset="vm-dependencies", includeDependencies=False)
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    assert all(n["type"] == "microsoft.compute/virtualmachines" for n in fn)
    # All edges touch filtered-out nodes so none survive
    assert len(fe) == 0


def test_filter_immediate_vm_network_scope_trims_fanout(sample_graph):
    """immediate-vm-network keeps only VM->NIC->Subnet->VNet chain."""
    nodes, edges = sample_graph
    # Add extra non-immediate fanout edges that should be trimmed.
    edges = list(edges) + [
        _make_edge(
            "/subs/s1/rg/rg1/providers/microsoft.network/networkinterfaces/nic1",
            "/subs/s1/rg/rg1/providers/microsoft.network/networksecuritygroups/nsg1",
            "nic->nsg",
        ),
        _make_edge(
            "/subs/s1/rg/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "/subs/s1/rg/rg1/providers/microsoft.compute/disks/disk1",
            "vm->disk",
        ),
    ]
    nodes = list(nodes) + [
        _make_node(
            "/subs/s1/rg/rg1/providers/microsoft.network/networksecuritygroups/nsg1",
            "microsoft.network/networksecuritygroups",
        ),
        _make_node(
            "/subs/s1/rg/rg1/providers/microsoft.compute/disks/disk1",
            "microsoft.compute/disks",
        ),
    ]

    focus = DiagramFocusConfig(
        preset="vm-dependencies",
        includeDependencies=True,
        dependencyDepth=3,
        networkScope="immediate-vm-network",
    )
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    edge_kinds = {e["kind"] for e in fe}
    assert edge_kinds == {"vm->nic", "nic->subnet", "subnet->vnet"}
    returned_types = {n["type"] for n in fn}
    assert "microsoft.network/networksecuritygroups" not in returned_types
    assert "microsoft.compute/disks" not in returned_types


def test_filter_diagram_type_network_keeps_only_network_edges(sample_graph):
    """diagramType='network' keeps only network-flow edges."""
    nodes, edges = sample_graph
    edges = list(edges) + [
        _make_edge(
            "/subs/s1/rg/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "/subs/s1/rg/rg1/providers/microsoft.logic/workflows/la1",
            "resource->dependency",
        )
    ]
    focus = DiagramFocusConfig(
        preset="vm-logicapp-integration",
        includeDependencies=True,
        dependencyDepth=2,
        diagramType="network",
    )
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    assert all(e["kind"] != "resource->dependency" for e in fe)


def test_filter_diagram_type_application_keeps_integration_edges(sample_graph):
    """diagramType='application' keeps integration/data-flow edges."""
    nodes, edges = sample_graph
    edges = list(edges) + [
        _make_edge(
            "/subs/s1/rg/rg1/providers/microsoft.compute/virtualmachines/vm1",
            "/subs/s1/rg/rg1/providers/microsoft.logic/workflows/la1",
            "resource->dependency",
        )
    ]
    focus = DiagramFocusConfig(
        preset="vm-logicapp-integration",
        includeDependencies=True,
        dependencyDepth=2,
        diagramType="application",
    )
    fn, fe = _filter_graph_by_focus(nodes, edges, focus)
    edge_kinds = {e["kind"] for e in fe}
    assert "resource->dependency" in edge_kinds
    assert "vm->nic" not in edge_kinds


# ---------------------------------------------------------------------------
# Integration: generate_drawio respects diagramFocus config
# ---------------------------------------------------------------------------

def test_generate_drawio_with_vm_dependencies_focus(tmp_path):
    """End-to-end: vm-dependencies focus removes unrelated resources from diagram."""
    (tmp_path / "inventory.json").write_text(
        (FIXTURES / "app_contoso.json").read_text()
    )
    (tmp_path / "unresolved.json").write_text("[]")
    cfg = Config(
        app="focus-test",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        diagramMode="MSFT",
        diagramFocus=DiagramFocusConfig(preset="vm-dependencies"),
    )
    build_graph(cfg)
    generate_drawio(cfg)
    tree = ET.parse(str(tmp_path / "diagram.drawio"))
    assert tree.getroot().tag == "mxfile"


def test_generate_drawio_full_focus_unchanged(tmp_path):
    """preset='full' should produce a valid diagram (baseline parity check)."""
    (tmp_path / "inventory.json").write_text(
        (FIXTURES / "app_contoso.json").read_text()
    )
    (tmp_path / "unresolved.json").write_text("[]")
    cfg_full = Config(
        app="focus-full",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        diagramMode="MSFT",
        diagramFocus=DiagramFocusConfig(preset="full"),
    )
    build_graph(cfg_full)
    generate_drawio(cfg_full)
    tree = ET.parse(str(tmp_path / "diagram.drawio"))
    assert tree.getroot().tag == "mxfile"


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------

def test_load_config_from_dict_default_diagram_focus():
    """diagramFocus defaults to preset='full' when not supplied."""
    data = {
        "app": "test",
        "subscriptions": ["00000000-0000-0000-0000-000000000001"],
        "outputDir": "/tmp/test",
        "seedEntireSubscriptions": True,
    }
    cfg = load_config_from_dict(data)
    assert cfg.diagramFocus.preset == "full"
    assert cfg.diagramFocus.resourceTypes == []
    assert cfg.diagramFocus.includeDependencies is True
    assert cfg.diagramFocus.networkScope == "full"
    assert cfg.diagramFocus.diagramType == "balanced"


def test_load_config_from_dict_valid_diagram_focus():
    """Custom diagramFocus is parsed correctly."""
    data = {
        "app": "test",
        "subscriptions": ["00000000-0000-0000-0000-000000000001"],
        "outputDir": "/tmp/test",
        "seedEntireSubscriptions": True,
        "diagramFocus": {
            "preset": "custom",
            "resourceTypes": ["microsoft.compute/virtualmachines"],
            "includeDependencies": True,
            "dependencyDepth": 2,
            "networkScope": "immediate-vm-network",
            "diagramType": "network",
        },
    }
    cfg = load_config_from_dict(data)
    assert cfg.diagramFocus.preset == "custom"
    assert "microsoft.compute/virtualmachines" in cfg.diagramFocus.resourceTypes
    assert cfg.diagramFocus.dependencyDepth == 2
    assert cfg.diagramFocus.networkScope == "immediate-vm-network"
    assert cfg.diagramFocus.diagramType == "network"


def test_load_config_from_dict_invalid_preset_raises():
    """Unknown preset raises ValueError."""
    data = {
        "app": "test",
        "subscriptions": ["00000000-0000-0000-0000-000000000001"],
        "outputDir": "/tmp/test",
        "seedEntireSubscriptions": True,
        "diagramFocus": {"preset": "unknown-preset"},
    }
    with pytest.raises(ValueError, match="diagramFocus.preset"):
        load_config_from_dict(data)
