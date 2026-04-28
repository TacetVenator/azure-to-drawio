"""Deterministic ScenarioSpec parser and graph adapter.

This module intentionally avoids LLM inference. It parses controlled scenario
prompts (like the Azure architecture example in Generate.md) into a structured
spec and then produces a graph-shaped payload that can feed drawio generation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional


_SECTION_HEADERS = {
    "resources": re.compile(r"^\s*resources\s*:\s*$", re.IGNORECASE),
    "connections": re.compile(r"^\s*connections\s*:\s*$", re.IGNORECASE),
    "layout": re.compile(r"^\s*layout\s+rules\s*:\s*$", re.IGNORECASE),
}

_CATEGORY_LINE_RE = re.compile(r"^\s*\d+\.\s*\*\*(.+?)\*\*\s*$")
_BULLET_RE = re.compile(r"^\s*-\s+(.+?)\s*$")
_QUOTED_RE = re.compile(r'"([^"]+)"')
_CIDR_RE = re.compile(r"\(([^)]+/\d+)\)")


@dataclass
class ScenarioResource:
    category: str
    kind: str
    name: str
    cidr: Optional[str] = None
    details: str = ""


@dataclass
class ScenarioConnection:
    chain: List[str]


@dataclass
class ScenarioSpec:
    title: str
    scenario: str
    resources: List[ScenarioResource] = field(default_factory=list)
    connections: List[ScenarioConnection] = field(default_factory=list)
    layout_rules: List[str] = field(default_factory=list)


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "item"


def parse_scenario_spec(text: str) -> ScenarioSpec:
    """Parse a controlled architecture prompt into a deterministic ScenarioSpec."""
    lines = [ln.rstrip() for ln in text.splitlines()]

    title = ""
    scenario = ""
    section = ""
    category = "General"
    subcontext = ""

    resources: List[ScenarioResource] = []
    connections: List[ScenarioConnection] = []
    layout_rules: List[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if not title and not line.endswith(":"):
            title = line
            continue

        if line.lower().startswith("scenario:"):
            scenario = line.split(":", 1)[1].strip()
            continue

        if _SECTION_HEADERS["resources"].match(line):
            section = "resources"
            category = "General"
            subcontext = ""
            continue
        if _SECTION_HEADERS["connections"].match(line):
            section = "connections"
            continue
        if _SECTION_HEADERS["layout"].match(line):
            section = "layout"
            continue

        cat_match = _CATEGORY_LINE_RE.match(line)
        if cat_match and section == "resources":
            category = cat_match.group(1).strip()
            subcontext = ""
            continue

        bullet_match = _BULLET_RE.match(line)
        if not bullet_match:
            continue

        payload = bullet_match.group(1).strip()

        if section == "resources":
            if payload.endswith(":"):
                subcontext = payload[:-1].strip()
                continue

            kind = ""
            details = ""
            name = ""

            if ":" in payload:
                kind, details = [p.strip() for p in payload.split(":", 1)]
                quoted = _QUOTED_RE.search(details)
                name = quoted.group(1).strip() if quoted else details
            else:
                details = payload
                if subcontext:
                    kind = subcontext.rstrip("s")
                else:
                    kind = payload
                quoted = _QUOTED_RE.search(payload)
                name = quoted.group(1).strip() if quoted else payload

            cidr_match = _CIDR_RE.search(payload)
            cidr = cidr_match.group(1).strip() if cidr_match else None

            resources.append(
                ScenarioResource(
                    category=category,
                    kind=kind.strip() or "Resource",
                    name=name.strip(),
                    cidr=cidr,
                    details=details,
                )
            )
            continue

        if section == "connections":
            # Support either unicode arrow or ascii arrow.
            normalized = payload.replace("->", "→")
            chain = [part.strip() for part in normalized.split("→") if part.strip()]
            if len(chain) >= 2:
                connections.append(ScenarioConnection(chain=chain))
            continue

        if section == "layout":
            layout_rules.append(payload)

    return ScenarioSpec(
        title=title or "Untitled Scenario",
        scenario=scenario,
        resources=resources,
        connections=connections,
        layout_rules=layout_rules,
    )


_KIND_TO_TYPE = {
    "vnet": "microsoft.network/virtualnetworks",
    "subnet": "microsoft.network/virtualnetworks/subnets",
    "azure firewall": "microsoft.network/azurefirewalls",
    "nsg": "microsoft.network/networksecuritygroups",
    "route table": "microsoft.network/routetables",
    "azure front door": "microsoft.cdn/profiles",
    "application gateway (waf)": "microsoft.network/applicationgateways",
    "app service plan": "microsoft.web/serverfarms",
    "web app": "microsoft.web/sites",
    "backend app service": "microsoft.web/sites",
    "azure function app": "microsoft.web/sites",
    "azure service bus": "microsoft.servicebus/namespaces",
    "sql server": "microsoft.sql/servers",
    "sql database": "microsoft.sql/servers/databases",
    "storage account": "microsoft.storage/storageaccounts",
    "azure key vault": "microsoft.keyvault/vaults",
    "private endpoint": "microsoft.network/privateendpoints",
    "log analytics workspace": "microsoft.operationalinsights/workspaces",
    "application insights": "microsoft.insights/components",
}


def _resolve_type(kind: str) -> str:
    normalized = _normalize_label(kind)
    for key, arm_type in _KIND_TO_TYPE.items():
        if normalized.startswith(key):
            return arm_type
    return "scenario/resource"


def _ensure_actor_node(label: str, node_map: Dict[str, Dict], alias_map: Dict[str, str]) -> str:
    key = _normalize_label(label)
    if key in alias_map:
        return alias_map[key]
    node_id = f"scenario://actor/{_slug(label)}"
    node = {
        "id": node_id,
        "name": label,
        "type": "scenario/actor",
        "resourceGroup": "scenario",
        "subscriptionId": "scenario",
        "location": "global",
        "properties": {},
    }
    node_map[node_id] = node
    alias_map[key] = node_id
    return node_id


def scenario_spec_to_graph(spec: ScenarioSpec) -> Dict[str, List[Dict]]:
    """Convert ScenarioSpec to graph-like payload for deterministic rendering."""
    nodes_by_id: Dict[str, Dict] = {}
    alias_map: Dict[str, str] = {}

    for item in spec.resources:
        node_id = f"scenario://{_slug(item.kind)}/{_slug(item.name)}"
        node = {
            "id": node_id,
            "name": item.name,
            "type": _resolve_type(item.kind),
            "resourceGroup": _slug(item.category),
            "subscriptionId": "scenario-subscription",
            "location": "australiaeast",
            "properties": {"details": item.details, "cidr": item.cidr},
            "tags": {"scenarioCategory": item.category},
        }
        nodes_by_id[node_id] = node

        alias_map[_normalize_label(item.name)] = node_id
        alias_map[_normalize_label(item.kind)] = node_id
        alias_map[_normalize_label(f"{item.kind} {item.name}")] = node_id

    edges: List[Dict] = []
    for conn in spec.connections:
        parts = conn.chain
        for i in range(len(parts) - 1):
            src_label = parts[i]
            tgt_label = parts[i + 1]

            src_id = alias_map.get(_normalize_label(src_label))
            if not src_id:
                src_id = _ensure_actor_node(src_label, nodes_by_id, alias_map)

            tgt_id = alias_map.get(_normalize_label(tgt_label))
            if not tgt_id:
                tgt_id = _ensure_actor_node(tgt_label, nodes_by_id, alias_map)

            edges.append(
                {
                    "source": src_id,
                    "target": tgt_id,
                    "kind": "scenario-flow",
                }
            )

    return {
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
        "layout_rules": spec.layout_rules,
        "title": spec.title,
        "scenario": spec.scenario,
    }


# ---------------------------------------------------------------------------
# Builtin templates
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES: Dict[str, str] = {
    "enterprise-multitier-web": """\
Enterprise Multi-Tier Web App Architecture

Scenario: enterprise multi-tier web app, single region, private data access.

Resources:
1. **Networking**
  - VNet: "vnet-enterprise-prod-aue-001" (10.10.0.0/16)
  - Subnets:
    - Subnet: "snet-gateway" (10.10.0.0/24)
    - Subnet: "snet-frontend" (10.10.1.0/24)
    - Subnet: "snet-app" (10.10.2.0/24)
    - Subnet: "snet-data" (10.10.3.0/24)
    - Subnet: "snet-management" (10.10.4.0/24)
  - Azure Firewall: "fw-enterprise-prod"
  - NSG: "nsg-frontend"
  - NSG: "nsg-app"
  - Route Table: "rt-enterprise-prod"
2. **Ingress**
  - Azure Front Door: "afd-enterprise-prod"
  - Application Gateway (WAF): "agw-enterprise-prod"
3. **Application**
  - App Service Plan: "asp-enterprise-prod"
  - Web App: "app-enterprise-web-prod"
  - Backend App Service: "app-enterprise-api-prod"
  - Azure Function App: "func-enterprise-worker-prod"
  - Azure Service Bus: "sb-enterprise-prod"
4. **Data**
  - SQL Server: "sql-enterprise-prod"
  - SQL Database: "sqldb-enterprise-app"
  - Storage Account: "stenterpriseprod"
  - Azure Key Vault: "kv-enterprise-prod"
  - Private Endpoint: "pe-sql-enterprise"
  - Private Endpoint: "pe-kv-enterprise"
5. **Observability**
  - Log Analytics Workspace: "law-enterprise-prod"
  - Application Insights: "appi-enterprise-prod"

Connections:
- User Browser -> Azure Front Door -> Application Gateway (WAF) -> Web App
- Web App -> Backend App Service -> SQL Database
- Backend App Service -> Azure Key Vault
- Backend App Service -> Storage Account
- Azure Function App -> Azure Service Bus
- Web App -> Application Insights
- Backend App Service -> Application Insights
- Application Insights -> Log Analytics Workspace

Layout rules:
- Left to right flow.
- Group by: Networking, Ingress, Application, Data, Observability.
- Place Observability at the bottom.
""",

    "vm-network-immediate": """\
VM Immediate Network Context

Scenario: single VM with its direct NIC, subnet, and VNet context.

Resources:
1. **Compute**
  - Virtual Machine: "vm-workload-prod-001"
  - Network Interface: "nic-vm-workload-prod-001"
2. **Networking**
  - Subnet: "snet-compute" (10.20.1.0/24)
  - VNet: "vnet-prod-aue-001" (10.20.0.0/16)
  - NSG: "nsg-compute"

Connections:
- vm-workload-prod-001 -> nic-vm-workload-prod-001 -> snet-compute -> vnet-prod-aue-001
- nsg-compute -> snet-compute

Layout rules:
- Left to right flow.
- Network scope: immediate VM chain only.
""",

    "vm-application-interactions": """\
VM Application Interaction Map

Scenario: VM interactions with application dependencies.

Resources:
1. **Compute**
  - Virtual Machine: "vm-app-prod-001"
  - Network Interface: "nic-vm-app-prod-001"
2. **Application**
  - Web App: "app-consumer-prod"
  - Azure Function App: "func-processor-prod"
  - Azure Service Bus: "sb-app-prod"
3. **Data**
  - Storage Account: "stapp001"
  - Azure Key Vault: "kv-app-prod"

Connections:
- vm-app-prod-001 -> app-consumer-prod
- vm-app-prod-001 -> Azure Service Bus
- Azure Service Bus -> func-processor-prod
- func-processor-prod -> Storage Account
- app-consumer-prod -> Azure Key Vault

Layout rules:
- Left to right flow.
- Diagram type: application interactions.
""",
}
