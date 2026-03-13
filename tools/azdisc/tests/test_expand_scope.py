"""Tests for expandScope config option and scoped discovery.

Verifies that expandScope=related (default) only follows known relationship
types, while expandScope=all follows every ARM reference in properties.
"""
import pytest

from tools.azdisc.config import Config, VALID_EXPAND_SCOPES, load_config
from tools.azdisc.discover import _extract_related_ids
from tools.azdisc.util import extract_arm_ids, normalize_id


# ── Config tests ─────────────────────────────────────────────────────────


class TestExpandScopeConfig:
    def test_default_is_related(self):
        cfg = Config(
            app="test",
            subscriptions=["sub1"],
            seedResourceGroups=["rg1"],
            outputDir="/tmp/test",
        )
        assert cfg.expandScope == "related"

    def test_all_is_valid(self):
        cfg = Config(
            app="test",
            subscriptions=["sub1"],
            seedResourceGroups=["rg1"],
            outputDir="/tmp/test",
            expandScope="all",
        )
        assert cfg.expandScope == "all"

    def test_valid_values(self):
        assert VALID_EXPAND_SCOPES == {"related", "all"}

    def test_load_config_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"app":"t","subscriptions":["s"],"seedResourceGroups":["rg"],"outputDir":"/tmp/t"}')
        cfg = load_config(str(cfg_file))
        assert cfg.expandScope == "related"

    def test_load_config_explicit_all(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"app":"t","subscriptions":["s"],"seedResourceGroups":["rg"],"outputDir":"/tmp/t","expandScope":"all"}')
        cfg = load_config(str(cfg_file))
        assert cfg.expandScope == "all"

    def test_load_config_invalid_scope(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text('{"app":"t","subscriptions":["s"],"seedResourceGroups":["rg"],"outputDir":"/tmp/t","expandScope":"invalid"}')
        with pytest.raises(ValueError, match="expandScope"):
            load_config(str(cfg_file))


# ── _extract_related_ids tests ───────────────────────────────────────────


class TestExtractRelatedIds:
    """Verify that scoped extraction only returns expected references."""

    def test_vm_extracts_nic_and_disk(self):
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "type": "Microsoft.Compute/virtualMachines",
            "properties": {
                "networkProfile": {
                    "networkInterfaces": [
                        {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic1"}
                    ]
                },
                "storageProfile": {
                    "osDisk": {
                        "managedDisk": {
                            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/disks/osdisk1"
                        }
                    },
                    "dataDisks": [
                        {"managedDisk": {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/disks/data1"}}
                    ],
                    "imageReference": {
                        "id": "/subscriptions/sub1/resourceGroups/rg-images/providers/Microsoft.Compute/galleries/gallery1/images/img1/versions/1.0.0"
                    }
                }
            }
        }
        ids = _extract_related_ids(resource)
        assert any("nic1" in i for i in ids)
        assert any("osdisk1" in i for i in ids)
        assert any("data1" in i for i in ids)
        # Image gallery reference should NOT be followed in scoped mode
        assert not any("gallery" in i for i in ids)

    def test_vm_does_not_follow_image_gallery(self):
        """Scoped mode should not chase image gallery/marketplace references."""
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "type": "Microsoft.Compute/virtualMachines",
            "properties": {
                "storageProfile": {
                    "imageReference": {
                        "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Compute/galleries/sharedGallery/images/myImage/versions/1.0.0",
                        "publisher": "Canonical",
                        "offer": "UbuntuServer",
                    }
                },
                "networkProfile": {"networkInterfaces": []},
            }
        }
        ids = _extract_related_ids(resource)
        assert len(ids) == 0

    def test_nic_extracts_subnet_nsg_asg(self):
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic1",
            "type": "Microsoft.Network/networkInterfaces",
            "properties": {
                "networkSecurityGroup": {
                    "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/networkSecurityGroups/nsg1"
                },
                "ipConfigurations": [
                    {
                        "properties": {
                            "subnet": {
                                "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet1"
                            },
                            "applicationSecurityGroups": [
                                {"id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/applicationSecurityGroups/asg1"}
                            ]
                        }
                    }
                ]
            }
        }
        ids = _extract_related_ids(resource)
        assert any("nsg1" in i for i in ids)
        assert any("snet1" in i for i in ids)
        assert any("asg1" in i for i in ids)

    def test_subnet_extracts_nsg_and_udr(self):
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet1",
            "type": "Microsoft.Network/virtualNetworks/subnets",
            "properties": {
                "networkSecurityGroup": {
                    "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/networkSecurityGroups/nsg1"
                },
                "routeTable": {
                    "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/routeTables/udr1"
                },
                "addressPrefix": "10.0.0.0/24",
            }
        }
        ids = _extract_related_ids(resource)
        assert any("nsg1" in i for i in ids)
        assert any("udr1" in i for i in ids)

    def test_route_table_does_not_chase_next_hops(self):
        """Route tables should not follow nextHopIpAddress or other references
        which would pull in appliances across the tenant."""
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/routeTables/udr1",
            "type": "Microsoft.Network/routeTables",
            "properties": {
                "routes": [
                    {
                        "properties": {
                            "addressPrefix": "0.0.0.0/0",
                            "nextHopType": "VirtualAppliance",
                            "nextHopIpAddress": "10.0.1.4",
                        }
                    }
                ],
                "subnets": [
                    {"id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet1"}
                ]
            }
        }
        ids = _extract_related_ids(resource)
        # Route tables are leaf nodes in scoped mode
        assert len(ids) == 0

    def test_scoped_vs_full_on_rich_resource(self):
        """Demonstrate that scoped extraction returns far fewer IDs than full."""
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1",
            "type": "Microsoft.Network/virtualNetworks",
            "properties": {
                "subnets": [
                    {
                        "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet1",
                        "properties": {
                            "networkSecurityGroup": {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg1"},
                            "routeTable": {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/routeTables/udr1"},
                            "serviceEndpoints": [{"provisioningState": "Succeeded"}],
                            "delegations": [],
                        }
                    },
                    {
                        "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet2",
                        "properties": {
                            "networkSecurityGroup": {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg2"},
                        }
                    },
                ],
                "virtualNetworkPeerings": [
                    {
                        "properties": {
                            "remoteVirtualNetwork": {"id": "/subscriptions/sub2/resourceGroups/rg2/providers/Microsoft.Network/virtualNetworks/vnet2"},
                            "remoteAddressSpace": {"addressPrefixes": ["10.2.0.0/16"]},
                        }
                    }
                ],
                "dhcpOptions": {},
                "enableDdosProtection": False,
            }
        }
        scoped_ids = _extract_related_ids(resource)
        full_ids = set(extract_arm_ids(resource.get("properties", {})))

        # Scoped should only get the peered VNET
        assert len(scoped_ids) == 1
        assert any("vnet2" in i for i in scoped_ids)

        # Full extraction would get subnets, NSGs, UDRs, and the peered VNET
        assert len(full_ids) > len(scoped_ids)
        # Full would also grab the subnet IDs, NSG IDs, route table IDs
        assert any("nsg1" in i for i in full_ids)
        assert any("udr1" in i for i in full_ids)
        assert any("snet1" in i for i in full_ids)

    def test_unknown_type_returns_empty(self):
        """Resources with unrecognized types should not produce references."""
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.SomeNew/service/svc1",
            "type": "Microsoft.SomeNew/service",
            "properties": {
                "linkedResource": {"id": "/subscriptions/sub1/resourceGroups/rg2/providers/Microsoft.Other/thing/t1"}
            }
        }
        ids = _extract_related_ids(resource)
        assert len(ids) == 0

    def test_private_endpoint_extracts_subnet_and_target(self):
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/privateEndpoints/pe1",
            "type": "Microsoft.Network/privateEndpoints",
            "properties": {
                "subnet": {"id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/pe-subnet"},
                "privateLinkServiceConnections": [
                    {"properties": {"privateLinkServiceId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1"}}
                ]
            }
        }
        ids = _extract_related_ids(resource)
        assert any("pe-subnet" in i for i in ids)
        assert any("sa1" in i for i in ids)

    def test_nsg_extracts_asg_references(self):
        resource = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkSecurityGroups/nsg1",
            "type": "Microsoft.Network/networkSecurityGroups",
            "properties": {
                "securityRules": [
                    {
                        "properties": {
                            "sourceApplicationSecurityGroups": [
                                {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/applicationSecurityGroups/src-asg"}
                            ],
                            "destinationApplicationSecurityGroups": [
                                {"id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/applicationSecurityGroups/dst-asg"}
                            ]
                        }
                    }
                ]
            }
        }
        ids = _extract_related_ids(resource)
        assert any("src-asg" in i for i in ids)
        assert any("dst-asg" in i for i in ids)
