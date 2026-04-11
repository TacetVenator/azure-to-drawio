"""Tests for software inventory export and CLI flags."""

import csv
import json

from tools.azdisc.__main__ import build_parser
from tools.azdisc.config import Config
from tools.azdisc.inventory import generate_software_inventory_csv


def test_build_parser_accepts_software_inventory_flags_for_expand():
    parser = build_parser()
    args = parser.parse_args([
        "expand",
        "app/myapp/config.json",
        "--software-inventory-csv",
        "workspace-123",
        "--software-inventory-days",
        "14",
    ])
    assert args.software_inventory_csv == "workspace-123"
    assert args.software_inventory_days == 14


def test_build_parser_accepts_software_inventory_flags_for_run():
    parser = build_parser()
    args = parser.parse_args([
        "run",
        "app/myapp/config.json",
        "--software-inventory-csv",
        "workspace-456",
    ])
    assert args.software_inventory_csv == "workspace-456"
    assert args.software_inventory_days == 30


def test_generate_software_inventory_csv_matches_by_resource_id(tmp_path, monkeypatch):
    cfg = Config(
        app="test",
        subscriptions=["sub1"],
        seedResourceGroups=["rg1"],
        outputDir=str(tmp_path),
    )
    inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "name": "vm1",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "eastus",
            "subscriptionId": "sub1",
            "resourceGroup": "rg1",
        }
    ]

    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps({
            "tables": [
                {
                    "columns": [
                        {"name": "AzureResourceId"},
                        {"name": "Computer"},
                        {"name": "SoftwareName"},
                        {"name": "CurrentVersion"},
                        {"name": "Publisher"},
                        {"name": "TimeGenerated"},
                    ],
                    "rows": [[
                        "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
                        "vm1.contoso.local",
                        "nginx",
                        "1.24.0",
                        "NGINX",
                        "2026-04-08T00:00:00Z",
                    ]],
                }
            ]
        })

    monkeypatch.setattr("tools.azdisc.azcli.subprocess.run", lambda *args, **kwargs: Result())

    out_path = generate_software_inventory_csv(cfg, "workspace-123", inventory=inventory)

    with out_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["VmName"] == "vm1"
    assert rows[0]["SoftwareName"] == "nginx"
    assert rows[0]["CurrentVersion"] == "1.24.0"


def test_generate_software_inventory_csv_matches_by_computer_name(tmp_path, monkeypatch):
    cfg = Config(
        app="test",
        subscriptions=["sub1"],
        seedResourceGroups=["rg1"],
        outputDir=str(tmp_path),
    )
    inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm-app-01",
            "name": "vm-app-01",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "eastus",
            "subscriptionId": "sub1",
            "resourceGroup": "rg1",
        }
    ]

    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps({
            "tables": [
                {
                    "columns": [
                        {"name": "Computer"},
                        {"name": "SoftwareName"},
                        {"name": "CurrentVersion"},
                        {"name": "Publisher"},
                        {"name": "TimeGenerated"},
                    ],
                    "rows": [[
                        "vm-app-01.contoso.local",
                        "python3",
                        "3.11.9",
                        "Python Software Foundation",
                        "2026-04-08T00:00:00Z",
                    ]],
                }
            ]
        })

    monkeypatch.setattr("tools.azdisc.azcli.subprocess.run", lambda *args, **kwargs: Result())

    out_path = generate_software_inventory_csv(cfg, "workspace-123", inventory=inventory)

    with out_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["VmName"] == "vm-app-01"
    assert rows[0]["Computer"] == "vm-app-01.contoso.local"


def test_generate_software_inventory_csv_writes_header_when_no_vms(tmp_path, monkeypatch):
    cfg = Config(
        app="test",
        subscriptions=["sub1"],
        seedResourceGroups=["rg1"],
        outputDir=str(tmp_path),
    )

    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        raise AssertionError("Azure CLI should not be called when there are no VMs")

    monkeypatch.setattr("tools.azdisc.azcli.subprocess.run", fake_run)

    out_path = generate_software_inventory_csv(cfg, "workspace-123", inventory=[])

    with out_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [[
        "VmName", "VmResourceId", "SubscriptionId", "ResourceGroup", "Location",
        "Computer", "SoftwareName", "CurrentVersion", "Publisher", "TimeGenerated",
    ]]
    assert called["value"] is False
