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
