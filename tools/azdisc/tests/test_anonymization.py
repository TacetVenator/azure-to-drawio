"""Unit tests for tools.azdisc.anonymize."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.azdisc.anonymize import ResourceAnonymizer


# ── Alias determinism ──────────────────────────────────────────────────────────

class TestAliasDeterminism:
    def test_same_value_same_alias(self):
        anon = ResourceAnonymizer(salt="")
        a1 = anon.alias_subscription("00000000-1111-2222-3333-444444444444")
        a2 = anon.alias_subscription("00000000-1111-2222-3333-444444444444")
        assert a1 == a2

    def test_different_values_different_aliases(self):
        anon = ResourceAnonymizer(salt="")
        a1 = anon.alias_subscription("aaaaaaaa-0000-0000-0000-000000000001")
        a2 = anon.alias_subscription("aaaaaaaa-0000-0000-0000-000000000002")
        assert a1 != a2

    def test_same_value_different_categories_different_aliases(self):
        anon = ResourceAnonymizer(salt="")
        a1 = anon.alias_subscription("some-name")
        a2 = anon.alias_resource_name("some-name")
        assert a1 != a2

    def test_deterministic_across_instances(self):
        """Two anonymizers with the same salt must produce identical aliases."""
        anon1 = ResourceAnonymizer(salt="test-salt")
        anon2 = ResourceAnonymizer(salt="test-salt")
        assert anon1.alias_resource_name("vm-web-01") == anon2.alias_resource_name("vm-web-01")

    def test_different_salts_different_aliases(self):
        anon1 = ResourceAnonymizer(salt="salt-a")
        anon2 = ResourceAnonymizer(salt="salt-b")
        assert anon1.alias_resource_name("vm-web-01") != anon2.alias_resource_name("vm-web-01")


# ── Alias prefixes ─────────────────────────────────────────────────────────────

class TestAliasPrefixes:
    def test_subscription_prefix(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_subscription("sub-id-value")
        assert alias.startswith("sub-")

    def test_resource_group_prefix(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_resource_group("rg-prod-eastus")
        assert alias.startswith("rg-")

    def test_resource_name_prefix(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_resource_name("vm-web-server-01")
        assert alias.startswith("res-")

    def test_tenant_prefix(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_tenant("tenant-id-001")
        assert alias.startswith("ten-")

    def test_principal_id_prefix(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_principal_id("oid-value-001")
        assert alias.startswith("oid-")

    def test_principal_email_format(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_principal_email("alice@contoso.com")
        assert alias.endswith("@anon.example")
        assert alias.startswith("user-")

    def test_tag_key_prefix(self):
        anon = ResourceAnonymizer()
        assert anon.alias_tag_key("Application").startswith("tagkey-")

    def test_tag_value_prefix(self):
        anon = ResourceAnonymizer()
        assert anon.alias_tag_value("SAP-ERP").startswith("tagval-")


# ── IP address aliases ─────────────────────────────────────────────────────────

class TestIPAddressAliases:
    def test_private_ip_uses_rfc1918_range(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_ipv4("10.1.2.3")
        parts = alias.split(".")
        assert parts[0] == "10"
        assert parts[1] == "100"

    def test_public_ip_uses_doc_range(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_ipv4("52.169.10.5")
        assert alias.startswith("203.0.113.")

    def test_private_172_range(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_ipv4("172.16.0.5")
        assert alias.startswith("10.100.")

    def test_private_192_168_range(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_ipv4("192.168.1.100")
        assert alias.startswith("10.100.")

    def test_same_ip_same_alias(self):
        anon = ResourceAnonymizer()
        assert anon.alias_ipv4("10.0.1.1") == anon.alias_ipv4("10.0.1.1")

    def test_different_ips_different_aliases(self):
        anon = ResourceAnonymizer()
        assert anon.alias_ipv4("10.0.1.1") != anon.alias_ipv4("10.0.1.2")


# ── FQDN aliases ───────────────────────────────────────────────────────────────

class TestFQDNAliases:
    def test_custom_fqdn_anonymized(self):
        anon = ResourceAnonymizer()
        alias = anon.alias_fqdn("myserver.contoso.com")
        assert "contoso" not in alias
        assert alias.endswith(".anon.example")

    def test_azure_domain_preserved(self):
        anon = ResourceAnonymizer()
        assert anon.alias_fqdn("myapp.azurewebsites.net") == "myapp.azurewebsites.net"

    def test_microsoft_domain_preserved(self):
        anon = ResourceAnonymizer()
        assert anon.alias_fqdn("management.azure.com") == "management.azure.com"


# ── ARM ID rewriting ───────────────────────────────────────────────────────────

class TestArmIdRewriting:
    SUB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    RG = "rg-production-eastus"
    NAME = "vm-webserver-01"

    def _arm_id(self, sub=None, rg=None, name=None):
        sub = sub or self.SUB
        rg = rg or self.RG
        name = name or self.NAME
        return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{name}"

    def test_subscription_is_replaced(self):
        anon = ResourceAnonymizer()
        result = anon.rewrite_arm_id(self._arm_id())
        assert self.SUB.lower() not in result.lower()
        assert "sub-" in result

    def test_resource_group_is_replaced(self):
        anon = ResourceAnonymizer()
        result = anon.rewrite_arm_id(self._arm_id())
        assert self.RG.lower() not in result.lower()
        assert "rg-" in result

    def test_resource_name_is_replaced(self):
        anon = ResourceAnonymizer()
        result = anon.rewrite_arm_id(self._arm_id())
        assert self.NAME.lower() not in result.lower()
        assert "res-" in result

    def test_provider_namespace_preserved(self):
        anon = ResourceAnonymizer()
        result = anon.rewrite_arm_id(self._arm_id())
        assert "Microsoft.Compute" in result

    def test_resource_type_preserved(self):
        anon = ResourceAnonymizer()
        result = anon.rewrite_arm_id(self._arm_id())
        assert "virtualMachines" in result

    def test_consistent_across_two_rewrites(self):
        """Same original in two calls → same alias."""
        anon = ResourceAnonymizer()
        r1 = anon.rewrite_arm_id(self._arm_id())
        r2 = anon.rewrite_arm_id(self._arm_id())
        assert r1 == r2

    def test_structure_preserved(self):
        anon = ResourceAnonymizer()
        result = anon.rewrite_arm_id(self._arm_id())
        assert result.startswith("/subscriptions/")
        assert "/resourceGroups/" in result
        assert "/providers/Microsoft.Compute/virtualMachines/" in result

    def test_non_arm_id_unchanged(self):
        anon = ResourceAnonymizer()
        assert anon.rewrite_arm_id("plain-string") == "plain-string"
        assert anon.rewrite_arm_id("") == ""


# ── Resource item transformation ───────────────────────────────────────────────

class TestAnonResourceItem:
    ITEM = {
        "id": "/subscriptions/sub-abc/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web01",
        "name": "vm-web01",
        "type": "microsoft.compute/virtualmachines",
        "resourceGroup": "rg-prod",
        "subscriptionId": "sub-abc",
        "location": "eastus",
        "tags": {"Application": "Billing", "Owner": "alice@contoso.com"},
        "properties": {
            "privateIPAddress": "10.0.1.5",
        },
    }

    def test_name_is_anonymized(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert out["name"] != "vm-web01"
        assert out["name"].startswith("res-")

    def test_resource_group_is_anonymized(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert out["resourceGroup"] != "rg-prod"
        assert out["resourceGroup"].startswith("rg-")

    def test_subscription_is_anonymized(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert out["subscriptionId"] != "sub-abc"
        assert out["subscriptionId"].startswith("sub-")

    def test_location_preserved(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert out["location"] == "eastus"

    def test_type_preserved(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert out["type"] == "microsoft.compute/virtualmachines"

    def test_arm_id_rewritten(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert "sub-abc" not in out["id"]
        assert "rg-prod" not in out["id"]
        assert "vm-web01" not in out["id"]

    def test_tag_keys_anonymized(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert "Application" not in out["tags"]
        assert "Owner" not in out["tags"]
        for k in out["tags"]:
            assert k.startswith("tagkey-")

    def test_tag_values_anonymized(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        for v in out["tags"].values():
            if v is not None:
                assert v.startswith("tagval-")

    def test_private_ip_in_properties_anonymized(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert out["properties"]["privateIPAddress"] != "10.0.1.5"
        assert out["properties"]["privateIPAddress"].startswith("10.100.")

    def test_output_structurally_same(self):
        anon = ResourceAnonymizer()
        out = anon.anon_resource_item(self.ITEM)
        assert set(out.keys()) == set(self.ITEM.keys())


# ── JSON file processing ───────────────────────────────────────────────────────

class TestAnonJsonFile:
    def _write_inventory(self, path: Path, items: list) -> None:
        path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def test_inventory_json_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "inventory.json"
            self._write_inventory(p, [
                {
                    "id": "/subscriptions/real-sub/resourceGroups/real-rg/providers/Microsoft.Network/virtualNetworks/real-vnet",
                    "name": "real-vnet",
                    "type": "microsoft.network/virtualnetworks",
                    "resourceGroup": "real-rg",
                    "subscriptionId": "real-sub",
                    "location": "westeurope",
                    "tags": {"Env": "prod"},
                }
            ])
            anon = ResourceAnonymizer()
            assert anon.anon_json_file(p) is True
            data = json.loads(p.read_text())
            assert data[0]["name"] != "real-vnet"
            assert data[0]["resourceGroup"] != "real-rg"
            assert "real-sub" not in data[0]["id"]

    def test_returns_false_for_missing_file(self):
        anon = ResourceAnonymizer()
        assert anon.anon_json_file(Path("/nonexistent/path/x.json")) is False

    def test_graph_json_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "graph.json"
            p.write_text(json.dumps({
                "nodes": [
                    {"id": "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
                     "name": "vm1", "resourceGroup": "rg1", "subscriptionId": "s1"}
                ],
                "edges": [
                    {"source": "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
                     "target": "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1",
                     "type": "belongs-to"}
                ],
            }), encoding="utf-8")
            anon = ResourceAnonymizer()
            anon.anon_json_file(p)
            data = json.loads(p.read_text())
            assert "vm1" not in data["nodes"][0]["name"]
            assert "rg1" not in data["edges"][0]["source"]
            assert data["edges"][0]["type"] == "belongs-to"  # non-sensitive field preserved


# ── Text file processing ───────────────────────────────────────────────────────

class TestAnonTextFile:
    def test_known_values_replaced_in_log(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "pipeline.log"
            anon = ResourceAnonymizer()
            # Pre-populate map by processing an inventory item
            anon.anon_resource_item({
                "id": "/subscriptions/real-sub-001/resourceGroups/rg-contoso-prod/providers/Microsoft.Compute/virtualMachines/vm-001",
                "name": "vm-001",
                "resourceGroup": "rg-contoso-prod",
                "subscriptionId": "real-sub-001",
            })
            log_path.write_text(
                "2024-01-01 Processing rg-contoso-prod/vm-001 in subscription real-sub-001",
                encoding="utf-8",
            )
            anon.anon_text_file(log_path)
            content = log_path.read_text()
            assert "rg-contoso-prod" not in content
            assert "vm-001" not in content
            assert "real-sub-001" not in content

    def test_returns_false_for_missing_file(self):
        anon = ResourceAnonymizer()
        assert anon.anon_text_file(Path("/nonexistent/path/x.log")) is False


# ── Map persistence ────────────────────────────────────────────────────────────

class TestSaveMap:
    def test_map_written_as_json(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = Path(td) / ".anon-map.json"
            anon = ResourceAnonymizer()
            anon.alias_subscription("real-sub-001")
            anon.alias_resource_group("rg-prod")
            anon.save_map(map_path)

            data = json.loads(map_path.read_text())
            assert "mappings" in data
            assert "_note" in data
            assert "sub" in data["mappings"]
            assert "rg-prod" in data["mappings"].get("rg", {})

    def test_mapping_count_property(self):
        anon = ResourceAnonymizer()
        assert anon.mapping_count == 0
        anon.alias_subscription("s1")
        anon.alias_resource_group("rg1")
        assert anon.mapping_count == 2


# ── Config flag integration ────────────────────────────────────────────────────

class TestConfigAnonymizeFlag:
    def test_anonymize_output_default_false(self):
        from tools.azdisc.config import load_config_from_dict
        cfg = load_config_from_dict({
            "app": "test",
            "subscriptions": ["s1"],
            "outputDir": "/tmp/test",
            "seedResourceGroups": ["rg1"],
        })
        assert cfg.anonymizeOutput is False
        assert cfg.anonymizeSalt == ""

    def test_anonymize_output_enabled(self):
        from tools.azdisc.config import load_config_from_dict
        cfg = load_config_from_dict({
            "app": "test",
            "subscriptions": ["s1"],
            "outputDir": "/tmp/test",
            "seedResourceGroups": ["rg1"],
            "anonymizeOutput": True,
            "anonymizeSalt": "my-secret",
        })
        assert cfg.anonymizeOutput is True
        assert cfg.anonymizeSalt == "my-secret"

    def test_anonymize_output_bad_type_raises(self):
        from tools.azdisc.config import load_config_from_dict
        with pytest.raises(ValueError, match="anonymizeOutput"):
            load_config_from_dict({
                "app": "test",
                "subscriptions": ["s1"],
                "outputDir": "/tmp/test",
                "seedResourceGroups": ["rg1"],
                "anonymizeOutput": "yes",
            })

    def test_anonymize_salt_bad_type_raises(self):
        from tools.azdisc.config import load_config_from_dict
        with pytest.raises(ValueError, match="anonymizeSalt"):
            load_config_from_dict({
                "app": "test",
                "subscriptions": ["s1"],
                "outputDir": "/tmp/test",
                "seedResourceGroups": ["rg1"],
                "anonymizeSalt": 42,
            })


# ── apply_output_dir integration ──────────────────────────────────────────────

class TestApplyOutputDir:
    def _make_output_dir(self, tmp: Path) -> Path:
        tmp.mkdir(parents=True, exist_ok=True)
        # inventory.json
        (tmp / "inventory.json").write_text(json.dumps([
            {
                "id": "/subscriptions/sub-real/resourceGroups/rg-real/providers/Microsoft.Compute/virtualMachines/vm-real",
                "name": "vm-real",
                "type": "microsoft.compute/virtualmachines",
                "resourceGroup": "rg-real",
                "subscriptionId": "sub-real",
                "location": "eastus",
                "tags": {"App": "PayrollSystem"},
            }
        ]), encoding="utf-8")
        # pipeline.log
        (tmp / "pipeline.log").write_text(
            "Processing vm-real in rg-real under sub-real\n",
            encoding="utf-8",
        )
        return tmp

    def test_inventory_no_sensitive_after_apply(self):
        with tempfile.TemporaryDirectory() as td:
            out = self._make_output_dir(Path(td))
            anon = ResourceAnonymizer(salt="test")
            anon.apply_output_dir(out)
            data = json.loads((out / "inventory.json").read_text())
            item = data[0]
            assert "vm-real" not in json.dumps(item)
            assert "rg-real" not in json.dumps(item)
            assert "sub-real" not in json.dumps(item)
            assert "PayrollSystem" not in json.dumps(item)

    def test_log_no_sensitive_after_apply(self):
        with tempfile.TemporaryDirectory() as td:
            out = self._make_output_dir(Path(td))
            anon = ResourceAnonymizer(salt="test")
            anon.apply_output_dir(out)
            log_content = (out / "pipeline.log").read_text()
            assert "vm-real" not in log_content
            assert "rg-real" not in log_content
            assert "sub-real" not in log_content

    def test_apply_on_missing_dir_does_not_raise(self):
        anon = ResourceAnonymizer()
        anon.apply_output_dir(Path("/nonexistent/output/dir"))  # should log and return cleanly

    def test_location_preserved_in_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            out = self._make_output_dir(Path(td))
            anon = ResourceAnonymizer(salt="test")
            anon.apply_output_dir(out)
            data = json.loads((out / "inventory.json").read_text())
            assert data[0]["location"] == "eastus"
