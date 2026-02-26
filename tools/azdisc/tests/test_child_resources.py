"""Tests for child resource filtering and attribute collection."""
import json
from pathlib import Path
from tools.azdisc.graph import (
    build_node, _is_child_resource, _find_parent_id, _collect_attributes,
)
from tools.azdisc.util import extract_arm_ids

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_vm_extensions_are_child_resources():
    assert _is_child_resource("microsoft.compute/virtualmachines/extensions")


def test_sql_firewall_rules_are_child_resources():
    assert _is_child_resource("microsoft.sql/servers/firewallrules")


def test_vm_is_not_child_resource():
    assert not _is_child_resource("microsoft.compute/virtualmachines")


def test_subnet_is_not_child_resource():
    """Subnets under microsoft.network are intentionally kept as standalone nodes."""
    assert not _is_child_resource("microsoft.network/virtualnetworks/subnets")


def test_find_parent_id_for_extension():
    ext_id = "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1/extensions/mde.linux"
    parent = _find_parent_id(ext_id, "microsoft.compute/virtualmachines/extensions")
    assert parent == "/subscriptions/sub1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1"


def test_vm_attributes_include_sku_and_image():
    inventory = load_fixture("inventory_small.json")
    vm_resource = [r for r in inventory if r["type"] == "Microsoft.Compute/virtualMachines"][0]
    node = build_node(vm_resource)
    attrs = _collect_attributes(node)
    assert any("Standard_D4s_v3" in a for a in attrs), f"SKU not found in {attrs}"
    assert any("Canonical" in a for a in attrs), f"Image not found in {attrs}"


def test_vm_extensions_not_in_nodes():
    """VM extensions from fixture should be filtered out as standalone nodes."""
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    ext_nodes = [n for n in nodes if "extensions" in n["type"]]
    # build_node creates them, but build_graph should filter them
    # Here we test that _is_child_resource correctly identifies them
    for n in ext_nodes:
        assert _is_child_resource(n["type"])


def test_non_resource_ids_filtered():
    """Marketplace image references should not be extracted as ARM IDs."""
    props = {
        "imageReference": {
            "id": "/subscriptions/sub1/providers/Microsoft.Compute/locations/eastus/publishers/Canonical"
        }
    }
    ids = list(extract_arm_ids(props))
    assert len(ids) == 0, f"Non-resource IDs should be filtered: {ids}"


def test_normal_resource_ids_still_extracted():
    """Normal resource ARM IDs should still be extracted."""
    props = {
        "subnet": {
            "id": "/subscriptions/sub1/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/sub1"
        }
    }
    ids = list(extract_arm_ids(props))
    assert len(ids) == 1
