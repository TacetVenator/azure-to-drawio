"""Tests for ARM ID parsing and normalization."""
import pytest
from tools.azdisc.util import extract_arm_ids, normalize_id, stable_id


def test_normalize_id_lowercase():
    arm_id = "/subscriptions/ABC/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/VM1"
    assert normalize_id(arm_id) == arm_id.lower()


def test_normalize_id_strips_trailing_slash():
    arm_id = "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1/"
    assert normalize_id(arm_id) == arm_id.lower().rstrip("/")


def test_extract_arm_ids_from_string():
    text = "something /subscriptions/abc-123/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1 other"
    ids = list(extract_arm_ids(text))
    assert len(ids) == 1
    assert "/subscriptions/abc-123/resourcegroups/rg1/providers/microsoft.network/virtualnetworks/vnet1" in ids


def test_extract_arm_ids_from_dict():
    props = {
        "networkProfile": {
            "networkInterfaces": [
                {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic1"}
            ]
        }
    }
    ids = list(extract_arm_ids(props))
    assert any("nic1" in i for i in ids)


def test_extract_arm_ids_from_nested_list():
    data = [
        "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
        {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1"},
    ]
    ids = list(extract_arm_ids(data))
    assert any("vm1" in i for i in ids)
    assert any("sa1" in i for i in ids)


def test_extract_arm_ids_deduplicates():
    text = "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet1 " \
           "/subscriptions/abc/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet1"
    ids = list(extract_arm_ids(text))
    assert len(ids) == 1


def test_stable_id_deterministic():
    sid1 = stable_id("/subscriptions/abc/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm1")
    sid2 = stable_id("/subscriptions/abc/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm1")
    assert sid1 == sid2


def test_stable_id_length():
    sid = stable_id("some-resource-id")
    assert len(sid) == 16


def test_stable_id_is_lowercase_hex():
    sid = stable_id("some-resource-id")
    assert all(c in "0123456789abcdef" for c in sid)


def test_stable_id_case_insensitive():
    sid1 = stable_id("/subscriptions/ABC/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/VM1")
    sid2 = stable_id("/subscriptions/abc/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1")
    assert sid1 == sid2
