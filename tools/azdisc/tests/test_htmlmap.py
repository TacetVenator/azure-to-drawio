from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.graph import build_graph
from tools.azdisc.htmlmap import ARTIFACT_CHOICES, build_html_view_model, classify_edge_kind, generate_html

FIXTURES = Path(__file__).parent / "fixtures"


def _make_config(tmp_path: Path) -> Config:
    cfg = Config(
        app="contoso-app",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
    )
    cfg.deepDiscovery.enabled = True
    cfg.deepDiscovery.searchStrings = ["sap", "bpc"]
    return cfg


def _seed_output_files(tmp_path: Path) -> None:
    fixture = FIXTURES / "app_contoso.json"
    (tmp_path / "inventory.json").write_text(fixture.read_text())
    (tmp_path / "unresolved.json").write_text("[]")


def test_artifact_choices_cover_all_supported_modes():
    assert ARTIFACT_CHOICES == ("graph", "related-candidates", "related-promoted", "rbac", "policy")


def test_classify_edge_kind_maps_network_and_reference_edges():
    assert classify_edge_kind("vm->nic") == "network"
    assert classify_edge_kind("appInsights->workspace") == "reference"
    assert classify_edge_kind("rbac-principal") == "reference"


def test_build_html_view_model_creates_subscription_rg_and_resource_hierarchy(tmp_path):
    _seed_output_files(tmp_path)
    cfg = _make_config(tmp_path)
    graph = build_graph(cfg)

    view = build_html_view_model(graph)

    subscriptions = [node for node in view["nodes"] if node["kind"] == "subscription"]
    resource_groups = [node for node in view["nodes"] if node["kind"] == "resourceGroup"]
    resources = [node for node in view["nodes"] if node["kind"] == "resource"]

    assert subscriptions
    assert resource_groups
    assert resources
    assert any(edge["source"].startswith("subscription::") and edge["target"].startswith("group::") for edge in view["hierarchyEdges"])
    assert any(edge["source"].startswith("group::") and edge["target"].startswith("/subscriptions/") for edge in view["hierarchyEdges"])


def test_generate_html_graph_mode_writes_mindmap(tmp_path):
    _seed_output_files(tmp_path)
    cfg = _make_config(tmp_path)
    build_graph(cfg)

    output = generate_html(cfg)

    assert output == tmp_path / "mindmap.html"
    content = output.read_text()
    assert "toggle-network" in content
    assert "toggle-reference" in content
    assert "Reset layout" in content
    assert "#2468d8" in content
    assert "#7a3cff" in content


def test_generate_html_related_candidate_modes(tmp_path):
    cfg = _make_config(tmp_path)
    cfg.ensure_deep_output_dir()
    candidates = [
        {
            "id": "/subscriptions/sub2/resourceGroups/rg-monitor/providers/Microsoft.Logic/workflows/bpc-sap-sync",
            "name": "bpc-sap-sync",
            "type": "Microsoft.Logic/workflows",
            "resourceGroup": "rg-monitor",
            "subscriptionId": "sub2",
            "matchedSearchStrings": ["SAP", "bpc"],
            "discoveryEvidence": [
                {
                    "explanation": "Potential in-scope context found in the base inventory.",
                    "relatedResources": [
                        {
                            "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/sap-core-app",
                            "name": "sap-core-app",
                            "type": "Microsoft.Web/sites",
                            "resourceGroup": "rg-app",
                            "subscriptionId": "sub1",
                            "matchedTerms": "SAP",
                        }
                    ],
                }
            ],
        }
    ]
    cfg.deep_out(cfg.deepDiscovery.candidateFile).write_text(json.dumps(candidates))
    cfg.deep_out(cfg.deepDiscovery.promotedFile).write_text(json.dumps(candidates))

    candidate_html = generate_html(cfg, artifact="related-candidates")
    promoted_html = generate_html(cfg, artifact="related-promoted")

    assert candidate_html == tmp_path / "related_candidates.html"
    assert promoted_html == tmp_path / "related_promoted.html"
    assert "sap-core-app" in candidate_html.read_text()
    assert "related-context" in candidate_html.read_text()
    assert "bpc-sap-sync" in promoted_html.read_text()


def test_generate_html_rbac_mode(tmp_path):
    cfg = _make_config(tmp_path)
    rows = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Authorization/roleAssignments/ra1",
            "properties": {
                "scope": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/site1",
                "roleDefinitionId": "/subscriptions/sub1/providers/Microsoft.Authorization/roleDefinitions/reader",
                "roleDefinitionName": "Reader",
                "principalId": "11111111-1111-1111-1111-111111111111",
                "principalDisplayName": "payments-api",
                "principalType": "ServicePrincipal",
                "principalResolutionStatus": "resolved",
            },
        }
    ]
    (tmp_path / "rbac.json").write_text(json.dumps(rows))

    output = generate_html(cfg, artifact="rbac")

    content = output.read_text()
    assert output == tmp_path / "rbac.html"
    assert "payments-api" in content
    assert "Reader" in content
    assert "Principals" in content


def test_generate_html_policy_mode(tmp_path):
    cfg = _make_config(tmp_path)
    rows = [
        {
            "id": "/providers/Microsoft.PolicyInsights/policyStates/latest/policyAssignments/deny-public",
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "resourceType": "microsoft.web/sites",
            "resourceGroup": "rg-app",
            "subscriptionId": "sub1",
            "resourceLocation": "eastus",
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
            "policyDefinitionName": "App Service should disable public network access",
            "policyAssignmentScope": "/subscriptions/sub1/resourceGroups/rg-app",
            "timestamp": "2026-03-24T10:00:00Z",
        }
    ]
    (tmp_path / "policy.json").write_text(json.dumps(rows))

    output = generate_html(cfg, artifact="policy")

    content = output.read_text()
    assert output == tmp_path / "policy.html"
    assert "deny-public" in content
    assert "App Service should disable public network access" in content
    assert "#f6b0aa" in content
