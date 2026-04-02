from __future__ import annotations

import io
import json

from tools.azdisc.config import Config
from tools.azdisc.review import run_review_related


def test_run_review_related_updates_promoted_file_and_supports_props(tmp_path):
    inventory = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
            "name": "app1",
            "type": "Microsoft.Web/sites",
            "resourceGroup": "rg-app",
            "subscriptionId": "sub1",
            "properties": {"notes": "sap shared app"},
            "tags": {"Application": "SAP"},
        }
    ]
    candidates = [
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-ops/providers/Microsoft.Logic/workflows/sap-sync",
            "name": "sap-sync",
            "type": "Microsoft.Logic/workflows",
            "resourceGroup": "rg-ops",
            "subscriptionId": "sub1",
            "properties": {"state": "Enabled"},
            "matchedSearchStrings": ["SAP"],
            "discoveryEvidence": [
                {
                    "source": "deep-discovery",
                    "matchField": "name",
                    "matchedTerms": ["SAP"],
                    "explanation": "Candidate surfaced because resource name 'sap-sync' matched search strings: SAP.",
                }
            ],
        },
        {
            "id": "/subscriptions/sub1/resourceGroups/rg-ops/providers/Microsoft.Insights/dataCollectionRules/bpc-monitor",
            "name": "bpc-monitor",
            "type": "Microsoft.Insights/dataCollectionRules",
            "resourceGroup": "rg-ops",
            "subscriptionId": "sub1",
            "properties": {"state": "Enabled"},
            "matchedSearchStrings": ["bpc"],
            "discoveryEvidence": [
                {
                    "source": "deep-discovery",
                    "matchField": "name",
                    "matchedTerms": ["bpc"],
                    "explanation": "Candidate surfaced because resource name 'bpc-monitor' matched search strings: bpc.",
                }
            ],
        },
    ]
    (tmp_path / "inventory.json").write_text(json.dumps(inventory))

    cfg = Config(
        app="sap-app",
        subscriptions=["sub1"],
        seedResourceGroups=["rg-app"],
        outputDir=str(tmp_path),
    )
    cfg.deepDiscovery.enabled = True
    cfg.ensure_deep_output_dir()
    cfg.deep_out(cfg.deepDiscovery.candidateFile).write_text(json.dumps(candidates))
    cfg.deep_out(cfg.deepDiscovery.promotedFile).write_text(json.dumps(candidates))

    commands = iter(["list", "drop 2", "props 1 discoveryEvidence", "save", "quit"])
    output = io.StringIO()
    run_review_related(cfg, input_fn=lambda _prompt: next(commands), output=output)

    promoted = json.loads(cfg.deep_out(cfg.deepDiscovery.promotedFile).read_text())
    assert [item["name"] for item in promoted] == ["sap-sync"]
    assert "Dropped bpc-monitor" in output.getvalue()
    assert "Candidate surfaced because resource name 'sap-sync' matched search strings: SAP." in output.getvalue()
    report = cfg.deep_out("related_review.md").read_text()
    assert "sap-sync [kept]" in report
    assert "bpc-monitor [dropped]" in report
