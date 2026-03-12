"""Tests for Application Security Group (ASG) support across graph, docs, and diagram."""
import json
import pytest
from pathlib import Path
from tools.azdisc.graph import build_node, extract_edges

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def _build_edges(fixture_name="inventory_small.json"):
    inventory = load_fixture(fixture_name)
    nodes = [build_node(r) for r in inventory]
    return nodes, extract_edges(nodes)


# --- Graph edge extraction ---

class TestAsgEdgeExtraction:
    def test_nic_to_asg_edge(self):
        """NIC ipConfiguration.applicationSecurityGroups -> nic->asg edge."""
        _nodes, edges = _build_edges()
        asg_edges = [e for e in edges if e["kind"] == "nic->asg"]
        assert len(asg_edges) >= 1
        # Verify the specific ASG
        targets = {e["target"] for e in asg_edges}
        assert any("asg-web-tier" in t for t in targets)

    def test_nsg_rule_source_asg_edge(self):
        """NSG rule sourceApplicationSecurityGroups -> nsgRule->sourceAsg edge."""
        _nodes, edges = _build_edges()
        src_asg_edges = [e for e in edges if e["kind"] == "nsgRule->sourceAsg"]
        assert len(src_asg_edges) >= 1
        targets = {e["target"] for e in src_asg_edges}
        assert any("asg-web-tier" in t for t in targets)

    def test_nsg_rule_dest_asg_edge(self):
        """NSG rule destinationApplicationSecurityGroups -> nsgRule->destAsg edge."""
        _nodes, edges = _build_edges()
        dst_asg_edges = [e for e in edges if e["kind"] == "nsgRule->destAsg"]
        assert len(dst_asg_edges) >= 1
        targets = {e["target"] for e in dst_asg_edges}
        assert any("asg-app-tier" in t for t in targets)

    def test_asg_edges_are_deduplicated(self):
        """ASG edges should not have duplicates."""
        _nodes, edges = _build_edges()
        asg_edges = [e for e in edges if "asg" in e["kind"].lower()]
        keys = [(e["source"], e["target"], e["kind"]) for e in asg_edges]
        assert len(keys) == len(set(keys))

    def test_asg_nodes_created(self):
        """ASG resources should appear as standalone nodes."""
        nodes, _edges = _build_edges()
        asg_nodes = [n for n in nodes if n["type"] == "microsoft.network/applicationsecuritygroups"]
        assert len(asg_nodes) == 2
        names = {n["name"] for n in asg_nodes}
        assert names == {"asg-web-tier", "asg-app-tier"}


# --- NSG summary with ASG resolution ---

class TestNsgSummaryAsgResolution:
    def test_nsg_summary_resolves_asg_names(self):
        """extract_nsg_summaries should resolve ASG IDs to names in rule src/dst."""
        from tools.azdisc.drawio import extract_nsg_summaries
        nodes, edges = _build_edges()
        summaries = extract_nsg_summaries(nodes, edges)
        # There should be at least one NSG summary
        assert len(summaries) >= 1
        # Find the rule that uses ASGs
        for nsg_id, summary in summaries.items():
            for rule in summary["rules"]:
                if rule["name"] == "allow-web-to-app":
                    assert "asg-web-tier" in rule["src"]
                    assert "asg-app-tier" in rule["dst"]
                    return
        pytest.fail("Expected rule 'allow-web-to-app' with ASG references not found")

    def test_nsg_panel_label_shows_asg_names(self):
        """NSG panel label should display ASG names instead of raw IDs."""
        from tools.azdisc.drawio import extract_nsg_summaries, _format_nsg_panel_label
        nodes, edges = _build_edges()
        summaries = extract_nsg_summaries(nodes, edges)
        for nsg_id, summary in summaries.items():
            label = _format_nsg_panel_label(summary)
            # If this NSG has the ASG rule, verify the label contains the ASG name
            if any(r["name"] == "allow-web-to-app" for r in summary["rules"]):
                assert "asg-web-tier" in label
                assert "asg-app-tier" in label
                return
        pytest.fail("Expected NSG panel label with ASG names not found")


# --- Docs reporting ---

class TestAsgDocsReporting:
    def test_routing_md_contains_asg_section(self, tmp_path):
        """routing.md should contain an ASG section."""
        from tools.azdisc.config import Config
        from tools.azdisc.docs import _write_routing
        nodes, edges = _build_edges()
        cfg = Config.__new__(Config)
        cfg.app = "test-app"
        cfg.outputDir = str(tmp_path)
        _write_routing(cfg, nodes, edges)
        content = (tmp_path / "routing.md").read_text()
        assert "## Application Security Groups" in content
        assert "asg-web-tier" in content
        assert "asg-app-tier" in content

    def test_routing_md_asg_nic_membership(self, tmp_path):
        """routing.md ASG section should list member NICs."""
        from tools.azdisc.config import Config
        from tools.azdisc.docs import _write_routing
        nodes, edges = _build_edges()
        cfg = Config.__new__(Config)
        cfg.app = "test-app"
        cfg.outputDir = str(tmp_path)
        _write_routing(cfg, nodes, edges)
        content = (tmp_path / "routing.md").read_text()
        assert "Member NICs" in content
        assert "`nic1`" in content

    def test_routing_md_asg_nsg_rule_refs(self, tmp_path):
        """routing.md ASG section should list NSG rule references."""
        from tools.azdisc.config import Config
        from tools.azdisc.docs import _write_routing
        nodes, edges = _build_edges()
        cfg = Config.__new__(Config)
        cfg.app = "test-app"
        cfg.outputDir = str(tmp_path)
        _write_routing(cfg, nodes, edges)
        content = (tmp_path / "routing.md").read_text()
        assert "Referenced in NSG rules" in content

    def test_nsg_rules_show_asg_names_instead_of_prefix(self, tmp_path):
        """NSG rules in routing.md should show ASG names for source/destination."""
        from tools.azdisc.config import Config
        from tools.azdisc.docs import _write_routing
        nodes, edges = _build_edges()
        cfg = Config.__new__(Config)
        cfg.app = "test-app"
        cfg.outputDir = str(tmp_path)
        _write_routing(cfg, nodes, edges)
        content = (tmp_path / "routing.md").read_text()
        # The allow-web-to-app rule should show ASG names
        assert "asg-web-tier" in content
        assert "asg-app-tier" in content


# --- Icon mapping ---

class TestAsgIconMapping:
    def test_asg_icon_exists_in_map(self):
        icon_map = json.loads(
            (Path(__file__).parent.parent.parent.parent / "assets" / "azure_icon_map.json").read_text()
        )
        assert "microsoft.network/applicationsecuritygroups" in icon_map
        assert "Application_Security_Groups" in icon_map["microsoft.network/applicationsecuritygroups"]


# --- Diagram placement ---

class TestAsgDiagramPlacement:
    def test_asg_placed_in_subnet_via_nic(self):
        """ASGs should be placed in the same subnet as their member NICs."""
        from tools.azdisc.drawio import _build_network_membership
        nodes, edges = _build_edges()
        _vnet_subnets, subnet_members, unattached = _build_network_membership(nodes, edges)
        # Find the ASG node ID
        asg_ids = {n["id"] for n in nodes if n["type"] == "microsoft.network/applicationsecuritygroups"}
        # At least one ASG should be placed in a subnet
        placed_in_subnet = set()
        for sid, members in subnet_members.items():
            placed_in_subnet.update(set(members) & asg_ids)
        assert len(placed_in_subnet) >= 1

    def test_asg_in_association_edge_kinds(self):
        """ASG edge kinds should be classified as association edges."""
        from tools.azdisc.drawio import _ASSOCIATION_EDGE_KINDS
        assert "nic->asg" in _ASSOCIATION_EDGE_KINDS
        assert "nsgRule->sourceAsg" in _ASSOCIATION_EDGE_KINDS
        assert "nsgRule->destAsg" in _ASSOCIATION_EDGE_KINDS

    def test_asg_in_network_types(self):
        """ASG type should be in the _NETWORK_TYPES set."""
        from tools.azdisc.drawio import _NETWORK_TYPES
        assert "microsoft.network/applicationsecuritygroups" in _NETWORK_TYPES
