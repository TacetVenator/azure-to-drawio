"""Tests for application-aware splitting, Azure Policy collection, and JSON parse hardening."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools.azdisc.arg import _run_az
from tools.azdisc.config import Config, load_config
from tools.azdisc.discover import run_policy
from tools.azdisc.graph import build_graph
from tools.azdisc.split import build_split_preview, run_split


def _write_split_inventory(tmp_path):
    sap_subnet = "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet-app/subnets/sap"
    crm_subnet = "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/virtualNetworks/vnet-app/subnets/crm"
    shared_plan = "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Web/serverfarms/asp-shared"
    inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Web/sites/sap-web",
            "name": "sap-web",
            "type": "Microsoft.Web/sites",
            "location": "eastus",
            "subscriptionId": "sub1",
            "resourceGroup": "rg-shared",
            "tags": {"Application": "SAP"},
            "properties": {
                "serverFarmId": shared_plan,
                "virtualNetworkSubnetId": sap_subnet,
            },
        },
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Web/sites/crm-web",
            "name": "crm-web",
            "type": "Microsoft.Web/sites",
            "location": "eastus",
            "subscriptionId": "sub1",
            "resourceGroup": "rg-shared",
            "tags": {"Application": "CRM"},
            "properties": {
                "serverFarmId": shared_plan,
                "virtualNetworkSubnetId": crm_subnet,
            },
        },
        {
            "id": shared_plan,
            "name": "asp-shared",
            "type": "Microsoft.Web/serverfarms",
            "location": "eastus",
            "subscriptionId": "sub1",
            "resourceGroup": "rg-shared",
            "tags": {},
            "properties": {},
        },
    ]
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    (tmp_path / "unresolved.json").write_text(json.dumps([sap_subnet, crm_subnet]))
    return inventory


def test_split_preview_reports_candidate_values(tmp_path):
    _write_split_inventory(tmp_path)
    cfg = Config(
        app="corp-apps",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-shared"],
        outputDir=str(tmp_path),
    )

    preview = build_split_preview(cfg)

    assert "Application Split Preview" in preview
    assert "`application`" in preview.lower()
    assert "`SAP`" in preview
    assert "`CRM`" in preview
    assert "Untagged for configured keys: 1" in preview


def test_split_preview_defaults_to_common_tag_keys(tmp_path):
    inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.Web/sites/workload-web",
            "name": "workload-web",
            "type": "Microsoft.Web/sites",
            "location": "eastus",
            "subscriptionId": "sub1",
            "resourceGroup": "rg-shared",
            "tags": {"Workload": "Payroll"},
            "properties": {},
        }
    ]
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))

    cfg = Config(
        app="corp-apps",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-shared"],
        outputDir=str(tmp_path),
    )

    preview = build_split_preview(cfg)

    assert "`Payroll`" in preview
    assert "`workload`" in preview.lower()


def test_run_policy_collects_policy_states_for_inventory_resources(monkeypatch, tmp_path):
    inventory = _write_split_inventory(tmp_path)
    cfg = Config(
        app="corp-apps",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-shared"],
        outputDir=str(tmp_path),
        includePolicy=True,
    )

    seen = {}

    def fake_query(kusto, subscriptions):
        seen["kusto"] = kusto
        seen["subscriptions"] = subscriptions
        return [
            {
                "id": "policy-state-1-old",
                "name": "default",
                "type": "Microsoft.PolicyInsights/policyStates",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-shared",
                "properties": {
                    "resourceId": inventory[0]["id"],
                    "resourceType": inventory[0]["type"],
                    "resourceLocation": inventory[0]["location"],
                    "complianceState": "Compliant",
                    "policyAssignmentId": "/subscriptions/sub1/providers/Microsoft.Authorization/policyAssignments/allowed-locations",
                    "policyAssignmentName": "allowed-locations",
                    "policyAssignmentScope": "/subscriptions/sub1",
                    "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/allowed-locations",
                    "policyDefinitionName": "Allowed locations",
                    "policyDefinitionReferenceId": "allowedLocations",
                    "policySetDefinitionId": None,
                    "policySetDefinitionName": None,
                    "timestamp": "2026-03-22T10:00:00Z",
                },
            },
            {
                "id": "policy-state-1-new",
                "name": "default",
                "type": "Microsoft.PolicyInsights/policyStates",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-shared",
                "properties": {
                    "resourceId": inventory[0]["id"],
                    "resourceType": inventory[0]["type"],
                    "resourceLocation": inventory[0]["location"],
                    "complianceState": "NonCompliant",
                    "policyAssignmentId": "/subscriptions/sub1/providers/Microsoft.Authorization/policyAssignments/allowed-locations",
                    "policyAssignmentName": "allowed-locations",
                    "policyAssignmentScope": "/subscriptions/sub1",
                    "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/allowed-locations",
                    "policyDefinitionName": "Allowed locations",
                    "policyDefinitionReferenceId": "allowedLocations",
                    "policySetDefinitionId": None,
                    "policySetDefinitionName": None,
                    "timestamp": "2026-03-23T10:00:00Z",
                },
            },
            {
                "id": "policy-state-2",
                "name": "default",
                "type": "Microsoft.PolicyInsights/policyStates",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-other",
                "properties": {
                    "resourceId": "/subscriptions/sub1/resourceGroups/rg-other/providers/Microsoft.Web/sites/out-of-scope",
                    "resourceType": "Microsoft.Web/sites",
                    "resourceLocation": "eastus",
                    "complianceState": "Compliant",
                    "policyAssignmentId": "/subscriptions/sub1/providers/Microsoft.Authorization/policyAssignments/out-of-scope",
                    "policyAssignmentName": "out-of-scope",
                    "policyAssignmentScope": "/subscriptions/sub1",
                    "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/example",
                    "policyDefinitionName": "Example",
                    "policyDefinitionReferenceId": "example",
                    "policySetDefinitionId": None,
                    "policySetDefinitionName": None,
                    "timestamp": "2026-03-23T10:00:00Z",
                },
            },
        ]

    monkeypatch.setattr("tools.azdisc.discover.query", fake_query)

    run_policy(cfg)

    rows = json.loads((tmp_path / "policy.json").read_text())
    assert seen["subscriptions"] == ["sub1"]
    assert "policyresources" in seen["kusto"]
    assert "microsoft.policyinsights/policystates" in seen["kusto"].lower()
    assert len(rows) == 1
    assert rows[0]["resourceId"] == inventory[0]["id"]
    assert rows[0]["complianceState"] == "NonCompliant"
    assert rows[0]["policyAssignmentName"] == "allowed-locations"


def test_run_split_generates_per_application_outputs_with_shared_context(tmp_path):
    inventory = _write_split_inventory(tmp_path)
    policy_rows = [
        {
            "resourceId": inventory[0]["id"],
            "complianceState": "NonCompliant",
            "policyAssignmentName": "sap-guardrail",
            "properties": {"resourceId": inventory[0]["id"]},
        },
        {
            "resourceId": inventory[1]["id"],
            "complianceState": "Compliant",
            "policyAssignmentName": "crm-guardrail",
            "properties": {"resourceId": inventory[1]["id"]},
        },
        {
            "resourceId": inventory[2]["id"],
            "complianceState": "Compliant",
            "policyAssignmentName": "shared-plan-guardrail",
            "properties": {"resourceId": inventory[2]["id"]},
        },
    ]
    (tmp_path / "policy.json").write_text(json.dumps(policy_rows))

    cfg = Config(
        app="corp-apps",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-shared"],
        outputDir=str(tmp_path),
    )
    cfg.applicationSplit.enabled = True
    cfg.applicationSplit.tagKeys = ["Application"]
    cfg.applicationSplit.values = ["SAP", "CRM"]
    cfg.applicationSplit.includeSharedDependencies = True

    build_graph(cfg)
    summaries = run_split(cfg)

    assert {summary["application"] for summary in summaries} == {"SAP", "CRM"}
    sap_inventory = json.loads((tmp_path / "applications" / "sap" / "inventory.json").read_text())
    sap_names = {resource["name"] for resource in sap_inventory}
    assert "sap-web" in sap_names
    assert "asp-shared" in sap_names
    assert "crm-web" not in sap_names

    sap_manifest = json.loads((tmp_path / "applications" / "sap" / "slice.json").read_text())
    assert sap_manifest["directCount"] == 1
    assert sap_manifest["sharedCount"] == 1
    assert sap_manifest["externalCount"] == 1

    sap_policy = json.loads((tmp_path / "applications" / "sap" / "policy.json").read_text())
    assert {row["policyAssignmentName"] for row in sap_policy} == {"sap-guardrail", "shared-plan-guardrail"}

    assert (tmp_path / "applications" / "sap" / "catalog.md").exists()
    assert (tmp_path / "applications" / "sap" / "master_report.md").exists()
    applications_report = (tmp_path / "applications.md").read_text()
    assert "`SAP`" in applications_report
    assert "`applications/sap`" in applications_report


def test_load_config_reports_invalid_json_with_position(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{\n  "app": "broken",\n  "subscriptions": [}\n')

    with pytest.raises(RuntimeError, match="Config file") as excinfo:
        load_config(str(cfg_file))

    message = str(excinfo.value)
    assert str(cfg_file) in message
    assert "line 3 column 21" in message


def test_build_graph_reports_invalid_inventory_json_with_stage_context(tmp_path):
    (tmp_path / "inventory.json").write_text('[{"id": "x"')
    (tmp_path / "unresolved.json").write_text('[]')
    cfg = Config(
        app="broken-graph",
        subscriptions=["sub1"],
        seedResourceGroups=["rg1"],
        outputDir=str(tmp_path),
    )

    with pytest.raises(RuntimeError, match="Graph stage inventory") as excinfo:
        build_graph(cfg)

    assert "inventory.json" in str(excinfo.value)


def test_run_az_reports_non_json_stdout(monkeypatch):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout='warning: not json', stderr='')

    monkeypatch.setattr('tools.azdisc.arg.subprocess.run', fake_run)

    with pytest.raises(RuntimeError, match="Azure CLI JSON output") as excinfo:
        _run_az(["graph", "query"])

    message = str(excinfo.value)
    assert "line 1 column 1" in message
    assert "az graph query" in message
