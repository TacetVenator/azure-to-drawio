"""Tests for consultant-style local analysis."""
from __future__ import annotations

import json

from tools.azdisc.analyze import run_analysis
from tools.azdisc.config import load_config
from tools.azdisc.migration_plan import generate_migration_plan


class FakeClient:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        evidence_ids = []
        for line in prompt.splitlines():
            if line.startswith("[evidence:"):
                evidence_ids.append(line.split("]", 1)[0][1:])
        refs = "\n".join(f"- [{item}]" for item in evidence_ids[:3])
        return (
            "# Mock Report\n\n"
            "## Executive Summary\n\n"
            "Generated from deterministic evidence.\n\n"
            "## Known Facts\n\n"
            "- Fact based on supplied analysis inputs.\n\n"
            "## Inferred Interpretation\n\n"
            "- Conservative interpretation only.\n\n"
            "## Open Questions\n\n"
            "- What remains to confirm?\n\n"
            "## Evidence References\n\n"
            f"{refs}\n"
        )


def _write_pack_inputs(base_dir, *, with_telemetry: bool = True) -> None:
    graph = {
        "nodes": [
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-app/providers/Microsoft.Web/sites/app1",
                "name": "app1",
                "type": "microsoft.web/sites",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-app",
                "properties": {"defaultHostName": "app1.azurewebsites.net", "publicNetworkAccess": "Enabled"},
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-shared/providers/Microsoft.KeyVault/vaults/kv-shared",
                "name": "kv-shared",
                "type": "microsoft.keyvault/vaults",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-shared",
            },
            {
                "id": "/subscriptions/sub1/resourceGroups/rg-net/providers/Microsoft.Network/privateEndpoints/pe-sql",
                "name": "pe-sql",
                "type": "microsoft.network/privateendpoints",
                "subscriptionId": "sub1",
                "resourceGroup": "rg-net",
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
        ] if with_telemetry else [],
    }
    inventory = [
        {"id": graph["nodes"][0]["id"], "name": "app1", "type": "microsoft.web/sites"},
        {"id": graph["nodes"][1]["id"], "name": "kv-shared", "type": "microsoft.keyvault/vaults"},
        {"id": graph["nodes"][2]["id"], "name": "pe-sql", "type": "microsoft.network/privateendpoints"},
    ]
    unresolved = [
        "/subscriptions/sub1/resourceGroups/rg-dns/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
    ]
    policy = [
        {
            "resourceId": graph["nodes"][0]["id"],
            "complianceState": "NonCompliant",
            "policyAssignmentName": "deny-public",
        }
    ]
    rbac = [{"id": "assignment-1", "scope": graph["nodes"][0]["id"]}]
    (base_dir / "graph.json").write_text(json.dumps(graph))
    (base_dir / "inventory.json").write_text(json.dumps(inventory))
    (base_dir / "unresolved.json").write_text(json.dumps(unresolved))
    (base_dir / "policy.json").write_text(json.dumps(policy))
    (base_dir / "rbac.json").write_text(json.dumps(rbac))


def test_load_config_supports_local_analysis(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "app": "contoso",
                "subscriptions": ["sub1"],
                "seedResourceGroups": ["rg-app"],
                "outputDir": str(tmp_path / "out"),
                "localAnalysis": {
                    "enabled": True,
                    "model": "gemma4",
                    "intents": ["estate-summary"],
                    "packScope": "root",
                    "topK": 4,
                },
            }
        )
    )

    cfg = load_config(str(config_path))

    assert cfg.localAnalysis.enabled is True
    assert cfg.localAnalysis.model == "gemma4"
    assert cfg.localAnalysis.intents == ["estate-summary"]
    assert cfg.localAnalysis.packScope == "root"
    assert cfg.localAnalysis.topK == 4


def test_run_analysis_generates_consultant_outputs(tmp_path):
    _write_pack_inputs(tmp_path)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "app": "contoso",
                "subscriptions": ["sub1"],
                "seedResourceGroups": ["rg-app"],
                "outputDir": str(tmp_path),
                "migrationPlan": {"enabled": True, "applicationScope": "root", "includeCopilotPrompts": True},
                "localAnalysis": {"enabled": True, "model": "gemma4", "intents": ["estate-summary", "migration-readiness"], "packScope": "root"},
            }
        )
    )
    cfg = load_config(str(cfg_path))
    generate_migration_plan(cfg)

    client = FakeClient()
    run_analysis(cfg, client=client)

    analysis_dir = tmp_path / "local-analysis" / "root"
    assert (analysis_dir / "manifest.json").exists()
    assert (analysis_dir / "chunks.jsonl").exists()
    assert (analysis_dir / "retrieval_debug.json").exists()
    assert (analysis_dir / "estate-summary.md").exists()
    assert (analysis_dir / "migration-readiness.md").exists()
    assert (analysis_dir / "consultant-pack.md").exists()
    assert (analysis_dir / "executive-brief.md").exists()
    assert (analysis_dir / "review.md").exists()
    assert (analysis_dir / "agent-playbook.md").exists()
    assert (analysis_dir / "facts" / "pack_fact_sheet.json").exists()

    manifest = json.loads((analysis_dir / "manifest.json").read_text())
    assert manifest["pack"] == "contoso"
    assert manifest["model"] == "gemma4"
    assert "capabilityMatrix" in manifest
    assert manifest["intentWorkflows"]

    report = (analysis_dir / "migration-readiness.md").read_text()
    assert "## Known Facts" in report
    assert "## Missing Evidence" in report
    assert "## Confidence Notes" in report
    assert "## Evidence References" in report
    playbook = (analysis_dir / "agent-playbook.md").read_text()
    assert "## Capability Matrix" in playbook
    assert client.prompts


def test_run_analysis_index_stage_writes_facts_and_chunks_only(tmp_path):
    _write_pack_inputs(tmp_path, with_telemetry=False)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "app": "contoso",
                "subscriptions": ["sub1"],
                "seedResourceGroups": ["rg-app"],
                "outputDir": str(tmp_path),
                "migrationPlan": {"enabled": True, "applicationScope": "root", "includeCopilotPrompts": True},
                "localAnalysis": {"enabled": True, "model": "gemma4", "intents": ["evidence-gaps"], "packScope": "root"},
            }
        )
    )
    cfg = load_config(str(cfg_path))
    generate_migration_plan(cfg)

    run_analysis(cfg, stage="index", client=FakeClient())

    analysis_dir = tmp_path / "local-analysis" / "root"
    assert (analysis_dir / "chunks.jsonl").exists()
    assert (analysis_dir / "facts" / "telemetry_gaps.json").exists()
    assert not (analysis_dir / "evidence-gaps.md").exists()


def test_specialist_intent_prompt_includes_missing_evidence_and_agent_metadata(tmp_path):
    _write_pack_inputs(tmp_path, with_telemetry=False)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "app": "contoso",
                "subscriptions": ["sub1"],
                "seedResourceGroups": ["rg-app"],
                "outputDir": str(tmp_path),
                "migrationPlan": {"enabled": True, "applicationScope": "root", "includeCopilotPrompts": True},
                "localAnalysis": {"enabled": True, "model": "gemma4", "intents": ["landing-zone-fit", "encryption-posture"], "packScope": "root"},
            }
        )
    )
    cfg = load_config(str(cfg_path))
    generate_migration_plan(cfg)

    client = FakeClient()
    run_analysis(cfg, client=client)

    manifest = json.loads((tmp_path / "local-analysis" / "root" / "manifest.json").read_text())
    names = [item["name"] for item in manifest["intentWorkflows"]]
    assert "landing-zone-fit" in names
    assert "encryption-posture" in names
    fit_workflow = next(item for item in manifest["intentWorkflows"] if item["name"] == "landing-zone-fit")
    assert fit_workflow["missingEvidence"]
    assert any("Landing Zone reference standards" in item for item in fit_workflow["missingEvidence"])

    prompt_text = "\n".join(client.prompts)
    assert "Specialist lens: Landing Zone control and platform fit-gap review" in prompt_text
    assert "Known missing evidence for this run:" in prompt_text
    assert "Capability matrix:" in prompt_text
