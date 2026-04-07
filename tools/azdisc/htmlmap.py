"""Offline HTML mindmap generator for Azure discovery artifacts."""
from __future__ import annotations

import html
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

from .config import Config
from .util import load_json_file, normalize_id

log = logging.getLogger(__name__)

ARTIFACT_CHOICES = (
    "graph",
    "related-candidates",
    "related-promoted",
    "rbac",
    "policy",
)

SUBSCRIPTION_FILL = "#f4d35e"
RESOURCE_GROUP_FILL = "#7fb3ff"
RESOURCE_FILL = "#8fd19e"
EXTERNAL_FILL = "#d9d9d9"
CONTEXT_FILL = "#c8d1ff"
PRINCIPAL_FILL = "#dbc8ff"
ASSIGNMENT_FILL = "#ffd39a"
POLICY_NONCOMPLIANT_FILL = "#f6b0aa"
POLICY_COMPLIANT_FILL = "#b7e4c7"
POLICY_EXEMPT_FILL = "#ffe08a"
POLICY_UNKNOWN_FILL = "#dfe6ee"

NODE_W = 240
NODE_H = 72
SUB_W = 280
SUB_H = 78
RG_W = 260
RG_H = 78
LEVEL_GAP = 170
SIBLING_GAP = 36
ROOT_GAP = 120
TOP_MARGIN = 70
LEFT_MARGIN = 80

NETWORK_EDGE_KINDS = {
    "vm->nic",
    "vm->disk",
    "nic->nsg",
    "nic->subnet",
    "nic->asg",
    "vnet->peeredVnet",
    "subnet->vnet",
    "subnet->nsg",
    "subnet->routeTable",
    "privateEndpoint->subnet",
    "privateEndpoint->target",
    "loadBalancer->backendNic",
    "publicIp->attachment",
    "webApp->subnet",
    "firewall->subnet",
    "firewall->publicIp",
    "bastion->subnet",
    "bastion->publicIp",
    "containerApp->environment",
    "containerEnv->subnet",
    "appGw->subnet",
}

NodeMap = Dict[str, Dict[str, Any]]
ViewModel = Dict[str, Any]


def classify_edge_kind(kind: str) -> str:
    """Classify an edge kind into a visual layer."""
    if kind in NETWORK_EDGE_KINDS:
        return "network"
    return "reference"


def _safe_key(value: str, fallback: str) -> str:
    return value.strip() or fallback


def _slug(value: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "-" for ch in value]
    slug = "".join(cleaned).strip("-")
    return slug or "item"


def _policy_fill(compliance_state: str) -> str:
    state = (compliance_state or "").strip().lower()
    if state == "noncompliant":
        return POLICY_NONCOMPLIANT_FILL
    if state == "compliant":
        return POLICY_COMPLIANT_FILL
    if state == "exempt":
        return POLICY_EXEMPT_FILL
    return POLICY_UNKNOWN_FILL


def _parse_arm_context(arm_id: str) -> Dict[str, str]:
    normalized = normalize_id(arm_id)
    if not normalized:
        return {
            "subscriptionId": "",
            "resourceGroup": "",
            "name": "unknown",
            "type": "unknown",
            "normalizedId": "",
        }

    parts = [part for part in normalized.split("/") if part]
    lower = [part.lower() for part in parts]
    subscription_id = ""
    resource_group = ""
    name = parts[-1] if parts else normalized
    resource_type = "scope"

    if "subscriptions" in lower:
        idx = lower.index("subscriptions")
        if idx + 1 < len(parts):
            subscription_id = parts[idx + 1]
    if "resourcegroups" in lower:
        idx = lower.index("resourcegroups")
        if idx + 1 < len(parts):
            resource_group = parts[idx + 1]
    if "providers" in lower:
        idx = lower.index("providers")
        if idx + 2 < len(parts):
            type_parts = [parts[idx + 1].lower()]
            for pos in range(idx + 2, len(parts), 2):
                type_parts.append(parts[pos].lower())
            resource_type = "/".join(type_parts)
    elif resource_group:
        resource_type = "resource-group-scope"
        name = resource_group
    elif subscription_id:
        resource_type = "subscription-scope"
        name = subscription_id

    return {
        "subscriptionId": subscription_id,
        "resourceGroup": resource_group,
        "name": name,
        "type": resource_type,
        "normalizedId": normalized,
    }


def _make_node(
    node_id: str,
    *,
    kind: str,
    name: str,
    type_name: str,
    fill: str,
    parent_id: str | None = None,
    width: int = NODE_W,
    height: int = NODE_H,
    attributes: Iterable[str] | None = None,
) -> Dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "name": name,
        "type": type_name,
        "fill": fill,
        "parentId": parent_id,
        "width": width,
        "height": height,
        "attributes": [attr for attr in (attributes or []) if attr],
    }


def _add_node(nodes_by_id: NodeMap, order: List[str], node: Dict[str, Any]) -> Dict[str, Any]:
    existing = nodes_by_id.get(node["id"])
    if existing is None:
        nodes_by_id[node["id"]] = node
        order.append(node["id"])
        return node
    if node.get("attributes"):
        seen = set(existing.get("attributes") or [])
        for attr in node["attributes"]:
            if attr not in seen:
                existing.setdefault("attributes", []).append(attr)
                seen.add(attr)
    return existing


def _ensure_subscription(nodes_by_id: NodeMap, order: List[str], subscription_id: str, *, label: str | None = None) -> str:
    sub_key = _safe_key(subscription_id, "external-unresolved")
    node_id = f"subscription::{sub_key}"
    _add_node(
        nodes_by_id,
        order,
        _make_node(
            node_id,
            kind="subscription",
            name=label or sub_key,
            type_name="Azure Subscription",
            fill=SUBSCRIPTION_FILL,
            width=SUB_W,
            height=SUB_H,
        ),
    )
    return node_id


def _ensure_group(
    nodes_by_id: NodeMap,
    order: List[str],
    parent_id: str,
    group_key: str,
    *,
    label: str,
    type_name: str = "Resource Group",
    fill: str = RESOURCE_GROUP_FILL,
) -> str:
    node_id = f"group::{parent_id}::{group_key}"
    _add_node(
        nodes_by_id,
        order,
        _make_node(
            node_id,
            kind="resourceGroup",
            name=label,
            type_name=type_name,
            fill=fill,
            parent_id=parent_id,
            width=RG_W,
            height=RG_H,
        ),
    )
    return node_id


def _add_resource_tree_node(
    nodes_by_id: NodeMap,
    order: List[str],
    *,
    subscription_id: str,
    resource_group: str,
    resource_id: str,
    name: str,
    type_name: str,
    fill: str,
    attributes: Iterable[str] | None = None,
    subscription_label: str | None = None,
) -> str:
    sub_node_id = _ensure_subscription(nodes_by_id, order, subscription_id, label=subscription_label)
    rg_label = resource_group or "Unassigned"
    rg_key = _slug(resource_group or "unassigned")
    rg_node_id = _ensure_group(nodes_by_id, order, sub_node_id, rg_key, label=rg_label)
    _add_node(
        nodes_by_id,
        order,
        _make_node(
            resource_id,
            kind="resource",
            name=name,
            type_name=type_name,
            fill=fill,
            parent_id=rg_node_id,
            attributes=attributes,
        ),
    )
    return resource_id


def _build_tree_view(nodes_by_id: NodeMap, order: List[str], overlay_edges: List[Dict[str, str]], title: str) -> ViewModel:
    nodes = [nodes_by_id[node_id] for node_id in order]
    hierarchy_edges = [
        {"source": node["parentId"], "target": node["id"], "category": "hierarchy"}
        for node in nodes
        if node.get("parentId")
    ]
    positions = compute_tree_layout(nodes)
    canvas = compute_canvas_bounds(positions, nodes_by_id)
    return {
        "title": title,
        "nodes": nodes,
        "hierarchyEdges": hierarchy_edges,
        "overlayEdges": overlay_edges,
        "positions": positions,
        "canvas": canvas,
    }


def compute_tree_layout(nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Compute a deterministic top-down tree layout for arbitrary hierarchy depth."""
    node_lookup = {node["id"]: node for node in nodes}
    children_by_parent: Dict[str, List[str]] = {}
    root_ids: List[str] = []

    for node in nodes:
        parent_id = node.get("parentId")
        if parent_id:
            children_by_parent.setdefault(parent_id, []).append(node["id"])
        else:
            root_ids.append(node["id"])

    def sort_key(node_id: str) -> tuple[str, str, str]:
        node = node_lookup[node_id]
        return (node.get("kind", ""), node.get("name", "").lower(), node_id)

    for child_ids in children_by_parent.values():
        child_ids.sort(key=sort_key)
    root_ids.sort(key=sort_key)

    width_cache: Dict[str, float] = {}

    def subtree_width(node_id: str) -> float:
        if node_id in width_cache:
            return width_cache[node_id]
        node = node_lookup[node_id]
        children = children_by_parent.get(node_id, [])
        if not children:
            width = float(node.get("width", NODE_W))
        else:
            total = sum(subtree_width(child_id) for child_id in children)
            total += max(0, len(children) - 1) * SIBLING_GAP
            width = max(float(node.get("width", NODE_W)), total)
        width_cache[node_id] = width
        return width

    positions: Dict[str, Dict[str, float]] = {}

    def place(node_id: str, start_x: float, depth: int) -> None:
        span = subtree_width(node_id)
        node = node_lookup[node_id]
        positions[node_id] = {
            "x": start_x + max(0.0, (span - float(node.get("width", NODE_W))) / 2),
            "y": TOP_MARGIN + depth * LEVEL_GAP,
        }
        cursor = start_x
        for child_id in children_by_parent.get(node_id, []):
            child_span = subtree_width(child_id)
            place(child_id, cursor, depth + 1)
            cursor += child_span + SIBLING_GAP

    current_x = LEFT_MARGIN
    for root_id in root_ids:
        root_span = subtree_width(root_id)
        place(root_id, current_x, 0)
        current_x += root_span + ROOT_GAP

    return positions


def compute_canvas_bounds(positions: Dict[str, Dict[str, float]], node_lookup: NodeMap) -> Dict[str, float]:
    if not positions:
        return {"width": 1200.0, "height": 800.0}

    max_right = 0.0
    max_bottom = 0.0
    for node_id, pos in positions.items():
        node = node_lookup[node_id]
        max_right = max(max_right, pos["x"] + float(node.get("width", NODE_W)))
        max_bottom = max(max_bottom, pos["y"] + float(node.get("height", NODE_H)))
    return {"width": max_right + 140.0, "height": max_bottom + 140.0}


def build_html_view_model(graph: Dict[str, Any]) -> ViewModel:
    """Build the graph.json HTML view model."""
    nodes_by_id: NodeMap = {}
    order: List[str] = []
    overlay_edges: List[Dict[str, str]] = []

    for resource in sorted(
        graph.get("nodes") or [],
        key=lambda node: (
            node.get("subscriptionId", ""),
            node.get("resourceGroup", ""),
            node.get("type", ""),
            node.get("name", ""),
        ),
    ):
        _add_resource_tree_node(
            nodes_by_id,
            order,
            subscription_id=(resource.get("subscriptionId") or "").strip(),
            resource_group=(resource.get("resourceGroup") or "").strip(),
            resource_id=resource["id"],
            name=resource.get("name") or resource.get("id", "").split("/")[-1] or "unnamed",
            type_name=resource.get("type") or "unknown",
            fill=EXTERNAL_FILL if resource.get("isExternal") else RESOURCE_FILL,
            attributes=resource.get("attributes") or [],
            subscription_label="External / Unresolved" if resource.get("isExternal") and not resource.get("subscriptionId") else None,
        )

    for edge in sorted(graph.get("edges") or [], key=lambda item: (item.get("source", ""), item.get("target", ""), item.get("kind", ""))):
        if edge.get("source") not in nodes_by_id or edge.get("target") not in nodes_by_id:
            continue
        overlay_edges.append(
            {
                "source": edge["source"],
                "target": edge["target"],
                "kind": edge.get("kind", "unknown"),
                "category": classify_edge_kind(edge.get("kind", "unknown")),
            }
        )

    return _build_tree_view(nodes_by_id, order, overlay_edges, "Azure resource mindmap")


def _build_related_view(rows: List[Dict[str, Any]], title: str) -> ViewModel:
    nodes_by_id: NodeMap = {}
    order: List[str] = []
    overlay_edges: List[Dict[str, str]] = []

    for row in sorted(rows, key=lambda item: (item.get("subscriptionId", ""), item.get("resourceGroup", ""), item.get("name", ""), item.get("id", ""))):
        matched = row.get("matchedSearchStrings") or []
        candidate_node_id = _add_resource_tree_node(
            nodes_by_id,
            order,
            subscription_id=(row.get("subscriptionId") or "").strip(),
            resource_group=(row.get("resourceGroup") or "").strip(),
            resource_id=row.get("id") or f"candidate::{_slug(row.get('name', 'unnamed'))}",
            name=row.get("name") or "unnamed",
            type_name=row.get("type") or "candidate",
            fill=RESOURCE_FILL,
            attributes=[
                f"matched: {', '.join(matched)}" if matched else "matched: none",
                *(evidence.get("explanation") or "" for evidence in row.get("discoveryEvidence") or [] if evidence.get("explanation")),
            ],
        )

        for evidence in row.get("discoveryEvidence") or []:
            for related in evidence.get("relatedResources") or []:
                related_id = related.get("id") or f"context::{candidate_node_id}::{_slug(related.get('name', 'context'))}"
                if related_id not in nodes_by_id:
                    _add_resource_tree_node(
                        nodes_by_id,
                        order,
                        subscription_id=(related.get("subscriptionId") or row.get("subscriptionId") or "").strip(),
                        resource_group=(related.get("resourceGroup") or row.get("resourceGroup") or "").strip(),
                        resource_id=related_id,
                        name=related.get("name") or related_id.split("/")[-1],
                        type_name=related.get("type") or "base-inventory-context",
                        fill=CONTEXT_FILL,
                        attributes=[f"matched terms: {related.get('matchedTerms', '')}"] if related.get("matchedTerms") else [],
                        subscription_label="External / Unresolved" if not (related.get("subscriptionId") or row.get("subscriptionId")) else None,
                    )
                overlay_edges.append(
                    {
                        "source": candidate_node_id,
                        "target": related_id,
                        "kind": "related-context",
                        "category": "reference",
                    }
                )

    return _build_tree_view(nodes_by_id, order, overlay_edges, title)


def _build_rbac_view(rows: List[Dict[str, Any]]) -> ViewModel:
    nodes_by_id: NodeMap = {}
    order: List[str] = []
    overlay_edges: List[Dict[str, str]] = []

    for index, row in enumerate(rows):
        props = row.get("properties") or {}
        scope = normalize_id(props.get("scope") or row.get("scope") or "")
        context = _parse_arm_context(scope)
        subscription_id = context["subscriptionId"]
        sub_node_id = _ensure_subscription(
            nodes_by_id,
            order,
            subscription_id,
            label="External / Unresolved" if not subscription_id else None,
        )

        scope_rg = context["resourceGroup"] or "scope-root"
        scope_group_id = _ensure_group(
            nodes_by_id,
            order,
            sub_node_id,
            _slug(scope_rg),
            label=context["resourceGroup"] or "Scope Root",
        )

        parent_id = scope_group_id
        subscription_scope = normalize_id(f"/subscriptions/{subscription_id}") if subscription_id else ""
        resource_group_scope = normalize_id(f"/subscriptions/{subscription_id}/resourceGroups/{context['resourceGroup']}") if subscription_id and context["resourceGroup"] else ""
        if scope and scope not in {subscription_scope, resource_group_scope}:
            scope_node_id = scope or f"scope::{index}"
            _add_node(
                nodes_by_id,
                order,
                _make_node(
                    scope_node_id,
                    kind="resource",
                    name=context["name"],
                    type_name=context["type"] or "scope",
                    fill=RESOURCE_FILL,
                    parent_id=scope_group_id,
                    attributes=[f"scope: {scope}"],
                ),
            )
            parent_id = scope_node_id

        role_name = props.get("roleDefinitionName") or row.get("roleDefinitionName") or row.get("name") or "Role Assignment"
        assignment_id = normalize_id(row.get("id") or f"{scope}/providers/microsoft.authorization/roleassignments/{index}") or f"rbac-assignment::{index}"
        _add_node(
            nodes_by_id,
            order,
            _make_node(
                assignment_id,
                kind="resource",
                name=str(role_name),
                type_name="Role Assignment",
                fill=ASSIGNMENT_FILL,
                parent_id=parent_id,
                attributes=[
                    f"principal type: {props.get('principalType', row.get('principalType', 'unknown'))}",
                    f"principal id: {props.get('principalId', row.get('principalId', ''))}",
                ],
            ),
        )

        principals_group_id = _ensure_group(
            nodes_by_id,
            order,
            sub_node_id,
            "principals",
            label="Principals",
            type_name="Principal Directory",
            fill="#d8d7ff",
        )
        principal_name = props.get("principalDisplayName") or row.get("principalDisplayName") or props.get("principalId") or row.get("principalId") or "unknown principal"
        principal_id = str(props.get("principalId") or row.get("principalId") or principal_name)
        principal_node_id = f"principal::{subscription_id or 'external'}::{_slug(principal_id)}"
        _add_node(
            nodes_by_id,
            order,
            _make_node(
                principal_node_id,
                kind="resource",
                name=str(principal_name),
                type_name=f"Principal: {props.get('principalType', row.get('principalType', 'unknown'))}",
                fill=PRINCIPAL_FILL,
                parent_id=principals_group_id,
                attributes=[
                    f"principal id: {principal_id}",
                    f"resolution: {props.get('principalResolutionStatus', 'unknown')}",
                ],
            ),
        )
        overlay_edges.append(
            {
                "source": assignment_id,
                "target": principal_node_id,
                "kind": "rbac-principal",
                "category": "reference",
            }
        )

    return _build_tree_view(nodes_by_id, order, overlay_edges, "Azure RBAC mindmap")


def _build_policy_view(rows: List[Dict[str, Any]]) -> ViewModel:
    nodes_by_id: NodeMap = {}
    order: List[str] = []
    overlay_edges: List[Dict[str, str]] = []

    for index, row in enumerate(sorted(rows, key=lambda item: (item.get("subscriptionId", ""), item.get("resourceGroup", ""), item.get("resourceId", ""), item.get("policyAssignmentName", ""), item.get("policyDefinitionName", "")))):
        resource_id = normalize_id(row.get("resourceId") or "")
        context = _parse_arm_context(resource_id)
        resource_node_id = _add_resource_tree_node(
            nodes_by_id,
            order,
            subscription_id=(row.get("subscriptionId") or context["subscriptionId"] or "").strip(),
            resource_group=(row.get("resourceGroup") or context["resourceGroup"] or "").strip(),
            resource_id=resource_id or f"policy-resource::{index}",
            name=context["name"] if resource_id else row.get("resourceId") or f"resource-{index}",
            type_name=row.get("resourceType") or context["type"] or "resource",
            fill=RESOURCE_FILL,
            attributes=[f"location: {row.get('resourceLocation', '')}" if row.get("resourceLocation") else ""],
            subscription_label="External / Unresolved" if not (row.get("subscriptionId") or context["subscriptionId"]) else None,
        )

        finding_name = row.get("policyAssignmentName") or row.get("policyDefinitionName") or f"policy-{index}"
        finding_type = f"Policy {row.get('complianceState') or 'Unknown'}"
        finding_id = normalize_id(row.get("id") or f"{resource_node_id}/policy/{index}") or f"policy::{index}"
        _add_node(
            nodes_by_id,
            order,
            _make_node(
                finding_id,
                kind="resource",
                name=str(finding_name),
                type_name=finding_type,
                fill=_policy_fill(row.get("complianceState") or ""),
                parent_id=resource_node_id,
                attributes=[
                    f"definition: {row.get('policyDefinitionName', '')}" if row.get("policyDefinitionName") else "",
                    f"assignment scope: {row.get('policyAssignmentScope', '')}" if row.get("policyAssignmentScope") else "",
                    f"timestamp: {row.get('timestamp', '')}" if row.get("timestamp") else "",
                ],
            ),
        )

    return _build_tree_view(nodes_by_id, order, overlay_edges, "Azure Policy mindmap")


def _artifact_spec(cfg: Config, artifact: str) -> Tuple[Path, str, type, Callable[[Any], ViewModel]]:
    if artifact == "graph":
        return cfg.out("graph.json"), "mindmap.html", dict, build_html_view_model
    if artifact == "related-candidates":
        return cfg.deep_out(cfg.deepDiscovery.candidateFile), "related_candidates.html", list, lambda rows: _build_related_view(rows, "Related candidates mindmap")
    if artifact == "related-promoted":
        return cfg.deep_out(cfg.deepDiscovery.promotedFile), "related_promoted.html", list, lambda rows: _build_related_view(rows, "Promoted related resources mindmap")
    if artifact == "rbac":
        return cfg.out("rbac.json"), "rbac.html", list, _build_rbac_view
    if artifact == "policy":
        return cfg.out("policy.json"), "policy.html", list, _build_policy_view
    raise ValueError(f"Unsupported HTML artifact: {artifact!r}")


def _json_for_script(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True).replace("</", "<\\/")


def _html_document(data: Dict[str, Any], title: str) -> str:
    doc = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>__TITLE__</title>
  <style>
    :root {
      --panel: rgba(255, 252, 243, 0.94);
      --ink: #1f2933;
      --assoc: #111111;
      --network: #2468d8;
      --reference: #7a3cff;
      --grid: rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: \"Segoe UI\", \"Helvetica Neue\", Arial, sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at top, #fffaf0 0%, #f1efe6 55%, #e6ebee 100%);
    }
    .toolbar {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 18px;
      align-items: center;
      padding: 14px 18px;
      background: var(--panel);
      backdrop-filter: blur(8px);
      border-bottom: 1px solid rgba(17, 24, 39, 0.12);
    }
    .toolbar h1 { margin: 0 14px 0 0; font-size: 18px; font-weight: 700; }
    .toolbar label { display: inline-flex; gap: 8px; align-items: center; font-size: 14px; }
    .toolbar button {
      border: 1px solid rgba(17, 24, 39, 0.2);
      background: white;
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
    }
    .toolbar .hint { margin-left: auto; font-size: 13px; color: #52606d; }
    .canvas-wrap { height: calc(100vh - 58px); overflow: hidden; }
    svg {
      width: 100%;
      height: 100%;
      display: block;
      background-image: linear-gradient(to right, var(--grid) 1px, transparent 1px), linear-gradient(to bottom, var(--grid) 1px, transparent 1px);
      background-size: 28px 28px;
      touch-action: none;
    }
    .node rect { rx: 18; ry: 18; stroke: rgba(17, 24, 39, 0.34); stroke-width: 1.2; }
    .node.subscription rect { stroke-width: 1.8; }
    .node.resourceGroup rect { stroke-width: 1.5; }
    .node text { pointer-events: none; user-select: none; }
    .node .name { font-size: 13px; font-weight: 700; fill: #13202f; }
    .node .meta { font-size: 11px; fill: #334e68; }
    .edge-hierarchy { stroke: var(--assoc); stroke-width: 2.1; fill: none; opacity: 0.72; }
    .edge-network { stroke: var(--network); stroke-width: 2.1; fill: none; stroke-dasharray: 8 7; opacity: 0.9; marker-end: url(#arrow-network); }
    .edge-reference { stroke: var(--reference); stroke-width: 2.1; fill: none; stroke-dasharray: 6 6; opacity: 0.82; marker-end: url(#arrow-reference); }
    .edge.hidden { display: none; }
  </style>
</head>
<body>
  <div class=\"toolbar\">
    <h1>__TITLE__</h1>
    <label><input id=\"toggle-network\" type=\"checkbox\"> Network</label>
    <label><input id=\"toggle-reference\" type=\"checkbox\"> References</label>
    <button id=\"reset-layout\" type=\"button\">Reset layout</button>
    <span class=\"hint\">Drag nodes, wheel to zoom, drag background to pan.</span>
  </div>
  <div class=\"canvas-wrap\">
    <svg id=\"mindmap\" viewBox=\"0 0 1600 900\" aria-label=\"Azure resource mindmap\">
      <defs>
        <marker id=\"arrow-network\" viewBox=\"0 0 10 10\" refX=\"8\" refY=\"5\" markerWidth=\"7\" markerHeight=\"7\" orient=\"auto-start-reverse\">
          <path d=\"M 0 0 L 10 5 L 0 10 z\" fill=\"#2468d8\"></path>
        </marker>
        <marker id=\"arrow-reference\" viewBox=\"0 0 10 10\" refX=\"8\" refY=\"5\" markerWidth=\"7\" markerHeight=\"7\" orient=\"auto-start-reverse\">
          <path d=\"M 0 0 L 10 5 L 0 10 z\" fill=\"#7a3cff\"></path>
        </marker>
      </defs>
      <g id=\"viewport\">
        <g id=\"edge-layer\"></g>
        <g id=\"node-layer\"></g>
      </g>
    </svg>
  </div>
  <script>
    const DATA = __DATA__;
    const svg = document.getElementById('mindmap');
    const viewport = document.getElementById('viewport');
    const edgeLayer = document.getElementById('edge-layer');
    const nodeLayer = document.getElementById('node-layer');
    const toggleNetwork = document.getElementById('toggle-network');
    const toggleReference = document.getElementById('toggle-reference');
    const resetButton = document.getElementById('reset-layout');

    const positions = JSON.parse(JSON.stringify(DATA.positions));
    const initialPositions = JSON.parse(JSON.stringify(DATA.positions));
    const nodeMap = new Map(DATA.nodes.map((node) => [node.id, node]));
    const hierarchyEntries = [];
    const overlayEntries = [];

    const viewState = { x: 0, y: 0, scale: 1 };
    let dragNode = null;
    let dragOffset = { x: 0, y: 0 };
    let panStart = null;

    function screenToWorld(clientX, clientY) {
      const pt = svg.createSVGPoint();
      pt.x = clientX;
      pt.y = clientY;
      return pt.matrixTransform(viewport.getScreenCTM().inverse());
    }

    function applyViewport() {
      viewport.setAttribute('transform', `translate(${viewState.x} ${viewState.y}) scale(${viewState.scale})`);
    }

    function centerOf(nodeId) {
      const node = nodeMap.get(nodeId);
      const pos = positions[nodeId];
      return { x: pos.x + node.width / 2, y: pos.y + node.height / 2 };
    }

    function edgePath(sourceId, targetId) {
      const a = centerOf(sourceId);
      const b = centerOf(targetId);
      return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
    }

    function truncate(text, maxLen) {
      return text.length <= maxLen ? text : `${text.slice(0, maxLen - 1)}…`;
    }

    function updateNodePosition(group) {
      const pos = positions[group.dataset.id];
      group.setAttribute('transform', `translate(${pos.x} ${pos.y})`);
    }

    function renderNode(node) {
      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.classList.add('node', node.kind);
      group.dataset.id = node.id;

      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('width', node.width);
      rect.setAttribute('height', node.height);
      rect.setAttribute('fill', node.fill);
      group.appendChild(rect);

      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      const attrText = (node.attributes || []).join(' | ');
      title.textContent = attrText ? `${node.name} (${node.type}) | ${attrText}` : `${node.name} (${node.type})`;
      group.appendChild(title);

      const name = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      name.setAttribute('x', 14);
      name.setAttribute('y', node.kind === 'resource' ? 28 : 33);
      name.setAttribute('class', 'name');
      name.textContent = truncate(node.name, node.kind === 'resource' ? 28 : 26);
      group.appendChild(name);

      const meta = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      meta.setAttribute('x', 14);
      meta.setAttribute('y', node.kind === 'resource' ? 49 : 54);
      meta.setAttribute('class', 'meta');
      meta.textContent = truncate(node.type, node.kind === 'resource' ? 34 : 24);
      group.appendChild(meta);

      updateNodePosition(group);

      group.addEventListener('pointerdown', (event) => {
        event.stopPropagation();
        const world = screenToWorld(event.clientX, event.clientY);
        dragNode = node.id;
        dragOffset = { x: world.x - positions[node.id].x, y: world.y - positions[node.id].y };
        group.setPointerCapture(event.pointerId);
      });

      group.addEventListener('pointermove', (event) => {
        if (dragNode !== node.id) return;
        const world = screenToWorld(event.clientX, event.clientY);
        positions[node.id] = { x: world.x - dragOffset.x, y: world.y - dragOffset.y };
        updateNodePosition(group);
        redrawEdges();
      });

      group.addEventListener('pointerup', (event) => {
        if (dragNode === node.id) {
          dragNode = null;
          group.releasePointerCapture(event.pointerId);
        }
      });

      group.addEventListener('pointercancel', () => {
        if (dragNode === node.id) dragNode = null;
      });

      nodeLayer.appendChild(group);
    }

    function renderEdge(edge, cssClass) {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', `edge ${cssClass}`);
      if (edge.kind) path.dataset.kind = edge.kind;
      path.dataset.category = edge.category;
      edgeLayer.appendChild(path);
      return { edge, path };
    }

    function redrawEdges() {
      hierarchyEntries.forEach((entry) => entry.path.setAttribute('d', edgePath(entry.edge.source, entry.edge.target)));
      overlayEntries.forEach((entry) => entry.path.setAttribute('d', edgePath(entry.edge.source, entry.edge.target)));
    }

    function syncEdgeVisibility() {
      overlayEntries.forEach((entry) => {
        const visible =
          (entry.edge.category === 'network' && toggleNetwork.checked) ||
          (entry.edge.category === 'reference' && toggleReference.checked);
        entry.path.classList.toggle('hidden', !visible);
      });
    }

    function resetLayout() {
      Object.keys(initialPositions).forEach((id) => {
        positions[id] = { x: initialPositions[id].x, y: initialPositions[id].y };
      });
      Array.from(nodeLayer.children).forEach(updateNodePosition);
      redrawEdges();
    }

    svg.addEventListener('wheel', (event) => {
      event.preventDefault();
      const scaleFactor = event.deltaY < 0 ? 1.08 : 0.92;
      viewState.scale = Math.max(0.35, Math.min(2.5, viewState.scale * scaleFactor));
      applyViewport();
    }, { passive: false });

    svg.addEventListener('pointerdown', (event) => {
      if (event.target !== svg) return;
      panStart = { x: event.clientX, y: event.clientY, vx: viewState.x, vy: viewState.y };
      svg.setPointerCapture(event.pointerId);
    });

    svg.addEventListener('pointermove', (event) => {
      if (!panStart || dragNode) return;
      const dx = event.clientX - panStart.x;
      const dy = event.clientY - panStart.y;
      viewState.x = panStart.vx + dx;
      viewState.y = panStart.vy + dy;
      applyViewport();
    });

    svg.addEventListener('pointerup', (event) => {
      panStart = null;
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    });

    toggleNetwork.addEventListener('change', syncEdgeVisibility);
    toggleReference.addEventListener('change', syncEdgeVisibility);
    resetButton.addEventListener('click', resetLayout);

    svg.setAttribute('viewBox', `0 0 ${DATA.canvas.width} ${DATA.canvas.height}`);
    DATA.hierarchyEdges.forEach((edge) => hierarchyEntries.push(renderEdge(edge, 'edge-hierarchy')));
    DATA.overlayEdges.forEach((edge) => overlayEntries.push(renderEdge(edge, edge.category === 'network' ? 'edge-network' : 'edge-reference')));
    DATA.nodes.forEach(renderNode);
    redrawEdges();
    syncEdgeVisibility();
    applyViewport();
  </script>
</body>
</html>
"""
    return doc.replace("__TITLE__", html.escape(title)).replace("__DATA__", _json_for_script(data))


def generate_html(cfg: Config, artifact: str = "graph") -> Path:
    """Generate a standalone offline HTML mindmap from the selected artifact."""
    artifact_path, output_name, expected_type, builder = _artifact_spec(cfg, artifact)
    if not artifact_path.exists():
        raise FileNotFoundError(f"{artifact_path.name} not found at {artifact_path}.")

    payload = load_json_file(
        artifact_path,
        context=f"HTML stage {artifact} artifact",
        expected_type=expected_type,
        advice=f"Fix {artifact_path.name} or rerun the producing stage.",
    )
    view_model = builder(payload)
    title = view_model.pop("title", f"{cfg.app} {artifact} mindmap")
    cfg.ensure_output_dir()
    output_path = Path(cfg.outputDir) / output_name
    full_title = title if title.lower().startswith(cfg.app.lower()) else f"{cfg.app} {title}"
    output_path.write_text(_html_document(view_model, full_title))
    log.info("Wrote offline HTML mindmap for artifact=%s: %s", artifact, output_path)
    return output_path
