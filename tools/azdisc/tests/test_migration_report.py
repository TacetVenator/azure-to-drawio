"""Tests for migration.md generation."""
from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.docs import generate_docs
from tools.azdisc.graph import build_graph

FIXTURES = Path(__file__).parent / "fixtures"


def _seed_output_files(tmp_path: Path) -> None:
    fixture = FIXTURES / "app_contoso.json"
    (tmp_path / "inventory.json").write_text(fixture.read_text())
    (tmp_path / "unresolved.json").write_text(json.dumps([
        "/subscriptions/sub1/resourcegroups/rg-shared/providers/microsoft.network/virtualnetworks/vnet-shared"
    ]))


def _make_config(tmp_path: Path) -> Config:
    return Config(
        app="contoso-app",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        includeRbac=False,
    )


def test_generate_docs_writes_migration_md(tmp_path):
    _seed_output_files(tmp_path)
    cfg = _make_config(tmp_path)
    build_graph(cfg)
    generate_docs(cfg)

    assert (tmp_path / "migration.md").exists()


def test_migration_md_includes_public_exposure_and_gaps(tmp_path):
    _seed_output_files(tmp_path)
    cfg = _make_config(tmp_path)
    build_graph(cfg)
    generate_docs(cfg)

    content = (tmp_path / "migration.md").read_text()
    assert "# Migration Assessment — contoso-app" in content
    assert "pip-web-01" in content
    assert "20.85.100.50" in content
    assert "pe-sql" in content
    assert "sql-contoso (microsoft.sql/servers)" in content
    assert "sqlServer" in content
    assert "Unresolved references: 1" in content
    assert "## Evidence And Confidence" in content
    assert "Configuration-derived" in content
    assert "Telemetry-derived" in content
    assert "Edges touching external placeholders" in content
    assert (
        "Edge kinds touching unresolved/external resources" in content
        or "No graph relationships currently terminate at unresolved/external placeholder nodes." in content
    )
    assert "No Application Insights components were discovered in scope" in content
    assert "inspect app settings and deployment patterns for connection strings or instrumentation keys" in content
    assert "No Log Analytics workspace was discovered in scope" in content
    assert "review monitoring resource groups, shared platform subscriptions" in content
    assert "confirm whether diagnostics are enabled" in content
    assert "RBAC collection is disabled" in content
    assert "review subscription, resource-group, and critical-resource role assignments separately" in content


def test_migration_md_lists_seed_scope(tmp_path):
    _seed_output_files(tmp_path)
    cfg = Config(
        app="tag-app",
        subscriptions=["sub1"],
        seedResourceGroups=[],
        seedTags={"Application": "checkout"},
        seedTagKeys=["Workload"],
        outputDir=str(tmp_path),
    )
    build_graph(cfg)
    generate_docs(cfg)

    content = (tmp_path / "migration.md").read_text()
    assert "Seed tags: `Application=checkout`" in content
    assert "Seed tag keys: `Workload`" in content
    assert "## Application Boundary" in content
    assert "| boundary label | resources | resource groups | subscriptions | resource types |" in content


def test_migration_md_highlights_shared_platform_candidates(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Compute/virtualMachines/vm-a",
                "name": "vm-a",
                "type": "microsoft.compute/virtualmachines",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app1",
            },
            {
                "id": "/subscriptions/sub2/resourceGroups/rg-app2/providers/Microsoft.Compute/virtualMachines/vm-b",
                "name": "vm-b",
                "type": "microsoft.compute/virtualmachines",
                "subscriptionId": "sub2",
                "resourceGroup": "rg-app2",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-network/providers/Microsoft.Network/virtualNetworks/vnet-hub",
                "name": "vnet-hub",
                "type": "microsoft.network/virtualnetworks",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-network",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "name": "kv-shared",
                "type": "microsoft.keyvault/vaults",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-shared",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-monitor/providers/Microsoft.OperationalInsights/workspaces/law-shared",
                "name": "law-shared",
                "type": "microsoft.operationalinsights/workspaces",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-monitor",
            },
        ],
        "edges": [
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Compute/virtualMachines/vm-a",
                "target": "/subscriptions/sub1/resourceGroups/rg-network/providers/Microsoft.Network/virtualNetworks/vnet-hub",
                "kind": "vm->subnet",
            },
            {
                "source": "/subscriptions/sub2/resourceGroups/rg-app2/providers/Microsoft.Compute/virtualMachines/vm-b",
                "target": "/subscriptions/sub1/resourceGroups/rg-network/providers/Microsoft.Network/virtualNetworks/vnet-hub",
                "kind": "vm->subnet",
            },
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Compute/virtualMachines/vm-a",
                "target": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "kind": "vm->dependsOn",
            },
            {
                "source": "/subscriptions/sub2/resourceGroups/rg-app2/providers/Microsoft.Compute/virtualMachines/vm-b",
                "target": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "kind": "vm->dependsOn",
            },
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app1/providers/Microsoft.Compute/virtualMachines/vm-a",
                "target": "/subscriptions/sub1/resourceGroups/rg-monitor/providers/Microsoft.OperationalInsights/workspaces/law-shared",
                "kind": "vm->dependsOn",
            },
            {
                "source": "/subscriptions/sub2/resourceGroups/rg-app2/providers/Microsoft.Compute/virtualMachines/vm-b",
                "target": "/subscriptions/sub1/resourceGroups/rg-monitor/providers/Microsoft.OperationalInsights/workspaces/law-shared",
                "kind": "vm->dependsOn",
            },
        ],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "inventory.json").write_text(json.dumps([
        {"type": "microsoft.network/privatednszones"},
        {"type": "microsoft.insights/diagnosticsettings"},
    ]))
    (tmp_path / "unresolved.json").write_text(json.dumps([
        "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
    ]))

    cfg = Config(
        app="shared-platform-app",
        subscriptions=["sub1", "sub2"],
        seedResourceGroups=[],
        seedTags={"Application": "checkout"},
        outputDir=str(tmp_path),
    )
    generate_docs(cfg)

    content = (tmp_path / "migration.md").read_text()
    assert "### Shared Platform Service Candidates" in content
    assert "vnet-hub" in content
    assert "kv-shared" in content
    assert "law-shared" in content
    assert "Shared VNet or hub network candidate" in content
    assert "Shared Key Vault candidate" in content
    assert "Shared Log Analytics workspace candidate" in content
    assert "### Migration Blockers And Unknowns" in content
    assert "cross-subscription relationships were discovered" in content
    assert "unresolved references remain" in content


def test_migration_md_reports_telemetry_and_identity_gaps_with_next_checks(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app-web",
                "name": "app-web",
                "type": "microsoft.web/sites",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
                "identity": {"type": "SystemAssigned"},
                "properties": {"defaultHostName": "app-web.azurewebsites.net"},
            }
        ],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "inventory.json").write_text(json.dumps([]))

    cfg = Config(
        app="telemetry-gap-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
        enableTelemetry=True,
        telemetryLookbackDays=14,
    )
    generate_docs(cfg)

    content = (tmp_path / "migration.md").read_text()
    assert "Telemetry enrichment is enabled but no telemetry-derived relationships were observed in the last 14 day(s)." in content
    assert "verify log retention, workspace scope, and whether diagnostic pipelines are configured" in content
    assert "Identity-bearing resources were detected." in content
    assert "review managed identities, service principals, Key Vault access, and principal ownership in Entra ID" in content


def test_migration_md_uses_group_by_tag_for_app_boundary(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm-checkout",
                "name": "vm-checkout",
                "type": "microsoft.compute/virtualmachines",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
                "tags": {"Application": "checkout"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.KeyVault/vaults/kv-checkout",
                "name": "kv-checkout",
                "type": "microsoft.keyvault/vaults",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
                "tags": {"Application": "checkout"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Sql/servers/sql-shared",
                "name": "sql-shared",
                "type": "microsoft.sql/servers",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-data",
                "tags": {},
            },
        ],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "inventory.json").write_text(json.dumps([]))

    cfg = Config(
        app="grouped-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
        groupByTag=["Application"],
    )
    generate_docs(cfg)

    content = (tmp_path / "migration.md").read_text()
    assert "## Application Boundary" in content
    assert "| Application: checkout | 2 | 1 | 1 | 2 |" in content
    assert "| Untagged | 1 | 1 | 1 | 1 |" in content


def test_migration_md_expands_public_and_private_exposure_tables(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-edge/providers/Microsoft.Network/publicIPAddresses/pip-appgw",
                "name": "pip-appgw",
                "type": "microsoft.network/publicipaddresses",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-edge",
                "properties": {"ipAddress": "52.10.10.10"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-edge/providers/Microsoft.Network/applicationGateways/agw1",
                "name": "agw1",
                "type": "microsoft.network/applicationgateways",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-edge",
                "properties": {
                    "frontendIPConfigurations": [
                        {
                            "properties": {
                                "publicIPAddress": {
                                    "id": "/subscriptions/sub1/resourceGroups/rg-edge/providers/Microsoft.Network/publicIPAddresses/pip-appgw"
                                }
                            }
                        }
                    ]
                },
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-edge/providers/Microsoft.Cdn/profiles/fd1",
                "name": "fd1",
                "type": "microsoft.cdn/profiles",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-edge",
                "properties": {"hostName": "fd1.azurefd.net"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-dns/providers/Microsoft.Network/trafficManagerProfiles/tm1",
                "name": "tm1",
                "type": "microsoft.network/trafficmanagerprofiles",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-dns",
                "properties": {"dnsConfig": {"fqdn": "tm1.trafficmanager.net"}},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet-private",
                "name": "snet-private",
                "type": "microsoft.network/virtualnetworks/subnets",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-net",
                "properties": {},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/privateEndpoints/pe-storage",
                "name": "pe-storage",
                "type": "microsoft.network/privateendpoints",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
                "properties": {
                    "privateLinkServiceConnections": [
                        {"properties": {"groupIds": ["blob"]}}
                    ]
                },
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Storage/storageAccounts/sa1",
                "name": "sa1",
                "type": "microsoft.storage/storageaccounts",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-data",
                "properties": {},
            },
        ],
        "edges": [
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-edge/providers/Microsoft.Network/applicationGateways/agw1",
                "target": "api.internal.contoso.local",
                "kind": "appGw->backend",
            },
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/privateEndpoints/pe-storage",
                "target": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/snet-private",
                "kind": "privateEndpoint->subnet",
            },
            {
                "source": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Network/privateEndpoints/pe-storage",
                "target": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Storage/storageAccounts/sa1",
                "kind": "privateEndpoint->target",
            },
        ],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "inventory.json").write_text(json.dumps([
        {"type": "microsoft.network/privatednszones"},
    ]))

    cfg = Config(
        app="exposure-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    generate_docs(cfg)

    content = (tmp_path / "migration.md").read_text()
    assert "agw1" in content
    assert "52.10.10.10" in content
    assert "api.internal.contoso.local" in content
    assert "fd1.azurefd.net" in content
    assert "tm1.trafficmanager.net" in content
    assert "| pe-storage | snet-private | sa1 (microsoft.storage/storageaccounts) | blob |" in content



def test_generate_docs_writes_policy_and_rbac_governance_summaries(tmp_path):
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "name": "app1",
                "type": "microsoft.web/sites",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Sql/servers/sql1",
                "name": "sql1",
                "type": "microsoft.sql/servers",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-data",
            },
        ],
        "edges": [],
    }
    policy = [
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "resourceGroup": "rg-app",
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
            "policyDefinitionName": "App Service should disable public network access",
            "timestamp": "2026-03-24T10:00:00Z",
        },
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Sql/servers/sql1",
            "resourceGroup": "rg-data",
            "complianceState": "Compliant",
            "policyAssignmentName": "sql-baseline",
            "policyDefinitionName": "SQL should use TDE",
            "timestamp": "2026-03-24T10:05:00Z",
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
    (tmp_path / "inventory.json").write_text(json.dumps([]))
    (tmp_path / "policy.json").write_text(json.dumps(policy))
    (tmp_path / "rbac.json").write_text(json.dumps(rbac))

    cfg = Config(
        app="governance-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    generate_docs(cfg)

    policy_summary = (tmp_path / "policy_summary.md").read_text()
    assert "## Executive Summary" in policy_summary
    assert "- Policy state records: 2" in policy_summary
    assert "- Non-compliant: 1" in policy_summary
    assert "- Resources with at least one non-compliant policy: 1" in policy_summary
    assert "| app1 (microsoft.web/sites) | rg-app | 1 | deny-public |" in policy_summary
    assert "### app1 (microsoft.web/sites)" in policy_summary
    assert "deny-public: App Service should disable public network access (NonCompliant, 2026-03-24T10:00:00Z)" in policy_summary

    rbac_summary = (tmp_path / "rbac_summary.md").read_text()
    assert "## Executive Summary" in rbac_summary
    assert "- Role assignments captured: 2" in rbac_summary
    assert "- Unique principals: 2" in rbac_summary
    assert "- Resources with effective access captured: 1" in rbac_summary
    assert "| app1 (microsoft.web/sites) | rg-app | 2 | 2 | 2 | 1 |" in rbac_summary
    assert "### app1 (microsoft.web/sites)" in rbac_summary
    assert "- Contributor -> App Ops (Group; direct)" in rbac_summary
    assert "- Reader -> Audit Team (Group; inherited from /subscriptions/sub1/resourcegroups/rg-app)" in rbac_summary
