"""Consultant-style local analysis workflow backed by Ollama."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .analysis_intents import AnalysisIntent, resolve_intents
from .config import Config, LocalAnalysisConfig
from .util import load_json_file, normalize_id, stable_id

log = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_/.-]+")
_MARKDOWN_HEADING_RE = re.compile(r"^##+\s+", re.MULTILINE)
_SHARED_SERVICE_TYPES = {
    "microsoft.keyvault/vaults",
    "microsoft.operationalinsights/workspaces",
    "microsoft.insights/components",
    "microsoft.network/privatednszones",
    "microsoft.network/privateendpoints",
    "microsoft.network/virtualnetworks",
    "microsoft.containerregistry/registries",
    "microsoft.appconfiguration/configurationstores",
}
_PUBLIC_TYPES = {
    "microsoft.network/publicipaddresses",
    "microsoft.network/applicationgateways",
    "microsoft.cdn/profiles",
    "microsoft.network/frontdoors",
    "microsoft.network/trafficmanagerprofiles",
}
_ANALYSIS_STAGES = {"prepare", "extract-evidence", "index", "analyze-intents", "synthesize", "review"}


@dataclass(frozen=True)
class AnalysisPackTarget:
    name: str
    slug: str
    base_dir: Path
    migration_dir: Path
    analysis_dir: Path
    is_root: bool


@dataclass
class Chunk:
    id: str
    pack: str
    source_file: str
    artifact_kind: str
    section: str
    text: str
    resource_ids: List[str]
    resource_names: List[str]
    resource_types: List[str]
    evidence_kind: str
    token_estimate: int
    keywords: List[str]

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pack": self.pack,
            "source_file": self.source_file,
            "artifact_kind": self.artifact_kind,
            "section": self.section,
            "text": self.text,
            "resource_ids": self.resource_ids,
            "resource_names": self.resource_names,
            "resource_types": self.resource_types,
            "evidence_kind": self.evidence_kind,
            "token_estimate": self.token_estimate,
            "keywords": self.keywords,
        }


class OllamaClient:
    def __init__(
        self,
        model: str,
        *,
        temperature: float = 0.1,
        endpoint: str = "http://127.0.0.1:11434/api/generate",
    ):
        self.model = model
        self.temperature = temperature
        self.endpoint = endpoint

    def generate(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": self.temperature},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {self.endpoint}. Ensure Ollama is running and the model {self.model!r} is available."
            ) from exc
        data = json.loads(body)
        text = str(data.get("response", "")).strip()
        if not text:
            raise RuntimeError(f"Ollama returned an empty response for model {self.model!r}")
        return text


def run_analysis(
    cfg: Config,
    *,
    stage: Optional[str] = None,
    intent_name: Optional[str] = None,
    pack_name: Optional[str] = None,
    rebuild_index: bool = False,
    model_override: Optional[str] = None,
    client: Optional[OllamaClient] = None,
) -> None:
    analysis_cfg = cfg.localAnalysis
    if not analysis_cfg.enabled:
        raise ValueError("localAnalysis.enabled must be true to run analyze")
    if stage and stage not in _ANALYSIS_STAGES:
        raise ValueError(f"Unsupported analysis stage: {stage!r}. Valid: {sorted(_ANALYSIS_STAGES)}")

    packs = _select_packs(cfg, analysis_cfg, pack_name)
    intents = resolve_intents([intent_name] if intent_name else analysis_cfg.intents)
    model = (model_override or analysis_cfg.model).strip()
    ollama_client = client or OllamaClient(model=model, temperature=analysis_cfg.temperature)

    for pack in packs:
        pack.analysis_dir.mkdir(parents=True, exist_ok=True)
        facts_dir = pack.analysis_dir / "facts"
        facts_dir.mkdir(parents=True, exist_ok=True)

        facts = _extract_evidence(pack, intents)
        _write_fact_files(facts_dir, facts)
        _write_json(pack.analysis_dir / "manifest.json", _prepare_pack_manifest(pack, model, intents, analysis_cfg, facts))
        (pack.analysis_dir / "agent-playbook.md").write_text(_build_agent_playbook(pack, intents, facts))
        if stage == "extract-evidence":
            continue

        chunks = _build_or_load_chunks(pack, facts, analysis_cfg, rebuild_index)
        if stage == "index":
            continue

        retrieval_debug: Dict[str, Any] = {}
        reports: Dict[str, str] = {}
        for intent in intents:
            selected_chunks = _select_chunks_for_intent(chunks, intent, analysis_cfg)
            missing_evidence = _detect_missing_evidence(facts, intent)
            retrieval_debug[intent.name] = {
                "chunk_ids": [chunk.id for chunk in selected_chunks],
                "sources": [chunk.source_file for chunk in selected_chunks],
                "token_estimate": sum(chunk.token_estimate for chunk in selected_chunks),
                "missing_evidence": missing_evidence,
            }
            prompt = _build_prompt(pack, facts, intent, selected_chunks, missing_evidence)
            report_text = _normalize_report(ollama_client.generate(prompt), intent, selected_chunks)
            (pack.analysis_dir / f"{intent.name}.md").write_text(report_text)
            reports[intent.name] = report_text
        _write_json(pack.analysis_dir / "retrieval_debug.json", retrieval_debug)
        if stage == "analyze-intents":
            continue

        (pack.analysis_dir / "consultant-pack.md").write_text(_synthesize_reports(pack, reports))
        (pack.analysis_dir / "executive-brief.md").write_text(_build_executive_brief(pack, facts, reports))
        if stage == "synthesize":
            continue

        (pack.analysis_dir / "review.md").write_text(_build_review(pack, reports, retrieval_debug))


def _prepare_pack_manifest(
    pack: AnalysisPackTarget,
    model: str,
    intents: Sequence[AnalysisIntent],
    analysis_cfg: LocalAnalysisConfig,
    facts: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "pack": pack.name,
        "slug": pack.slug,
        "baseDir": str(pack.base_dir),
        "migrationDir": str(pack.migration_dir),
        "analysisDir": str(pack.analysis_dir),
        "isRoot": pack.is_root,
        "model": model,
        "intents": [intent.name for intent in intents],
        "intentWorkflows": [_intent_workflow_payload(intent, facts) for intent in intents],
        "capabilityMatrix": facts.get("capability_matrix", {}),
        "includeArtifacts": analysis_cfg.includeArtifacts,
        "maxContextTokens": analysis_cfg.maxContextTokens,
        "maxChunkTokens": analysis_cfg.maxChunkTokens,
        "topK": analysis_cfg.topK,
    }


def _intent_workflow_payload(intent: AnalysisIntent, facts: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": intent.name,
        "title": intent.title,
        "domain": intent.domain,
        "audience": intent.audience,
        "specialistLens": intent.specialist_lens,
        "decisionOwners": intent.decision_owners,
        "requiredEvidence": intent.required_evidence,
        "helperScripts": intent.helper_scripts,
        "expectedGaps": intent.expected_gaps,
        "missingEvidence": _detect_missing_evidence(facts, intent),
    }


def _select_packs(cfg: Config, analysis_cfg: LocalAnalysisConfig, pack_name: Optional[str]) -> List[AnalysisPackTarget]:
    analysis_root = _analysis_output_root(cfg)
    targets: List[AnalysisPackTarget] = []
    if analysis_cfg.packScope in {"root", "both"}:
        migration_dir = _migration_pack_dir(cfg, cfg.app, is_root=True)
        if migration_dir.exists() and (Path(cfg.outputDir) / "graph.json").exists():
            targets.append(
                AnalysisPackTarget(
                    name=cfg.app,
                    slug="root",
                    base_dir=Path(cfg.outputDir),
                    migration_dir=migration_dir,
                    analysis_dir=analysis_root / "root",
                    is_root=True,
                )
            )
    if analysis_cfg.packScope in {"split", "both"}:
        applications_root = Path(cfg.outputDir) / "applications"
        if applications_root.exists():
            for child in sorted(applications_root.iterdir()):
                if not child.is_dir() or not (child / "graph.json").exists():
                    continue
                migration_dir = _migration_pack_dir(cfg, child.name, is_root=False)
                if not migration_dir.exists():
                    continue
                targets.append(
                    AnalysisPackTarget(
                        name=child.name,
                        slug=child.name,
                        base_dir=child,
                        migration_dir=migration_dir,
                        analysis_dir=analysis_root / child.name,
                        is_root=False,
                    )
                )
    if not targets:
        raise FileNotFoundError(
            f"No analysis targets were found under {cfg.outputDir}. Generate migration-plan outputs before running analyze."
        )
    if pack_name:
        targets = [target for target in targets if target.slug == pack_name or target.name == pack_name]
        if not targets:
            raise ValueError(f"Unknown analysis pack: {pack_name!r}")
    return targets


def _analysis_output_root(cfg: Config) -> Path:
    configured = cfg.localAnalysis.outputDir.strip()
    out = Path(configured)
    if out.is_absolute():
        return out
    return Path(cfg.outputDir) / out


def _migration_pack_dir(cfg: Config, pack_name: str, *, is_root: bool) -> Path:
    configured = cfg.migrationPlan.outputDir.strip()
    root = Path(cfg.outputDir) / (configured or "migration-plan")
    if is_root:
        return root
    return root / "applications" / pack_name


def _extract_evidence(pack: AnalysisPackTarget, intents: Sequence[AnalysisIntent]) -> Dict[str, Any]:
    graph = load_json_file(
        pack.base_dir / "graph.json",
        context="Analysis graph artifact",
        expected_type=dict,
        advice="Fix graph.json or rerun the graph stage before running analyze.",
    )
    inventory = _load_optional(pack.base_dir / "inventory.json", expected_type=list) or []
    unresolved = _load_optional(pack.base_dir / "unresolved.json", expected_type=list) or []
    policy = _load_optional(pack.base_dir / "policy.json", expected_type=list) or []
    rbac = _load_optional(pack.base_dir / "rbac.json", expected_type=list) or []

    graph_summary = _summarize_graph(graph, inventory)
    shared_services = _find_shared_services(graph)
    exposure_summary = _summarize_exposure(graph)
    policy_summary = _summarize_policy(policy)
    rbac_summary = _summarize_rbac(rbac)
    unresolved_summary = _summarize_unresolved(unresolved)
    telemetry_gaps = _summarize_telemetry_gaps(graph)
    pack_fact_sheet = {
            "pack": pack.name,
            "resources": graph_summary["resources"],
            "graphNodes": graph_summary["graphNodes"],
            "graphEdges": graph_summary["graphEdges"],
            "sharedServiceCount": len(shared_services["sharedServices"]),
            "publicExposureCount": len(exposure_summary["publicIndicators"]),
            "privateEndpointCount": exposure_summary["privateEndpointCount"],
            "nonCompliantPolicies": policy_summary["counts"].get("NonCompliant", 0),
            "rbacAssignments": rbac_summary["assignments"],
            "unresolvedReferences": unresolved_summary["count"],
            "telemetryEdges": telemetry_gaps["telemetryEdges"],
            "hasTelemetry": telemetry_gaps["hasTelemetry"],
    }
    capability_matrix = _build_capability_matrix(
        pack_fact_sheet=pack_fact_sheet,
        policy_summary=policy_summary,
        shared_services=shared_services,
        exposure_summary=exposure_summary,
        telemetry_gaps=telemetry_gaps,
        intents=intents,
    )
    return {
        "pack_fact_sheet": pack_fact_sheet,
        "graph_summary": graph_summary,
        "shared_services": shared_services,
        "exposure_summary": exposure_summary,
        "policy_summary": policy_summary,
        "rbac_summary": rbac_summary,
        "unresolved_summary": unresolved_summary,
        "telemetry_gaps": telemetry_gaps,
        "capability_matrix": capability_matrix,
    }


def _build_capability_matrix(
    *,
    pack_fact_sheet: Dict[str, Any],
    policy_summary: Dict[str, Any],
    shared_services: Dict[str, Any],
    exposure_summary: Dict[str, Any],
    telemetry_gaps: Dict[str, Any],
    intents: Sequence[AnalysisIntent],
) -> Dict[str, Any]:
    non_compliant = int(policy_summary.get("counts", {}).get("NonCompliant", 0))
    shared_count = len(shared_services.get("sharedServices", []))
    public_count = len(exposure_summary.get("publicIndicators", []))
    capabilities = {
        "dependencies": {
            "status": "partial",
            "signals": [f"shared_service_candidates={shared_count}", f"telemetry_edges={pack_fact_sheet.get('telemetryEdges', 0)}"],
        },
        "network_exposure": {
            "status": "partial",
            "signals": [f"public_indicators={public_count}", f"private_endpoints={pack_fact_sheet.get('privateEndpointCount', 0)}"],
        },
        "governance_policy": {
            "status": "partial" if non_compliant or policy_summary.get("counts") else "weak",
            "signals": [f"policy_non_compliant={non_compliant}"],
        },
        "encryption": {
            "status": "weak",
            "signals": ["No dedicated encryption extractor yet."],
        },
        "backup_dr": {
            "status": "weak",
            "signals": ["No dedicated backup or recovery extractor yet."],
        },
        "integration_logic_apps": {
            "status": "weak",
            "signals": ["Integration-specific connector and workflow evidence is not yet extracted."],
        },
        "landing_zone_fit": {
            "status": "partial",
            "signals": ["Agent-side fit-gap workflow is wired, but enterprise standards and specialist extractors are still needed."],
        },
    }
    return {
        "intentCoverage": [intent.name for intent in intents],
        "capabilities": capabilities,
    }


def _load_optional(path: Path, *, expected_type: type | None = None) -> Any:
    if not path.exists():
        return [] if expected_type is list else None
    return load_json_file(
        path,
        context="Optional analysis artifact",
        expected_type=expected_type,
        advice=f"Fix {path.name} or regenerate the prerequisite artifact before running analyze.",
    )


def _summarize_graph(graph: Dict[str, Any], inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    telemetry_edges = graph.get("telemetryEdges") or []
    rg_edges = 0
    sub_edges = 0
    type_counts: Dict[str, int] = {}
    node_by_id = {normalize_id(node.get("id", "")): node for node in nodes if node.get("id")}
    for resource in inventory or nodes:
        rtype = str(resource.get("type", "unknown")).lower()
        type_counts[rtype] = type_counts.get(rtype, 0) + 1
    for edge in edges:
        source = node_by_id.get(normalize_id(edge.get("source", "")), {})
        target = node_by_id.get(normalize_id(edge.get("target", "")), {})
        if source.get("resourceGroup") and target.get("resourceGroup") and source.get("resourceGroup") != target.get("resourceGroup"):
            rg_edges += 1
        if source.get("subscriptionId") and target.get("subscriptionId") and source.get("subscriptionId") != target.get("subscriptionId"):
            sub_edges += 1
    return {
        "resources": len(inventory) or len(nodes),
        "graphNodes": len(nodes),
        "graphEdges": len(edges),
        "telemetryEdges": len(telemetry_edges),
        "externalNodes": sum(1 for node in nodes if node.get("isExternal")),
        "crossResourceGroupEdges": rg_edges,
        "crossSubscriptionEdges": sub_edges,
        "topResourceTypes": sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))[:10],
    }


def _find_shared_services(graph: Dict[str, Any]) -> Dict[str, Any]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_by_id = {normalize_id(node.get("id", "")): node for node in nodes if node.get("id")}
    incoming: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        target_id = normalize_id(edge.get("target", ""))
        source = node_by_id.get(normalize_id(edge.get("source", "")))
        target = node_by_id.get(target_id)
        if not source or not target:
            continue
        incoming.setdefault(target_id, []).append(source)
    shared = []
    for target_id, sources in incoming.items():
        target = node_by_id[target_id]
        target_type = str(target.get("type", "")).lower()
        groups = {source.get("resourceGroup") for source in sources if source.get("resourceGroup")}
        subs = {source.get("subscriptionId") for source in sources if source.get("subscriptionId")}
        if target_type not in _SHARED_SERVICE_TYPES and len(groups) < 2 and len(subs) < 2:
            continue
        shared.append(
            {
                "id": target.get("id"),
                "name": target.get("name"),
                "type": target_type,
                "consumerCount": len(sources),
                "resourceGroups": sorted(groups),
                "subscriptions": sorted(subs),
            }
        )
    shared.sort(key=lambda item: (-len(item["subscriptions"]), -len(item["resourceGroups"]), -item["consumerCount"], item["name"] or ""))
    return {"sharedServices": shared[:20]}


def _summarize_exposure(graph: Dict[str, Any]) -> Dict[str, Any]:
    nodes = graph.get("nodes") or []
    public_indicators: List[str] = []
    private_endpoint_count = 0
    for node in nodes:
        node_type = str(node.get("type", "")).lower()
        props = node.get("properties") or {}
        if node_type in _PUBLIC_TYPES or props.get("defaultHostName") or str(props.get("publicNetworkAccess", "")).lower() == "enabled":
            public_indicators.append(node.get("name") or node.get("id"))
        if node_type == "microsoft.network/privateendpoints":
            private_endpoint_count += 1
    return {
        "publicIndicators": sorted(dict.fromkeys(public_indicators)),
        "privateEndpointCount": private_endpoint_count,
    }


def _summarize_policy(policy_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    hotspots: Dict[str, int] = {}
    for row in policy_rows:
        state = str(row.get("complianceState", "Unknown")).strip() or "Unknown"
        counts[state] = counts.get(state, 0) + 1
        if state == "NonCompliant":
            resource_id = str(row.get("resourceId") or row.get("resource_id") or "unknown")
            hotspots[resource_id] = hotspots.get(resource_id, 0) + 1
    return {
        "counts": counts,
        "nonCompliantHotspots": sorted(hotspots.items(), key=lambda item: (-item[1], item[0]))[:10],
    }


def _summarize_rbac(rbac_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    scopes: Dict[str, int] = {}
    for row in rbac_rows:
        scope = str(row.get("scope") or "unknown")
        scopes[scope] = scopes.get(scope, 0) + 1
    return {
        "assignments": len(rbac_rows),
        "topScopes": sorted(scopes.items(), key=lambda item: (-item[1], item[0]))[:10],
    }


def _summarize_unresolved(unresolved: List[str]) -> Dict[str, Any]:
    by_provider: Dict[str, int] = {}
    for item in unresolved:
        parts = normalize_id(str(item)).split("/providers/")
        provider = parts[1].split("/")[0] if len(parts) > 1 else "unknown"
        by_provider[provider] = by_provider.get(provider, 0) + 1
    return {
        "count": len(unresolved),
        "byProvider": sorted(by_provider.items(), key=lambda item: (-item[1], item[0]))[:10],
        "sample": unresolved[:20],
    }


def _summarize_telemetry_gaps(graph: Dict[str, Any]) -> Dict[str, Any]:
    telemetry_edges = graph.get("telemetryEdges") or []
    return {
        "hasTelemetry": bool(telemetry_edges),
        "telemetryEdges": len(telemetry_edges),
        "gapSummary": (
            "Telemetry-derived relationships were available for this pack."
            if telemetry_edges
            else "Telemetry-derived relationships were not available for this pack."
        ),
    }


def _write_fact_files(facts_dir: Path, facts: Dict[str, Any]) -> None:
    for name, payload in facts.items():
        _write_json(facts_dir / f"{name}.json", payload)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _build_or_load_chunks(
    pack: AnalysisPackTarget,
    facts: Dict[str, Any],
    analysis_cfg: LocalAnalysisConfig,
    rebuild_index: bool,
) -> List[Chunk]:
    chunks_path = pack.analysis_dir / "chunks.jsonl"
    if chunks_path.exists() and not rebuild_index:
        return _load_chunks(chunks_path)
    chunks = _build_chunks(pack, facts, analysis_cfg)
    chunks_path.write_text("".join(json.dumps(chunk.to_json(), sort_keys=True) + "\n" for chunk in chunks))
    return chunks


def _load_chunks(path: Path) -> List[Chunk]:
    items: List[Chunk] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        items.append(Chunk(**json.loads(line)))
    return items


def _build_chunks(pack: AnalysisPackTarget, facts: Dict[str, Any], analysis_cfg: LocalAnalysisConfig) -> List[Chunk]:
    chunks: List[Chunk] = []
    for name, payload in facts.items():
        chunks.append(
            _make_chunk(
                pack=pack,
                source_file=f"facts/{name}.json",
                artifact_kind="facts",
                section=name,
                text=json.dumps(payload, indent=2, sort_keys=True),
                evidence_kind="deterministic-summary",
            )
        )
    for artifact in analysis_cfg.includeArtifacts:
        if artifact == "migration-plan":
            for path in sorted(pack.migration_dir.glob("*.md")):
                chunks.extend(_chunk_markdown_file(pack, path))
        else:
            path = pack.base_dir / f"{artifact}.json"
            if path.exists():
                chunks.extend(_chunk_json_file(pack, path, artifact_kind=artifact))
    return chunks


def _chunk_markdown_file(pack: AnalysisPackTarget, path: Path) -> List[Chunk]:
    parts = _split_markdown_sections(path.read_text())
    chunks: List[Chunk] = []
    for idx, (section, body) in enumerate(parts, start=1):
        chunks.append(
            _make_chunk(
                pack=pack,
                source_file=path.name,
                artifact_kind="migration-plan",
                section=section or f"section-{idx}",
                text=body.strip(),
                evidence_kind="generated-markdown",
            )
        )
    return chunks


def _split_markdown_sections(text: str) -> List[Tuple[str, str]]:
    if not text.strip():
        return []
    matches = list(_MARKDOWN_HEADING_RE.finditer(text))
    if not matches:
        return [("document", text)]
    sections: List[Tuple[str, str]] = []
    first = matches[0]
    if first.start() > 0:
        sections.append(("overview", text[:first.start()]))
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        heading_line_end = text.find("\n", start)
        heading_line = text[start:end if heading_line_end == -1 else heading_line_end]
        heading = heading_line.lstrip("#").strip() or f"section-{idx + 1}"
        sections.append((heading, text[start:end]))
    return sections


def _chunk_json_file(pack: AnalysisPackTarget, path: Path, *, artifact_kind: str) -> List[Chunk]:
    data = load_json_file(path, context="Analysis source artifact")
    chunks: List[Chunk] = []
    if isinstance(data, list):
        for idx, item in enumerate(data, start=1):
            chunks.append(
                _make_chunk(
                    pack=pack,
                    source_file=path.name,
                    artifact_kind=artifact_kind,
                    section=f"item-{idx}",
                    text=json.dumps(item, indent=2, sort_keys=True),
                    evidence_kind=f"{artifact_kind}-artifact",
                )
            )
    elif isinstance(data, dict):
        for key, value in data.items():
            chunks.append(
                _make_chunk(
                    pack=pack,
                    source_file=path.name,
                    artifact_kind=artifact_kind,
                    section=str(key),
                    text=json.dumps(value, indent=2, sort_keys=True),
                    evidence_kind=f"{artifact_kind}-artifact",
                )
            )
    else:
        chunks.append(
            _make_chunk(
                pack=pack,
                source_file=path.name,
                artifact_kind=artifact_kind,
                section="document",
                text=json.dumps(data, indent=2, sort_keys=True),
                evidence_kind=f"{artifact_kind}-artifact",
            )
        )
    return chunks


def _make_chunk(
    *,
    pack: AnalysisPackTarget,
    source_file: str,
    artifact_kind: str,
    section: str,
    text: str,
    evidence_kind: str,
) -> Chunk:
    resource_ids = sorted({match.group(0) for match in re.finditer(r"/subscriptions/[^\s\"']+", text, re.IGNORECASE)})[:20]
    resource_names = _extract_named_tokens(text)[:20]
    resource_types = sorted({item.lower() for item in re.findall(r"microsoft\.[a-z0-9./-]+", text, re.IGNORECASE)})[:20]
    keywords = sorted(set(_tokenize(" ".join([section, source_file, text]))))[:80]
    return Chunk(
        id=stable_id(f"{pack.slug}:{source_file}:{section}:{text[:120]}"),
        pack=pack.slug,
        source_file=source_file,
        artifact_kind=artifact_kind,
        section=section,
        text=text,
        resource_ids=resource_ids,
        resource_names=resource_names,
        resource_types=resource_types,
        evidence_kind=evidence_kind,
        token_estimate=_estimate_tokens(text),
        keywords=keywords,
    )


def _extract_named_tokens(text: str) -> List[str]:
    matches = re.findall(r'"name"\s*:\s*"([^"]+)"', text)
    if matches:
        return matches
    return re.findall(r"\b[a-zA-Z][a-zA-Z0-9-]{2,}\b", text)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) * 4 // 3)


def _tokenize(text: str) -> List[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text) if len(token) > 2]


def _fact_present(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, dict):
        return bool(payload) and any(_fact_present(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_fact_present(value) for value in payload)
    if isinstance(payload, str):
        return bool(payload.strip())
    return True


def _detect_missing_evidence(facts: Dict[str, Any], intent: AnalysisIntent) -> List[str]:
    missing: List[str] = []
    for key in intent.required_evidence:
        fact_name = key.replace("-", "_")
        if fact_name not in facts or not _fact_present(facts.get(fact_name)):
            missing.append(f"Required evidence not available: {key}")
    implemented_helpers = {
        "pack_fact_sheet",
        "summarize_graph",
        "summarize_policy",
        "summarize_rbac",
        "find_shared_services",
        "summarize_telemetry_gaps",
        "summarize_exposure",
        "summarize_unresolved",
    }
    for helper in intent.helper_scripts:
        if helper not in implemented_helpers:
            missing.append(f"Specialist extractor not implemented yet: {helper}")
    if intent.domain == "security":
        missing.append("Detailed encryption settings are not yet extracted per resource.")
    if intent.name == "backup-dr-posture":
        missing.append("Backup policy, restore readiness, and DR evidence are not yet extracted.")
    if intent.name == "logic-apps-integration":
        missing.append("Logic App connector, trigger, and workflow evidence are not yet extracted.")
    if intent.name == "landing-zone-fit":
        missing.append("Landing Zone reference standards are not yet provided to the analysis engine.")
    return sorted(dict.fromkeys(missing))


def _build_agent_playbook(pack: AnalysisPackTarget, intents: Sequence[AnalysisIntent], facts: Dict[str, Any]) -> str:
    lines = [f"# Agent Playbook - {pack.name}", "", "## Capability Matrix", ""]
    capability_matrix = facts.get("capability_matrix", {})
    for capability, detail in sorted(capability_matrix.get("capabilities", {}).items()):
        lines.append(f"- `{capability}`: {detail.get('status', 'unknown')} :: {'; '.join(detail.get('signals', []))}")
    lines.extend(["", "## Intent Workflows", ""])
    for intent in intents:
        lines.extend([
            f"### {intent.title}",
            "",
            f"- Domain: {intent.domain}",
            f"- Specialist lens: {intent.specialist_lens}",
            f"- Audience: {', '.join(intent.audience)}",
            f"- Decision owners: {', '.join(intent.decision_owners)}",
            f"- Required evidence: {', '.join(intent.required_evidence)}",
            f"- Expected gaps: {', '.join(intent.expected_gaps)}",
            "- Missing evidence:",
        ])
        missing = _detect_missing_evidence(facts, intent)
        if missing:
            lines.extend(f"  - {item}" for item in missing)
        else:
            lines.append("  - none")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _select_chunks_for_intent(
    chunks: Sequence[Chunk],
    intent: AnalysisIntent,
    analysis_cfg: LocalAnalysisConfig,
) -> List[Chunk]:
    chosen: List[Chunk] = []
    used_ids = set()
    for key in intent.required_evidence:
        fact_name = key.replace("-", "_")
        for chunk in chunks:
            if chunk.source_file == f"facts/{fact_name}.json" and chunk.id not in used_ids:
                chosen.append(chunk)
                used_ids.add(chunk.id)
                break
    query_terms = set(_tokenize(" ".join([intent.name, intent.title, intent.business_goal, intent.prompt_template])))
    scores: List[Tuple[int, Chunk]] = []
    profile = set(intent.retrieval_profile)
    for chunk in chunks:
        if chunk.id in used_ids:
            continue
        if profile and chunk.artifact_kind not in profile:
            continue
        score = len(query_terms.intersection(chunk.keywords)) * 5
        if chunk.artifact_kind == "facts":
            score += 10
        if chunk.artifact_kind in profile:
            score += 3
        scores.append((score, chunk))
    scores.sort(key=lambda item: (-item[0], item[1].source_file, item[1].section))
    total = sum(chunk.token_estimate for chunk in chosen)
    limit = analysis_cfg.topK + len(intent.required_evidence)
    for score, chunk in scores:
        if score <= 0 or len(chosen) >= limit:
            continue
        if total + chunk.token_estimate > analysis_cfg.maxContextTokens:
            continue
        chosen.append(chunk)
        total += chunk.token_estimate
    return chosen


def _build_prompt(
    pack: AnalysisPackTarget,
    facts: Dict[str, Any],
    intent: AnalysisIntent,
    chunks: Sequence[Chunk],
    missing_evidence: Sequence[str],
) -> str:
    lines = [
        f"Pack: {pack.name}",
        f"Business goal: {intent.business_goal}",
        f"Domain: {intent.domain}",
        f"Specialist lens: {intent.specialist_lens}",
        f"Audience: {', '.join(intent.audience)}",
        f"Decision owners: {', '.join(intent.decision_owners)}",
        "Rules:",
        "- Use only the provided evidence.",
        "- Distinguish known facts, inferred interpretation, risks, open questions, and confidence notes.",
        "- Cite evidence using chunk IDs in brackets, for example [evidence:abcd1234].",
        "- Escalate uncertainty instead of guessing.",
        "- Prefer deterministic fact files over raw artifact interpretation.",
        "- If key evidence is missing, say so explicitly and treat the conclusion as provisional.",
        "Review checklist:",
    ]
    lines.extend(f"- {item}" for item in intent.review_checklist)
    lines.extend([
        "",
        "Expected evidence gaps:",
    ])
    lines.extend(f"- {item}" for item in intent.expected_gaps)
    lines.extend([
        "",
        "Known missing evidence for this run:",
    ])
    if missing_evidence:
        lines.extend(f"- {item}" for item in missing_evidence)
    else:
        lines.append("- none identified from current metadata")
    lines.extend([
        "",
        "Fact sheet summary:",
        json.dumps(facts.get("pack_fact_sheet", {}), indent=2, sort_keys=True),
        "",
        "Capability matrix:",
        json.dumps(facts.get("capability_matrix", {}), indent=2, sort_keys=True),
        "",
        f"Task: {intent.prompt_template}",
        "",
        "Required output sections:",
    ])
    lines.extend(f"- {section}" for section in intent.output_sections)
    lines.extend(["", "Evidence:"])
    for chunk in chunks:
        lines.extend([
            f"[evidence:{chunk.id}] source={chunk.source_file} section={chunk.section} kind={chunk.evidence_kind}",
            chunk.text,
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def _normalize_report(model_output: str, intent: AnalysisIntent, chunks: Sequence[Chunk]) -> str:
    text = model_output.strip()
    if not text.startswith("#"):
        text = "\n".join([f"# {intent.title}", "", text])
    for section in ["Missing Evidence", "Confidence Notes"]:
        if f"## {section}" not in text:
            text = text.rstrip() + f"\n\n## {section}\n\n- Not explicitly addressed by the model.\n"
    if "## Evidence References" not in text:
        refs = [f"- [evidence:{chunk.id}] {chunk.source_file} :: {chunk.section}" for chunk in chunks]
        text = text.rstrip() + "\n\n## Evidence References\n\n" + "\n".join(refs) + "\n"
    return text.rstrip() + "\n"


def _synthesize_reports(pack: AnalysisPackTarget, reports: Dict[str, str]) -> str:
    lines = [f"# Consultant Pack - {pack.name}", "", "## Included Reports", ""]
    for name in sorted(reports):
        lines.append(f"- `{name}.md` - {name.replace('-', ' ').title()}")
    lines.extend(["", "## Consolidated Narrative", ""])
    for name in sorted(reports):
        lines.append(f"### {name.replace('-', ' ').title()}")
        lines.append("")
        lines.append(_first_non_heading_paragraph(reports[name]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_executive_brief(pack: AnalysisPackTarget, facts: Dict[str, Any], reports: Dict[str, str]) -> str:
    fact_sheet = facts.get("pack_fact_sheet", {})
    lines = [
        f"# Executive Brief - {pack.name}",
        "",
        "## Snapshot",
        "",
        f"- Resources: {fact_sheet.get('resources', 0)}",
        f"- Shared service candidates: {fact_sheet.get('sharedServiceCount', 0)}",
        f"- Public exposure indicators: {fact_sheet.get('publicExposureCount', 0)}",
        f"- Non-compliant policies: {fact_sheet.get('nonCompliantPolicies', 0)}",
        f"- Unresolved references: {fact_sheet.get('unresolvedReferences', 0)}",
        "",
        "## Analyst Summary",
        "",
    ]
    source_name = "migration-readiness" if "migration-readiness" in reports else sorted(reports)[0]
    lines.append(_first_non_heading_paragraph(reports[source_name]))
    return "\n".join(lines).rstrip() + "\n"


def _build_review(pack: AnalysisPackTarget, reports: Dict[str, str], retrieval_debug: Dict[str, Any]) -> str:
    lines = [f"# Review - {pack.name}", "", "## Checks", ""]
    for name, report in sorted(reports.items()):
        missing_sections = []
        for section in ["Known Facts", "Missing Evidence", "Confidence Notes", "Evidence References"]:
            if f"## {section}" not in report:
                missing_sections.append(section)
        debug = retrieval_debug.get(name, {})
        missing_evidence = debug.get("missing_evidence", [])
        lines.append(
            f"- `{name}`: chunks={len(debug.get('chunk_ids', []))}; missing_sections={missing_sections or ['none']}; missing_evidence={len(missing_evidence)}"
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- Outputs remain evidence-assisted and should be reviewed by an architect before delivery.",
        "- Missing sections or very low retrieval counts indicate the prompt or evidence selection should be refined.",
        "- Specialist intents may still report structural gaps until corresponding extractors are implemented.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _first_non_heading_paragraph(text: str) -> str:
    for block in [part.strip() for part in text.split("\n\n") if part.strip()]:
        if not block.startswith("#"):
            return block
    return "No narrative summary was generated."
