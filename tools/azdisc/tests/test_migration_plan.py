"""Tests for migration-plan generation."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.master_report import generate_master_report
from tools.azdisc.migration_plan import generate_migration_plan


def _write_pack_inputs(base_dir: Path) -> None:
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "name": "app1",
                "type": "microsoft.web/sites",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
                "properties": {"defaultHostName": "app1.azurewebsites.net"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/privateEndpoints/pe-sql",
                "name": "pe-sql",
                "type": "microsoft.network/privateendpoints",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-net",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "name": "kv-shared",
                "type": "microsoft.keyvault/vaults",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-shared",
            },
        ],
        "edges": [
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "target": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "kind": "app->kv",
            }
        ],
        "telemetryEdges": [
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "target": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "kind": "telemetry",
            }
        ],
    }
    inventory = [
        {"type": "microsoft.web/sites", "name": "app1"},
        {"type": "microsoft.network/privateendpoints", "name": "pe-sql"},
        {"type": "microsoft.keyvault/vaults", "name": "kv-shared"},
    ]
    unresolved = ["/subscriptions/sub1/resourceGroups/rg-ext/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"]
    policy = [
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
        }
    ]
    rbac = [
        {
            "id": "assignment-1",
            "scope": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
        }
    ]
    (base_dir / "graph.json").write_text(json.dumps(graph))
    (base_dir / "inventory.json").write_text(json.dumps(inventory))
    (base_dir / "unresolved.json").write_text(json.dumps(unresolved))
    (base_dir / "policy.json").write_text(json.dumps(policy))
    (base_dir / "rbac.json").write_text(json.dumps(rbac))


def test_generate_migration_plan_writes_root_pack(tmp_path):
    _write_pack_inputs(tmp_path)
    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.migrationPlan.enabled = True
    cfg.migrationPlan.includeCopilotPrompts = True

    generate_migration_plan(cfg)

    pack_dir = tmp_path / "migration-plan"
    assert (pack_dir / "migration-plan.md").exists()
    assert (pack_dir / "migration-questionnaire.md").exists()
    assert (pack_dir / "migration-decisions.md").exists()
    assert (pack_dir / "decision-trees.md").exists()
    assert (pack_dir / "wave-plan.md").exists()
    assert (pack_dir / "stakeholder-pack.md").exists()
    assert (pack_dir / "technical-gaps.md").exists()
    assert (pack_dir / "copilot-prompts.md").exists()

    content = (pack_dir / "migration-plan.md").read_text()
    assert "# Migration Plan" in content
    assert "## Step-by-Step Migration Plan" in content
    assert "Policy records captured: 1" in content

    summary = json.loads((pack_dir / "migration-plan.json").read_text())
    assert summary["resources"] == 3
    assert summary["privateEndpointCount"] == 1
    assert summary["telemetryEdges"] == 1


def test_generate_migration_plan_writes_split_packs(tmp_path):
    _write_pack_inputs(tmp_path)
    app_dir = tmp_path / "applications" / "sap"
    app_dir.mkdir(parents=True)
    _write_pack_inputs(app_dir)
    (app_dir / "slice.json").write_text(
        json.dumps(
            {
                "application": "SAP",
                "appBoundary": {
                    "confidence": 0.62,
                    "ambiguityLevel": "medium",
                    "ambiguousResourceGroupCount": 1,
                    "ambiguousResourceCount": 2,
                    "ambiguousResourceGroups": [
                        {
                            "subscriptionId": "sub1",
                            "resourceGroup": "rg-shared",
                            "apps": ["SAP", "CRM"],
                            "appCount": 2,
                        }
                    ],
                },
            }
        )
    )

    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.migrationPlan.enabled = True
    cfg.migrationPlan.applicationScope = "split"
    cfg.migrationPlan.includeCopilotPrompts = False

    generate_migration_plan(cfg)

    pack_dir = tmp_path / "migration-plan" / "applications" / "sap"
    assert (pack_dir / "migration-plan.md").exists()
    assert (pack_dir / "stakeholder-pack.md").exists()
    assert not (pack_dir / "copilot-prompts.md").exists()
    content = (pack_dir / "migration-plan.md").read_text()
    assert "## Application Boundary Confidence" in content
    assert "Boundary confidence: 0.62" in content

    summary = json.loads((pack_dir / "migration-plan.json").read_text())
    assert summary["appBoundaryAnalysis"]["available"] is True
    assert summary["appBoundaryAnalysis"]["ambiguityLevel"] == "medium"


def test_master_report_links_migration_plan_when_present(tmp_path):
    _write_pack_inputs(tmp_path)
    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )

    generate_migration_plan(cfg)
    generate_master_report(cfg)

    content = (tmp_path / "master_report.md").read_text()
    assert "## Migration Planning Pack" in content
    assert "migration-plan/migration-plan.md" in content
    assert "migration-plan/stakeholder-pack.md" in content

def test_migration_plan_pack_contains_richer_questionnaire_and_decision_content(tmp_path):
    _write_pack_inputs(tmp_path)
    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.migrationPlan.enabled = True

    generate_migration_plan(cfg)

    questionnaire = (tmp_path / "migration-plan" / "migration-questionnaire.md").read_text()
    assert "## Business Sponsor / Application Owner" in questionnaire
    assert "## Identity And Access" in questionnaire
    assert "## Cutover And Rollback" in questionnaire
    assert "What are the RTO and RPO expectations" in questionnaire
    assert "Which RBAC assignments are required for runtime, deployment, operations, and break-glass support" in questionnaire

    decisions = (tmp_path / "migration-plan" / "migration-decisions.md").read_text()
    assert "Migration pattern selected (rehost / replatform / refactor)" in decisions
    assert "Data migration and synchronization method confirmed" in decisions
    assert "Compliance remediation / exception path approved" in decisions

    trees = (tmp_path / "migration-plan" / "decision-trees.md").read_text()
    assert "## Decision Tree 1: Choose The Migration Pattern" in trees
    assert "## Decision Tree 3: Identity And Access" in trees
    assert "## Decision Tree 5: Cutover And Rollback" in trees
    assert "Discovery hint: Yes." in trees

    wave_plan = (tmp_path / "migration-plan" / "wave-plan.md").read_text()
    assert "## Exit Criteria Per Wave" in wave_plan
    assert "Rollback steps remain viable until the agreed point of no return" in wave_plan



def test_migration_plan_adapts_sections_to_discovered_signals(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Web/sites/app1",
                "name": "app1",
                "type": "microsoft.web/sites",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app1",
                "properties": {"defaultHostName": "app1.azurewebsites.net"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app2/providers/Microsoft.Compute/virtualMachines/vm2",
                "name": "vm2",
                "type": "microsoft.compute/virtualmachines",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app2",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/privateEndpoints/pe-sql",
                "name": "pe-sql",
                "type": "microsoft.network/privateendpoints",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-net",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "name": "kv-shared",
                "type": "microsoft.keyvault/vaults",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-shared",
            },
        ],
        "edges": [
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Web/sites/app1",
                "target": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "kind": "app->kv",
            },
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app2/providers/Microsoft.Compute/virtualMachines/vm2",
                "target": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "kind": "vm->kv",
            },
        ],
    }
    inventory = [
        {"type": "microsoft.web/sites", "name": "app1"},
        {"type": "microsoft.compute/virtualmachines", "name": "vm2"},
        {"type": "microsoft.network/privateendpoints", "name": "pe-sql"},
        {"type": "microsoft.keyvault/vaults", "name": "kv-shared"},
    ]
    policy = [
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Web/sites/app1",
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
        }
    ]
    unresolved = ["/subscriptions/sub1/resourceGroups/rg-dns/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"]

    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    (tmp_path / "unresolved.json").write_text(json.dumps(unresolved))
    (tmp_path / "rbac.json").write_text(json.dumps([]))

    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app1"],
        outputDir=str(tmp_path),
    )
    cfg.migrationPlan.enabled = True

    generate_migration_plan(cfg)

    questionnaire = (tmp_path / "migration-plan" / "migration-questionnaire.md").read_text()
    assert "## Private Connectivity And DNS" in questionnaire
    assert "## Public Exposure Review" in questionnaire
    assert "## Compliance Remediation Interview" in questionnaire
    assert "## Shared Services And Coordination" in questionnaire
    assert "## Evidence Follow-Up" in questionnaire
    assert "Private endpoints detected: 1" in questionnaire
    assert "Non-compliant policy records detected: 1" in questionnaire

    trees = (tmp_path / "migration-plan" / "decision-trees.md").read_text()
    assert "## Priority Tree: Private Connectivity And DNS" in trees
    assert "## Priority Tree: Public Exposure Review" in trees
    assert "## Priority Tree: Compliance Remediation" in trees
    assert "## Priority Tree: Shared Services And Coordination" in trees
    assert "## Priority Tree: Unresolved Dependency Review" in trees

    summary = json.loads((tmp_path / "migration-plan" / "migration-plan.json").read_text())
    assert summary["hasPublicExposure"] is True
    assert summary["hasPrivateEndpoints"] is True
    assert summary["hasPolicyEvidence"] is True
    assert summary["hasNonCompliantPolicies"] is True
    assert summary["hasSharedDependencies"] is True
    assert summary["hasUnresolvedReferences"] is True


def test_migration_plan_omits_adaptive_sections_when_signals_absent(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm1",
                "name": "vm1",
                "type": "microsoft.compute/virtualmachines",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
            }
        ],
        "edges": [],
    }
    inventory = [{"type": "microsoft.compute/virtualmachines", "name": "vm1"}]

    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    (tmp_path / "unresolved.json").write_text(json.dumps([]))
    (tmp_path / "policy.json").write_text(json.dumps([]))
    (tmp_path / "rbac.json").write_text(json.dumps([]))

    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.migrationPlan.enabled = True

    generate_migration_plan(cfg)

    questionnaire = (tmp_path / "migration-plan" / "migration-questionnaire.md").read_text()
    assert "## Private Connectivity And DNS" not in questionnaire
    assert "## Public Exposure Review" not in questionnaire
    assert "## Compliance Remediation Interview" not in questionnaire
    assert "## Shared Services And Coordination" not in questionnaire
    assert "Private endpoints detected: 0" in questionnaire
    assert "Non-compliant policy records detected: 0" in questionnaire

    trees = (tmp_path / "migration-plan" / "decision-trees.md").read_text()
    assert "## Priority Tree: Private Connectivity And DNS" not in trees
    assert "## Priority Tree: Public Exposure Review" not in trees
    assert "## Priority Tree: Compliance Remediation" not in trees
    assert "## Priority Tree: Shared Services And Coordination" not in trees
    assert "## Priority Tree: Unresolved Dependency Review" not in trees
    assert "Discovery hint: No." in trees


def test_master_report_includes_governance_snapshots(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "name": "app1",
                "type": "microsoft.web/sites",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
            }
        ],
        "edges": [],
    }
    policy = [
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
        },
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "complianceState": "Compliant",
            "policyAssignmentName": "allowed-locations",
        },
    ]
    rbac = [
        {
            "properties": {
                "scope": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "roleDefinitionName": "Contributor",
                "principalName": "App Ops",
                "principalType": "Group",
            }
        },
        {
            "properties": {
                "scope": "/subscriptions/sub1/resourceGroups/rg-app",
                "roleDefinitionName": "Reader",
                "principalName": "Audit Team",
                "principalType": "Group",
            }
        },
    ]

    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    (tmp_path / "rbac.json").write_text(json.dumps(rbac))

    cfg = Config(
        app="contoso",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )

    generate_master_report(cfg)

    content = (tmp_path / "master_report.md").read_text()
    assert "- [rbac_summary.md](rbac_summary.md): Human-readable access review summary." in content
    assert "- [policy_summary.md](policy_summary.md): Executive-friendly compliance summary." in content
    assert "### Policy Snapshot" in content
    assert "- Policy state records: 2" in content
    assert "- Compliant: 1" in content
    assert "- Non-compliant: 1" in content
    assert "### RBAC Snapshot" in content
    assert "- Role assignments captured: 2" in content
    assert "- Unique principals: 2" in content
    assert "| app1 (microsoft.web/sites) | rg-app | 2 | 2 | 1 |" in content
