"""Tests for policy CSV and YAML exports."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.inventory import generate_policy_csv, generate_policy_yaml


def _make_config(tmp_path: Path) -> Config:
    return Config(
        app="governance-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )


def _write_policy_rows(tmp_path: Path) -> None:
    rows = [
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "resourceType": "microsoft.web/sites",
            "resourceGroup": "rg-app",
            "subscriptionId": "sub1",
            "resourceLocation": "eastus",
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
            "policyDefinitionName": "App Service should disable public network access",
            "policyDefinitionReferenceId": "web-public",
            "policyAssignmentId": "/providers/Microsoft.Management/managementGroups/mg/providers/Microsoft.Authorization/policyAssignments/deny-public",
            "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/def-web-public",
            "policySetDefinitionName": "web-baseline",
            "policySetDefinitionId": "/providers/Microsoft.Authorization/policySetDefinitions/web-baseline",
            "policyAssignmentScope": "/subscriptions/sub1/resourceGroups/rg-app",
            "timestamp": "2026-03-24T10:00:00Z",
        },
        {
            "resourceId": "/subscriptions/sub1/resourceGroups/rg-data/providers/Microsoft.Sql/servers/sql1",
            "resourceType": "microsoft.sql/servers",
            "resourceGroup": "rg-data",
            "subscriptionId": "sub1",
            "resourceLocation": "eastus",
            "complianceState": "Compliant",
            "policyAssignmentName": "sql-baseline",
            "policyDefinitionName": "SQL should use TDE",
            "policyAssignmentId": "/providers/Microsoft.Management/managementGroups/mg/providers/Microsoft.Authorization/policyAssignments/sql-baseline",
            "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/def-sql-tde",
            "policyAssignmentScope": "/subscriptions/sub1/resourceGroups/rg-data",
            "timestamp": "2026-03-24T10:05:00Z",
        },
    ]
    (tmp_path / "policy.json").write_text(json.dumps(rows))


def test_generate_policy_csv_writes_flat_rows(tmp_path):
    _write_policy_rows(tmp_path)
    cfg = _make_config(tmp_path)

    out_path = generate_policy_csv(cfg)

    assert out_path == tmp_path / "policy.csv"
    with out_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["ResourceName"] == "app1"
    assert rows[0]["ComplianceState"] == "NonCompliant"
    assert rows[0]["PolicyAssignmentName"] == "deny-public"
    assert rows[1]["ResourceName"] == "sql1"
    assert rows[1]["ComplianceState"] == "Compliant"


def test_generate_policy_yaml_writes_grouped_views(tmp_path):
    _write_policy_rows(tmp_path)
    cfg = _make_config(tmp_path)

    out_path = generate_policy_yaml(cfg)

    assert out_path == tmp_path / "policy.yaml"
    content = out_path.read_text()
    assert "# Azure Policy Compliance Export" in content
    assert "byResource:" in content
    assert "byPolicy:" in content
    assert 'app1 (/subscriptions/sub1/resourcegroups/rg-app/providers/microsoft.web/sites/app1):' in content
    assert 'sql1 (/subscriptions/sub1/resourcegroups/rg-data/providers/microsoft.sql/servers/sql1):' in content
    assert 'deny-public -> App Service should disable public network access:' in content
    assert 'sql-baseline -> SQL should use TDE:' in content
    assert 'complianceState: NonCompliant' in content
    assert 'complianceState: Compliant' in content
