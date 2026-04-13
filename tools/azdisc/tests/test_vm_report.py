from __future__ import annotations

import json
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.graph import build_graph
from tools.azdisc.vm_report import generate_vm_report_packs

FIXTURES = Path(__file__).parent / "fixtures"


def test_generate_vm_report_pack_from_inventory_fixture(tmp_path):
    inventory = json.loads((FIXTURES / "inventory_small.json").read_text())
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))
    (tmp_path / "unresolved.json").write_text("[]")

    cfg = Config(
        app="vm-report-test",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app-dev"],
        outputDir=str(tmp_path),
    )

    build_graph(cfg)
    summaries = generate_vm_report_packs(cfg)

    assert len(summaries) == 1
    vm_dir = tmp_path / "vms" / "vm1"
    assert vm_dir.exists()
    assert (vm_dir / "inventory.json").exists()
    assert (vm_dir / "graph.json").exists()
    assert (vm_dir / "diagram.drawio").exists()
    assert (vm_dir / "vm_report.md").exists()
    assert (vm_dir / "vm_report.csv").exists()
    assert (vm_dir / "vm_details.csv").exists()
    assert (tmp_path / "vms" / "index.md").exists()

    report_text = (vm_dir / "vm_report.md").read_text()
    assert "SKU: `Standard_D4s_v3`" in report_text
    assert "NICs: nic1" in report_text
    assert "VNets: vnet1" in report_text
    assert "Extensions: AzureMonitorLinuxAgent; MDE.Linux" in report_text

    csv_text = (vm_dir / "vm_report.csv").read_text()
    assert "vm1" in csv_text
    assert "nic1" in csv_text
    assert "vnet1" in csv_text

    sliced_inventory = json.loads((vm_dir / "inventory.json").read_text())
    sliced_ids = {item["id"].lower() for item in sliced_inventory}
    assert "/subscriptions/sub1/resourcegroups/rg-app-dev/providers/microsoft.compute/virtualmachines/vm1" in sliced_ids
    assert "/subscriptions/sub1/resourcegroups/rg-app-dev/providers/microsoft.network/networkinterfaces/nic1" in sliced_ids
    assert "/subscriptions/sub1/resourcegroups/rg-app-dev/providers/microsoft.network/virtualnetworks/vnet1/subnets/subnet1" in sliced_ids
