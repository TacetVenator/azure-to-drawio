"""Tests for graph edge extraction using fixture data."""
import json
import pytest
from pathlib import Path
from tools.azdisc.graph import build_node, extract_edges

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_vm_to_nic_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    vm_nic_edges = [e for e in edges if e["kind"] == "vm->nic"]
    assert len(vm_nic_edges) >= 1


def test_vm_to_disk_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    vm_disk_edges = [e for e in edges if e["kind"] == "vm->disk"]
    assert len(vm_disk_edges) >= 1


def test_nic_to_subnet_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    nic_subnet_edges = [e for e in edges if e["kind"] == "nic->subnet"]
    assert len(nic_subnet_edges) >= 1


def test_nic_to_nsg_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    nic_nsg_edges = [e for e in edges if e["kind"] == "nic->nsg"]
    assert len(nic_nsg_edges) >= 1


def test_subnet_to_vnet_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    subnet_vnet_edges = [e for e in edges if e["kind"] == "subnet->vnet"]
    assert len(subnet_vnet_edges) >= 1


def test_subnet_to_nsg_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    subnet_nsg_edges = [e for e in edges if e["kind"] == "subnet->nsg"]
    assert len(subnet_nsg_edges) >= 1


def test_subnet_to_routetable_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    udr_edges = [e for e in edges if e["kind"] == "subnet->routeTable"]
    assert len(udr_edges) >= 1


def test_vnet_peering_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    vnet_peer_edges = [e for e in edges if e["kind"] == "vnet->peeredVnet"]
    assert len(vnet_peer_edges) >= 1


def test_webapp_to_plan_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    wa_plan_edges = [e for e in edges if e["kind"] == "webApp->appServicePlan"]
    assert len(wa_plan_edges) >= 1


def test_webapp_to_subnet_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    wa_sub_edges = [e for e in edges if e["kind"] == "webApp->subnet"]
    assert len(wa_sub_edges) >= 1


def test_private_endpoint_edges():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    pe_subnet = [e for e in edges if e["kind"] == "privateEndpoint->subnet"]
    pe_target = [e for e in edges if e["kind"] == "privateEndpoint->target"]
    assert len(pe_subnet) >= 1
    assert len(pe_target) >= 1


def test_lb_to_nic_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    lb_nic_edges = [e for e in edges if e["kind"] == "loadBalancer->backendNic"]
    assert len(lb_nic_edges) >= 1


def test_public_ip_edge():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    pip_edges = [e for e in edges if e["kind"] == "publicIp->attachment"]
    assert len(pip_edges) >= 1


def test_edges_are_sorted():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    keys = [(e["source"], e["target"], e["kind"]) for e in edges]
    assert keys == sorted(keys)


def test_no_duplicate_edges():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    edges = extract_edges(nodes)
    keys = [(e["source"], e["target"], e["kind"]) for e in edges]
    assert len(keys) == len(set(keys))
