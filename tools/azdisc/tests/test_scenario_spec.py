from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.scenario_spec import (
    BUILTIN_TEMPLATES,
    parse_scenario_spec,
    scenario_spec_to_graph,
)

_FIXTURES = Path(__file__).parent / "fixtures"


_SAMPLE = """
Create an Azure architecture diagram.

Scenario: enterprise multi-tier web app, single region, private data access.

Resources:
1. **Networking**
  - VNet: "vnet-enterprise-prod-aue-001" (10.10.0.0/16)
  - Subnets:
    - "snet-frontend" (10.10.1.0/24)
    - "snet-app" (10.10.2.0/24)
2. **Application**
  - Web App: "app-enterprise-web-prod"
  - Azure Function App: "func-enterprise-worker-prod"
3. **Data**
  - Azure Key Vault: "kv-enterprise-prod"

Connections:
- User Browser → Azure Front Door → Application Gateway (WAF) → Web App
- Web App → Azure Function App
- Web App → Azure Key Vault

Layout rules:
- Left to right flow.
- Group by network, application, data.
""".strip()


def test_parse_scenario_spec_extracts_sections():
    spec = parse_scenario_spec(_SAMPLE)

    assert spec.title == "Create an Azure architecture diagram."
    assert spec.scenario == "enterprise multi-tier web app, single region, private data access."
    assert len(spec.resources) >= 5
    assert spec.resources[0].category == "Networking"
    assert spec.resources[0].kind == "VNet"
    assert spec.resources[0].name == "vnet-enterprise-prod-aue-001"
    assert spec.resources[0].cidr == "10.10.0.0/16"

    names = {r.name for r in spec.resources}
    assert "app-enterprise-web-prod" in names
    assert "func-enterprise-worker-prod" in names
    assert "kv-enterprise-prod" in names

    assert len(spec.connections) == 3
    assert spec.connections[0].chain[0] == "User Browser"
    assert spec.connections[0].chain[-1] == "Web App"
    assert spec.layout_rules == [
        "Left to right flow.",
        "Group by network, application, data.",
    ]


def test_scenario_spec_to_graph_creates_nodes_edges_and_actors():
    spec = parse_scenario_spec(_SAMPLE)

    graph = scenario_spec_to_graph(spec)

    assert "nodes" in graph
    assert "edges" in graph
    assert graph["title"] == "Create an Azure architecture diagram."

    node_types = {n["type"] for n in graph["nodes"]}
    assert "microsoft.web/sites" in node_types
    assert "microsoft.keyvault/vaults" in node_types

    # User Browser and Azure Front Door are not explicit resources, so they
    # should be synthesized as deterministic scenario actors.
    actor_names = {n["name"] for n in graph["nodes"] if n["type"] == "scenario/actor"}
    assert "User Browser" in actor_names
    assert "Azure Front Door" in actor_names

    assert len(graph["edges"]) >= 4
    assert all(edge["kind"] == "scenario-flow" for edge in graph["edges"])


# ---------------------------------------------------------------------------
# BUILTIN_TEMPLATES coverage
# ---------------------------------------------------------------------------

def test_builtin_templates_are_registered():
  assert "enterprise-multitier-web" in BUILTIN_TEMPLATES
  assert "vm-network-immediate" in BUILTIN_TEMPLATES
  assert "vm-application-interactions" in BUILTIN_TEMPLATES


def test_builtin_template_vm_network_immediate_matches_fixture():
  fixture = json.loads(
    (_FIXTURES / "scenario_vm_network_immediate_expected.json").read_text()
  )
  spec = parse_scenario_spec(BUILTIN_TEMPLATES["vm-network-immediate"])
  graph = scenario_spec_to_graph(spec)

  assert spec.title == fixture["title"]
  assert len(spec.resources) == fixture["resource_count"]
  assert len(spec.connections) == fixture["connection_count"]
  assert len(spec.layout_rules) == fixture["layout_rule_count"]
  assert len(graph["nodes"]) == fixture["total_nodes"]
  assert len(graph["edges"]) == fixture["total_edges"]


def test_builtin_template_enterprise_multitier_matches_fixture():
  fixture = json.loads(
    (_FIXTURES / "scenario_enterprise_multitier_expected.json").read_text()
  )
  spec = parse_scenario_spec(BUILTIN_TEMPLATES["enterprise-multitier-web"])
  graph = scenario_spec_to_graph(spec)

  assert spec.title == fixture["title"]
  assert len(spec.connections) == fixture["connection_count"]

  actual_types = {n["type"] for n in graph["nodes"]}
  for expected_type in fixture["expected_arm_types"]:
    assert expected_type in actual_types, f"Missing ARM type: {expected_type}"


def test_all_builtin_templates_parse_without_error():
  for name, text in BUILTIN_TEMPLATES.items():
    spec = parse_scenario_spec(text)
    graph = scenario_spec_to_graph(spec)
    assert spec.title, f"Template {name!r}: expected non-empty title"
    assert len(graph["nodes"]) > 0, f"Template {name!r}: expected at least one node"
    assert len(graph["edges"]) > 0, f"Template {name!r}: expected at least one edge"
