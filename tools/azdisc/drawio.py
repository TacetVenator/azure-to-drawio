"""Draw.io diagram generator."""
from __future__ import annotations

import base64
import json
import math
import logging
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Config, VALID_DIAGRAM_MODES, VALID_LAYOUTS
from .util import load_json_file, normalize_id, stable_id

log = logging.getLogger(__name__)


def _spacing_factor(spacing: str) -> float:
    """Return the gap/padding multiplier for a named spacing preset."""
    return {"compact": 1.0, "spacious": 1.8}.get(spacing, 1.0)


# Grid layout constants
CELL_W = 120
CELL_H = 80
H_GAP = 20
V_GAP = 20
COLS_PER_ROW = 6
RG_PADDING = 40
TYPE_V_GAP = 30
REGION_PADDING = 60

# VNET>SUBNET layout constants
VNET_PADDING = 50
VNET_HEADER = 40
SUBNET_PADDING = 30
SUBNET_HEADER = 30
SUBNET_H_GAP = 30
VNET_H_GAP = 60
UNATTACHED_PADDING = 40
VNET_REGION_PADDING = 20   # Padding around VNets inside a region container
VNET_REGION_HEADER = 30    # Height of region container title bar

# MSFT mode layout constants
MSFT_CELL_W = 110
MSFT_CELL_H = 70
MSFT_X_STEP = 140
MSFT_Y_STEP = 95
MSFT_COLS = 6
MSFT_RG_PAD = 20
MSFT_RG_HEADER = 35
MSFT_TYPE_HEADER_H = 22
MSFT_RG_V_GAP = 30
MSFT_REGION_PAD = 40
MSFT_REGION_HEADER = 35

# Default style strings
EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;exitX=0.5;exitY=1;exitDx=0;exitDy=0;"
GROUP_STYLE = "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];shape=mxgraph.azure.groups.subscription;labelPosition=top;verticalLabelPosition=top;align=center;verticalAlign=bottom;fillColor=#dae8fc;strokeColor=#6c8ebf;fontColor=#000000;"
RG_STYLE = "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];shape=mxgraph.azure.groups.resource_group;labelPosition=top;verticalLabelPosition=top;align=center;verticalAlign=bottom;fillColor=#fff2cc;strokeColor=#d6b656;fontColor=#000000;"
UNKNOWN_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#9E9E9E;fontColor=#333333;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
EXTERNAL_STYLE = "ellipse;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
EXTERNAL_ICON_OVERRIDES = "dashed=1;strokeColor=#b85450;fontColor=#b85450;labelBackgroundColor=#f8cecc;"
UDR_CALLOUT_STYLE = "shape=callout;fillColor=#fff2cc;strokeColor=#d6b656;align=left;verticalAlign=top;spacingLeft=5;fontSize=10;"
NSG_CALLOUT_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;align=left;verticalAlign=top;spacingLeft=5;spacingTop=4;fontSize=10;"
MSFT_NSG_PANEL_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff0f0;strokeColor=#b85450;fontColor=#7A1A1A;dashed=1;"

# Style for a small subnet icon decoration inside a container
SUBNET_ICON_DECORATION_STYLE = "sketch=0;aspect=fixed;html=1;align=center;fontSize=1;pointerEvents=0;shape=image;image=img/lib/azure2/networking/Subnet.svg;"
ATTR_BOX_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;fontSize=10;"
VNET_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontColor=#2D6A2D;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;fontSize=13;fontStyle=1;arcSize=6;opacity=70;"
SUBNET_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#fce4ec;strokeColor=#c2185b;fontColor=#880E4F;verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;fontSize=11;dashed=1;dashPattern=5 5;arcSize=8;opacity=70;"
UNATTACHED_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#999999;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;fontSize=13;fontStyle=1;arcSize=6;dashed=1;dashPattern=8 4;"
VNET_REGION_CONTAINER_STYLE = (
    "shape=rectangle;dashed=1;dashPattern=8 4;fillColor=none;strokeColor=#0078D4;"
    "strokeWidth=2;rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;align=left;"
    "spacingLeft=10;spacingTop=5;fontSize=13;fontStyle=1;fontColor=#0078D4;arcSize=4;"
)

# MSFT mode styles
MSFT_REGION_STYLE = "shape=rectangle;dashed=1;dashPattern=6 4;fillColor=#F0F7FF;strokeColor=#0078D4;fontColor=#0078D4;rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;spacingTop=5;fontSize=12;fontStyle=1;"
MSFT_RG_STYLE = "rounded=1;fillColor=#F5F5F5;strokeColor=#BDBDBD;fontColor=#333333;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;spacingTop=5;"
MSFT_NODE_STYLE_EXTRA = "whiteSpace=wrap;html=1;align=center;verticalAlign=top;"
MSFT_UDR_PANEL_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF9C4;strokeColor=#F9A825;fontColor=#5D4037;"
MSFT_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"

# Edge kinds classified by semantic type for visual differentiation
_ASSOCIATION_EDGE_KINDS = {
    "subnet->nsg", "subnet->routeTable", "nic->nsg", "nic->asg",
    "nsgRule->sourceAsg", "nsgRule->destAsg",
    "rbac_assignment", "appInsights->workspace", "udr_detail", "nsg_detail",
    "activityLog->access",
}
_PEERING_EDGE_KINDS = {
    "vnet->peeredVnet",
}
# All other edge kinds default to traffic/attachment style

# Differentiated edge styles (all lines are at least 2pt wide)
EDGE_STYLE_TRAFFIC = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;exitX=0.5;exitY=1;exitDx=0;exitDy=0;strokeColor=#333333;strokeWidth=2;endArrow=block;endFill=1;"
EDGE_STYLE_ASSOCIATION = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;dashed=1;dashPattern=5 5;strokeColor=#999999;strokeWidth=2;endArrow=none;"
EDGE_STYLE_PEERING = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;strokeColor=#0078D4;strokeWidth=2;endArrow=block;endFill=1;"
MSFT_EDGE_STYLE_TRAFFIC = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#333333;strokeWidth=2;endArrow=block;endFill=1;"
MSFT_EDGE_STYLE_ASSOCIATION = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;dashed=1;dashPattern=5 5;strokeColor=#999999;strokeWidth=2;endArrow=none;"
MSFT_EDGE_STYLE_PEERING = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#0078D4;strokeWidth=2;endArrow=block;endFill=1;"
EDGE_STYLE_TELEMETRY_DEPENDENCY = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
    "strokeColor=#AA00AA;strokeWidth=1;dashed=1;dashPattern=8 3;"
    "endArrow=open;endFill=0;"
)
EDGE_STYLE_TELEMETRY_FLOW = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
    "strokeColor=#FF6600;strokeWidth=1;dashed=1;dashPattern=4 4;"
    "endArrow=open;endFill=0;"
)
MSFT_EDGE_STYLE_TELEMETRY_DEPENDENCY = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;"
    "strokeColor=#AA00AA;strokeWidth=1;dashed=1;dashPattern=8 3;"
    "endArrow=open;endFill=0;"
)
MSFT_EDGE_STYLE_TELEMETRY_FLOW = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;"
    "strokeColor=#FF6600;strokeWidth=1;dashed=1;dashPattern=4 4;"
    "endArrow=open;endFill=0;"
)
MSFT_TYPE_HEADER_STYLE = "text;html=1;align=left;verticalAlign=top;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=11;fontStyle=1;fontColor=#333333;"

# ---------------------------------------------------------------------------
# L2R mode styles and constants
# ---------------------------------------------------------------------------

# L2R layout dimensions
L2R_CELL_W = 110
L2R_CELL_H = 70
L2R_X_STEP = 140
L2R_Y_STEP = 95
L2R_RESOURCE_COLS = 4
L2R_NETWORK_COLS = 3
L2R_SECTION_GAP = 50
L2R_SECTION_HEADER_H = 20
L2R_RG_PAD = 20
L2R_RG_HEADER = 30
L2R_RG_V_GAP = 20
L2R_REGION_PAD = 25
L2R_REGION_HEADER = 30
L2R_REGION_V_GAP = 20
L2R_SUB_PAD = 15
L2R_SUB_HEADER = 30

# L2R container styles — all with explicit colors (no "default") to avoid theme clashes
L2R_SUB_STYLE = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],"
    "[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];"
    "shape=mxgraph.azure.groups.subscription;labelPosition=top;verticalLabelPosition=top;"
    "align=center;verticalAlign=bottom;fillColor=#EBF3FB;strokeColor=#1565C0;fontColor=#0D47A1;"
)
L2R_REGION_STYLE = (
    "shape=rectangle;dashed=1;dashPattern=6 4;fillColor=#F8F9FA;strokeColor=#0078D4;"
    "strokeWidth=1;rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;align=left;"
    "spacingLeft=10;spacingTop=5;fontSize=11;fontStyle=1;fontColor=#0078D4;arcSize=3;"
)
L2R_RG_STYLE = (
    "rounded=1;fillColor=#FFFDE7;strokeColor=#E65100;fontColor=#BF360C;"
    "whiteSpace=wrap;html=1;verticalAlign=top;align=left;"
    "spacingLeft=8;spacingTop=5;fontSize=11;fontStyle=1;"
)
L2R_CONTEXT_BOX_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF8E1;strokeColor=#F9A825;"
    "align=left;verticalAlign=top;spacingLeft=10;spacingTop=8;fontSize=11;"
    "fontColor=#4E342E;strokeWidth=2;"
)
L2R_SECTION_HEADER_RESOURCE_STYLE = (
    "text;html=1;align=left;verticalAlign=top;fontSize=9;fontStyle=1;"
    "fontColor=#424242;strokeColor=none;fillColor=none;"
)
L2R_SECTION_HEADER_NETWORK_STYLE = (
    "text;html=1;align=left;verticalAlign=top;fontSize=9;fontStyle=1;"
    "fontColor=#1B5E20;strokeColor=none;fillColor=none;"
)
# Edge style for L2R mode — minimal, clean arrows with no labels
L2R_EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
    "strokeColor=#546E7A;strokeWidth=1.5;endArrow=block;endFill=1;"
)

# Network types shown on the right (network section) in L2R mode
_L2R_NETWORK_TYPES = {
    "microsoft.network/virtualnetworks",
    "microsoft.network/virtualnetworks/subnets",
    "microsoft.network/networksecuritygroups",
    "microsoft.network/applicationsecuritygroups",
    "microsoft.network/routetables",
    "microsoft.network/azurefirewalls",
    "microsoft.network/bastionhosts",
    "microsoft.network/applicationgateways",
    "microsoft.network/loadbalancers",
    "microsoft.network/publicipaddresses",
    "microsoft.network/privateendpoints",
    "microsoft.network/networkinterfaces",
    "microsoft.network/natgateways",
    "microsoft.network/firewallpolicies",
    "microsoft.network/virtualnetworkgateways",
    "microsoft.network/localnetworkgateways",
    "microsoft.network/connections",
    "microsoft.network/expressroutecircuits",
}

# Edges drawn in L2R mode — only resource→network attachment edges + boundaries
_L2R_DRAW_EDGE_KINDS = {
    "vm->nic",
    "webApp->subnet",
    "containerEnv->subnet",
    "privateEndpoint->subnet",
    "appGw->subnet",
    "firewall->subnet",
    "bastion->subnet",
    "internet->publicIp",
    "onPrem->gateway",
    "appInsights->dependency",
    "flowLog->flow",
}

# Network detail compact mode — resource types hidden from the diagram and
# summarised in a per-resource annotation box instead.
_COMPACT_HIDDEN_TYPES = {
    "microsoft.network/networkinterfaces",
    "microsoft.network/virtualnetworks/subnets",
    "microsoft.network/networksecuritygroups",
    "microsoft.network/applicationsecuritygroups",
    "microsoft.network/routetables",
    "microsoft.compute/disks",
}
NET_CONTEXT_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;"
    "align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;fontSize=10;"
)
NET_CONTEXT_EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
    "strokeColor=#6c8ebf;dashed=1;strokeWidth=1;"
)


def _edge_style(kind: str, msft: bool = False) -> str:
    """Return the appropriate edge style based on edge kind and rendering mode."""
    if kind in _ASSOCIATION_EDGE_KINDS:
        return MSFT_EDGE_STYLE_ASSOCIATION if msft else EDGE_STYLE_ASSOCIATION
    if kind in _PEERING_EDGE_KINDS:
        return MSFT_EDGE_STYLE_PEERING if msft else EDGE_STYLE_PEERING
    if kind == "appInsights->dependency":
        return MSFT_EDGE_STYLE_TELEMETRY_DEPENDENCY if msft else EDGE_STYLE_TELEMETRY_DEPENDENCY
    if kind == "flowLog->flow":
        return MSFT_EDGE_STYLE_TELEMETRY_FLOW if msft else EDGE_STYLE_TELEMETRY_FLOW
    return MSFT_EDGE_STYLE_TRAFFIC if msft else EDGE_STYLE_TRAFFIC

def _validate_render_surface(cfg: Config) -> None:
    if cfg.layout not in VALID_LAYOUTS:
        raise ValueError(f"Unsupported layout for drawio generation: {cfg.layout!r}")
    if cfg.diagramMode not in VALID_DIAGRAM_MODES:
        raise ValueError(f"Unsupported diagramMode for drawio generation: {cfg.diagramMode!r}")


def _collect_node_degrees(edges: List[Dict]) -> Dict[str, int]:
    degrees: Dict[str, int] = defaultdict(int)
    for edge in edges:
        degrees[normalize_id(edge["source"])] += 1
        degrees[normalize_id(edge["target"])] += 1
    return degrees


def _sorted_group_nodes(nodes: List[Dict], degree_map: Dict[str, int], layout_magic: bool) -> List[Dict]:
    if not layout_magic:
        return sorted(nodes, key=lambda n: (n.get("name", "").lower(), n["id"].lower()))
    return sorted(
        nodes,
        key=lambda n: (-degree_map.get(n["id"], 0), n.get("name", "").lower(), n["id"].lower()),
    )


def _group_cols(node_count: int, default_cols: int, layout_magic: bool) -> int:
    if node_count <= 0:
        return 1
    if not layout_magic:
        return min(default_cols, node_count)
    return max(1, min(default_cols, math.ceil(math.sqrt(node_count))))


def _node_tags(node: Dict) -> Dict[str, str]:
    tags = node.get("tags") or {}
    return {str(k).strip().lower(): str(v).strip() for k, v in tags.items() if str(v).strip()}


def _display_tag_items(node: Dict) -> List[Tuple[str, str]]:
    tags = node.get("tags") or {}
    items: List[Tuple[str, str]] = []
    if not isinstance(tags, dict):
        return items
    for key, value in tags.items():
        tag_key = str(key).strip()
        tag_value = "" if value is None else str(value).strip()
        if tag_key and tag_value:
            items.append((tag_key, tag_value))
    items.sort(key=lambda item: (item[0].lower(), item[1].lower()))
    return items


def _resource_metadata_lines(node: Dict) -> List[str]:
    lines = list(node.get("attributes", []) or [])
    for key, value in _display_tag_items(node):
        lines.append(f"Tag: {key}={value}")
    return lines


def _diagram_inventory_lines(nodes: List[Dict], visible_node_ids: set[str]) -> List[str]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    rendered_count = 0
    for node in nodes:
        node_id = node.get("id")
        if not node_id or node_id not in visible_node_ids:
            continue
        node_type = (node.get("type") or "").lower()
        if node_type.startswith("__boundary__"):
            continue
        grouped[node_type or "unknown"].append(node.get("displayName") or node.get("name") or node_id)
        rendered_count += 1
    if not grouped:
        return []
    lines = ["Diagram Inventory", "──────────────────────", f"Resources shown: {rendered_count}"]
    for node_type in sorted(grouped.keys()):
        lines.append("")
        lines.append(node_type)
        for name in sorted(dict.fromkeys(grouped[node_type]), key=lambda value: value.lower()):
            lines.append(f"  {name}")
    return lines


def _emit_text_panel(
    root: ET.Element,
    panel_id: str,
    lines: List[str],
    *,
    x: int,
    y: int,
    width: int,
    style: str,
) -> int:
    label = "\n".join(lines)
    height = max(60, 16 * len(lines) + 24)
    cell = ET.SubElement(root, "mxCell")
    cell.set("id", panel_id)
    cell.set("value", label)
    cell.set("style", style)
    cell.set("vertex", "1")
    cell.set("parent", LAYER_LABELS)
    geo = ET.SubElement(cell, "mxGeometry")
    geo.set("x", str(x))
    geo.set("y", str(y))
    geo.set("width", str(width))
    geo.set("height", str(height))
    geo.set("as", "geometry")
    return height


def _emit_resource_metadata_boxes(
    root: ET.Element,
    nodes: List[Dict],
    node_id_map: Dict[str, str],
    positions: Dict[str, Tuple[int, int, int, int]],
    node_parents: Dict[str, str],
    container_positions: Dict[str, Tuple[int, int]],
) -> None:
    attr_edge_style = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        "strokeColor=#9673a6;dashed=1;strokeWidth=2;"
    )
    for node in nodes:
        nid = node.get("id")
        if not nid or nid not in positions:
            continue
        lines = _resource_metadata_lines(node)
        if not lines:
            continue
        sid = node_id_map.get(nid)
        if not sid:
            continue
        x, y, _w, _h = positions[nid]
        parent_id = node_parents.get(nid, LAYER_RESOURCES)
        abs_x, abs_y = _absolute_child_position(x, y, parent_id, container_positions)
        box_w = 220
        box_h = max(40, 12 + 16 * len(lines))
        box_x = abs_x - box_w - 10
        box_y = abs_y

        attr_id = "attr_" + stable_id(nid)
        ab = ET.SubElement(root, "mxCell")
        ab.set("id", attr_id)
        ab.set("value", "\n".join(lines))
        ab.set("style", ATTR_BOX_STYLE)
        ab.set("vertex", "1")
        ab.set("parent", LAYER_LABELS)
        abg = ET.SubElement(ab, "mxGeometry")
        abg.set("x", str(box_x))
        abg.set("y", str(box_y))
        abg.set("width", str(box_w))
        abg.set("height", str(box_h))
        abg.set("as", "geometry")

        ae = ET.SubElement(root, "mxCell")
        ae.set("id", "attr_edge_" + stable_id(nid))
        ae.set("value", "")
        ae.set("style", attr_edge_style)
        ae.set("edge", "1")
        ae.set("source", attr_id)
        ae.set("target", sid)
        ae.set("parent", LAYER_ASSOC_EDGES)
        aeg = ET.SubElement(ae, "mxGeometry")
        aeg.set("relative", "1")
        aeg.set("as", "geometry")


def _tag_group_label(node: Dict, group_by_tag: List[str]) -> str:
    if not group_by_tag:
        return ""
    tags = _node_tags(node)
    requested = [tag.strip() for tag in group_by_tag if tag and tag.strip()]
    any_requested = any(tag.lower() == "any" for tag in requested)
    candidates = requested
    if any_requested:
        candidates = ["Application", "App", "Service", "Workload", "System", "Product"]
    for candidate in candidates:
        value = tags.get(candidate.lower())
        if value:
            return f"{candidate}: {value}"
    return "Untagged"


def _resource_sections(
    type_groups: List[Tuple[str, List[Dict]]],
    group_by_tag: List[str],
    degree_map: Dict[str, int],
    layout_magic: bool,
) -> List[Dict[str, Any]]:
    if not group_by_tag:
        return [{
            "label": None,
            "type_groups": [
                (rtype, _sorted_group_nodes(type_nodes, degree_map, layout_magic))
                for rtype, type_nodes in type_groups
            ],
        }]

    grouped: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    for rtype, type_nodes in type_groups:
        for node in type_nodes:
            grouped[_tag_group_label(node, group_by_tag)][rtype].append(node)

    sections: List[Dict[str, Any]] = []
    for label in sorted(grouped.keys(), key=lambda v: (v == "Untagged", v.lower())):
        section_type_groups = []
        for rtype in sorted(grouped[label].keys(), key=lambda t: (_type_category(t).lower(), t.lower())):
            section_type_groups.append((rtype, _sorted_group_nodes(grouped[label][rtype], degree_map, layout_magic)))
        sections.append({"label": label, "type_groups": section_type_groups})
    return sections


def _container_absolute_positions(containers: List[Dict]) -> Dict[str, Tuple[int, int]]:
    by_id = {c["id"]: c for c in containers}
    absolute: Dict[str, Tuple[int, int]] = {}

    def visit(container_id: str) -> Tuple[int, int]:
        if container_id in absolute:
            return absolute[container_id]
        cont = by_id[container_id]
        parent = cont.get("parent", "1")
        if parent in by_id:
            px, py = visit(parent)
        else:
            px, py = 0, 0
        absolute[container_id] = (cont["x"] + px, cont["y"] + py)
        return absolute[container_id]

    for cont in containers:
        visit(cont["id"])
    return absolute


def _absolute_child_position(
    x: int, y: int, parent_id: str, container_positions: Dict[str, Tuple[int, int]],
) -> Tuple[int, int]:
    if parent_id in container_positions:
        px, py = container_positions[parent_id]
        return x + px, y + py
    return x, y


def _hub_role_map(nodes: List[Dict], edges: List[Dict]) -> Dict[str, str]:
    hub_ids = _detect_hub_vnet_ids(nodes, edges)
    roles: Dict[str, str] = {hub_id: "Hub" for hub_id in hub_ids}
    for edge in edges:
        if edge["kind"] != "vnet->peeredVnet":
            continue
        src = normalize_id(edge["source"])
        tgt = normalize_id(edge["target"])
        if src in hub_ids and tgt not in hub_ids:
            roles.setdefault(tgt, "Spoke")
        if tgt in hub_ids and src not in hub_ids:
            roles.setdefault(src, "Spoke")
    return roles


def _network_legend_text() -> str:
    return "\n".join([
        "Network Legend",
        "──────────────────────",
        "Black arrow: direct flow or attachment",
        "Blue arrow: peering or network path",
        "Gray dashed line: association or policy binding",
        "Magenta dashed arrow: telemetry dependency",
        "Orange dashed arrow: telemetry flow",
        "Red dashed resource: unresolved or out-of-scope dependency",
    ])


def _emit_legend_box(root: ET.Element, box_id: str, x: int, y: int) -> Tuple[int, int]:
    label = _network_legend_text()
    width = 280
    height = max(90, 18 * (label.count("\n") + 1) + 18)
    cell = ET.SubElement(root, "mxCell")
    cell.set("id", box_id)
    cell.set("value", label)
    cell.set("style", L2R_CONTEXT_BOX_STYLE)
    cell.set("vertex", "1")
    cell.set("parent", LAYER_LABELS)
    geo = ET.SubElement(cell, "mxGeometry")
    geo.set("x", str(x))
    geo.set("y", str(y))
    geo.set("width", str(width))
    geo.set("height", str(height))
    geo.set("as", "geometry")
    return width, height


def _nic_ip_context_lines(nodes: List[Dict]) -> List[str]:
    node_by_id = {n["id"]: n for n in nodes}
    lines: List[str] = []
    nics = sorted(
        [n for n in nodes if n.get("type", "").lower() == "microsoft.network/networkinterfaces"],
        key=lambda n: (n.get("name", "").lower(), n["id"].lower()),
    )
    if not nics:
        return lines
    lines.append("Interfaces:")
    for nic in nics:
        addresses: List[str] = []
        for ip_config in nic.get("properties", {}).get("ipConfigurations") or []:
            props = ip_config.get("properties", {})
            private_ip = props.get("privateIPAddress")
            if private_ip:
                addresses.append(private_ip)
            public_ref = ((props.get("publicIPAddress") or {}).get("id"))
            if public_ref:
                pip = node_by_id.get(normalize_id(public_ref))
                public_ip = (pip or {}).get("properties", {}).get("ipAddress")
                if public_ip:
                    addresses.append(public_ip)
        label = ", ".join(dict.fromkeys(addresses)) if addresses else "N/A"
        lines.append(f"  {nic.get('name', nic['id'])}: {label}")
    return lines


# ---------------------------------------------------------------------------
# Edge label helpers
# ---------------------------------------------------------------------------

_EDGE_LABELS: Dict[str, str] = {
    "internet->publicIp":             "HTTPS",
    "onPrem->gateway":                "VPN / ExpressRoute",
    "vnet->peeredVnet":               "VNet Peering",
    "privateEndpoint->targetService": "Private Link",
    "privateEndpoint->subnet":        "subnet",
    "nic->subnet":                    "subnet",
    "nic->nsg":                       "NSG",
    "nic->asg":                       "ASG",
    "subnet->nsg":                    "NSG",
    "subnet->vnet":                   "VNet",
    "vm->nic":                        "NIC",
    "vm->disk":                       "disk",
    "vmss->nic":                      "NIC",
    "appGw->subnet":                  "subnet",
    "firewall->subnet":               "subnet",
    "bastion->subnet":                "subnet",
    "webApp->subnet":                 "VNet Integration",
    "containerEnv->subnet":           "subnet",
    "loadBalancer->backendPool":      "backend",
    "appInsights->workspace":         "Log Analytics",
    "appInsights->dependency":        "telemetry",
    "flowLog->flow":                  "flow log",
    "flowLog->traffic":               "traffic",
    "activityLog->access":            "activity",
    "rbac_assignment":                "RBAC",
}


def _edge_label(kind: str) -> str:
    """Return a human-readable label for an edge kind, or empty string if none defined."""
    return _EDGE_LABELS.get(kind, "")


# Boundary node styles (Internet, On-Premises)
BOUNDARY_INTERNET_STYLE = "shape=mxgraph.azure.cloud;fillColor=#0078D4;strokeColor=#005A9E;fontColor=#FFFFFF;verticalLabelPosition=bottom;verticalAlign=top;align=center;whiteSpace=wrap;html=1;"
BOUNDARY_ONPREM_STYLE = "shape=mxgraph.azure.enterprise;fillColor=#7D7D7D;strokeColor=#555555;fontColor=#333333;verticalLabelPosition=bottom;verticalAlign=top;align=center;whiteSpace=wrap;html=1;"

# Sentinel IDs for boundary nodes
_BOUNDARY_INTERNET_ID = "__boundary__/internet"
_BOUNDARY_ONPREM_ID = "__boundary__/on-premises"

_VPN_ER_TYPES = {
    "microsoft.network/virtualnetworkgateways",
    "microsoft.network/localnetworkgateways",
    "microsoft.network/connections",
    "microsoft.network/expressroutecircuits",
}


def _inject_boundary_nodes(
    nodes: List[Dict], edges: List[Dict],
) -> Tuple[List[Dict], List[Dict]]:
    """Add Internet and/or On-Premises boundary nodes and edges if applicable.

    - Internet node: added when any Public IP exists.
    - On-Premises node: added when any VPN/ER gateway or local network gateway exists.

    Returns new copies of nodes and edges with boundary entries appended.
    """
    has_pip = any(n["type"] == "microsoft.network/publicipaddresses" for n in nodes)
    has_vpn_er = any(n["type"] in _VPN_ER_TYPES for n in nodes)

    if not has_pip and not has_vpn_er:
        return nodes, edges

    new_nodes = list(nodes)
    new_edges = list(edges)

    if has_pip:
        new_nodes.append({
            "id": _BOUNDARY_INTERNET_ID,
            "stableId": stable_id(_BOUNDARY_INTERNET_ID),
            "name": "Internet",
            "type": "__boundary__/internet",
            "location": "",
            "resourceGroup": "",
            "subscriptionId": "",
            "properties": {},
            "isExternal": False,
            "childResources": [],
            "attributes": [],
        })
        # Connect each public IP to the Internet node
        for n in nodes:
            if n["type"] == "microsoft.network/publicipaddresses":
                new_edges.append({
                    "source": _BOUNDARY_INTERNET_ID,
                    "target": n["id"],
                    "kind": "internet->publicIp",
                })

    if has_vpn_er:
        new_nodes.append({
            "id": _BOUNDARY_ONPREM_ID,
            "stableId": stable_id(_BOUNDARY_ONPREM_ID),
            "name": "On-Premises",
            "type": "__boundary__/on-premises",
            "location": "",
            "resourceGroup": "",
            "subscriptionId": "",
            "properties": {},
            "isExternal": False,
            "childResources": [],
            "attributes": [],
        })
        # Connect VPN/ER gateways to On-Premises node
        for n in nodes:
            if n["type"] in _VPN_ER_TYPES:
                new_edges.append({
                    "source": _BOUNDARY_ONPREM_ID,
                    "target": n["id"],
                    "kind": "onPrem->gateway",
                })

    return new_nodes, new_edges


def _get(obj: Any, *keys) -> Any:
    for k in keys:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
    return obj


def _load_icon_map(assets_dir: Path) -> Dict[str, str]:
    icon_map_path = assets_dir / "azure_icon_map.json"
    if icon_map_path.exists():
        return load_json_file(
            icon_map_path,
            context="Azure icon map",
            expected_type=dict,
            advice="Repair assets/azure_icon_map.json.",
        )
    return {}


def _normalize_name(s: str) -> str:
    """Lowercase and strip all non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _load_msft_icon_index(assets_dir: Path) -> Dict[str, Path]:
    """Build a normalized keyword→path index from the Microsoft Azure icon set.

    Scans assets/microsoft-azure-icons/ recursively for *.svg files.
    Returns an empty dict if the directory does not exist.

    Microsoft icon filenames follow the pattern:
        {number}-icon-service-{Service-Name}.svg

    The index maps lowercased alphanumeric keys extracted from the service name
    to their SVG path, enabling fuzzy lookup from ARM resource type strings.
    """
    icons_dir = assets_dir / "microsoft-azure-icons"
    if not icons_dir.exists():
        return {}
    index: Dict[str, Path] = {}
    for svg in sorted(icons_dir.rglob("*.svg")):
        stem = svg.stem
        # Strip leading numeric prefix
        clean = re.sub(r"^\d+-", "", stem)
        # Strip "icon-service-" or "icon-" prefix
        clean = re.sub(r"^icon-(service-)?", "", clean, flags=re.IGNORECASE)
        # Full normalized key (e.g. "azurefunctions")
        full_key = _normalize_name(clean)
        if full_key and full_key not in index:
            index[full_key] = svg
        # Individual word tokens of ≥3 chars as secondary keys (first match wins)
        for tok in re.split(r"[-_\s]+", clean):
            tok_key = _normalize_name(tok)
            if len(tok_key) >= 3 and tok_key not in index:
                index[tok_key] = svg
    return index


def _match_msft_icon(arm_type: str, index: Dict[str, Path]) -> Optional[Path]:
    """Find the best matching SVG from the Microsoft icon index for an ARM type.

    Tries progressively looser matches against the normalized index keys:
    1. Full normalized resource-type part (e.g. "storageaccounts")
    2. Resource part with common suffixes stripped (e.g. "storage")
    3. Normalized provider name (e.g. "documentdb")
    """
    if not index:
        return None
    cleaned = arm_type.lower().replace("microsoft.", "")
    parts = cleaned.split("/")
    provider = _normalize_name(parts[0]) if parts else ""
    resource = _normalize_name(parts[-1]) if len(parts) > 1 else ""

    candidates: List[str] = []
    if resource:
        candidates.append(resource)
        for suffix in ("accounts", "services", "namespaces", "servers",
                       "hubs", "vaults", "profiles", "workspaces", "clusters",
                       "registries", "gateways", "policies", "zones"):
            if resource != suffix and resource.endswith(suffix):
                candidates.append(resource[: -len(suffix)])
    if provider:
        candidates.append(provider)

    for c in candidates:
        if c in index:
            return index[c]
    return None


def _msft_svg_style(svg_path: Path) -> str:
    """Generate a draw.io image cell style with the SVG embedded as a base64 data URI."""
    b64 = base64.b64encode(svg_path.read_bytes()).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{b64}"
    return (
        f"sketch=0;aspect=fixed;html=1;align=center;fontSize=12;"
        f"pointerEvents=1;shape=image;image={data_uri};"
        f"verticalLabelPosition=bottom;verticalAlign=top;"
    )


def _rebuild_fallback_library(assets_dir: Path, msft_icons: Dict[str, Path]) -> None:
    """Write assets/azure-fallback.mxlibrary with icons from the Microsoft icon set.

    The mxlibrary format is a JSON array that draw.io can import via
    Extras > Edit Diagram or drag-and-drop. Each entry contains the XML
    for one icon cell plus its display metadata.
    """
    if not msft_icons:
        return
    seen: set = set()
    entries = []
    for svg_path in sorted({str(p): p for p in msft_icons.values()}.values(),
                           key=lambda p: p.name):
        canonical = str(svg_path.resolve())
        if canonical in seen:
            continue
        seen.add(canonical)
        style = _msft_svg_style(svg_path)
        title = svg_path.stem
        title = re.sub(r"^\d+-", "", title)
        title = re.sub(r"^icon-(service-)?", "", title, flags=re.IGNORECASE)
        title = title.replace("-", " ")
        cell_xml = (
            f'<mxCell style="{style}" vertex="1" parent="1">'
            f'<mxGeometry width="60" height="60" as="geometry"/></mxCell>'
        )
        entries.append({"xml": cell_xml, "w": 60, "h": 60,
                        "aspect": "fixed", "title": title})
    lib_path = assets_dir / "azure-fallback.mxlibrary"
    lib_path.write_text(json.dumps(entries, indent=2))
    log.info("Wrote %s (%d icons)", lib_path, len(entries))


def _externalize_style(style: str) -> str:
    if not style:
        return EXTERNAL_STYLE
    if style.endswith(";"):
        return style + EXTERNAL_ICON_OVERRIDES
    return style + ";" + EXTERNAL_ICON_OVERRIDES


def _node_style(node: Dict, icon_map: Dict[str, str],
                msft_icons: Optional[Dict[str, Path]] = None) -> str:
    t = node.get("type", "")
    # Boundary nodes have special styles
    if t == "__boundary__/internet":
        return BOUNDARY_INTERNET_STYLE
    if t == "__boundary__/on-premises":
        return BOUNDARY_ONPREM_STYLE
    style = icon_map.get(t)
    if not style:
        # Try partial match on type suffix
        parts = t.split("/")
        if len(parts) >= 2:
            style = icon_map.get(parts[-1])
    if not style and msft_icons is not None:
        svg_path = _match_msft_icon(t, msft_icons)
        if svg_path is not None:
            style = _msft_svg_style(svg_path)

    if node.get("isExternal"):
        if style:
            return _externalize_style(style)
        return EXTERNAL_STYLE
    return style or UNKNOWN_STYLE


def _make_cell(parent, cell_id: str, label: str, style: str,
               x: int, y: int, w: int, h: int, vertex: bool = True,
               edge_source: str = "", edge_target: str = "") -> ET.Element:
    cell = ET.SubElement(parent, "mxCell")
    cell.set("id", cell_id)
    cell.set("value", label)
    cell.set("style", style)
    cell.set("parent", parent.get("id", "1"))
    if vertex:
        cell.set("vertex", "1")
        geo = ET.SubElement(cell, "mxGeometry")
        geo.set("x", str(x))
        geo.set("y", str(y))
        geo.set("width", str(w))
        geo.set("height", str(h))
        geo.set("as", "geometry")
    return cell


def layout_nodes(
    nodes: List[Dict], spacing: float = 1.0,
) -> Tuple[Dict[str, Tuple[int, int, int, int]], List[Dict]]:
    """Compute deterministic (x, y, w, h) positions.

    Hierarchy: REGION > RG > TYPE band.
    Regions are arranged left to right; RGs within each region also go left to
    right.  Returns (positions, containers) where containers are flat region and
    RG bounding boxes (all parent="1", BANDS style).

    The *spacing* multiplier scales gaps and padding (≥1.0 = more whitespace).
    Cell sizes (CELL_W, CELL_H) are unchanged.
    """
    s = lambda v: round(v * spacing)
    h_gap = s(H_GAP)
    v_gap = s(V_GAP)
    rg_padding = s(RG_PADDING)
    type_v_gap = s(TYPE_V_GAP)
    region_padding = s(REGION_PADDING)

    # Separate boundary nodes
    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]

    # Group by (region, rg, type)
    groups: Dict[Tuple[str, str, str], List[Dict]] = defaultdict(list)
    for n in regular_nodes:
        key = (n.get("location", ""), n.get("resourceGroup", ""), n.get("type", ""))
        groups[key].append(n)

    for key in groups:
        groups[key].sort(key=lambda n: (n.get("name", ""), n["id"]))

    # Organize by region -> rg
    region_rg: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))
    for key in sorted(groups.keys()):
        region, rg, _ = key
        region_rg[region][rg].append(key)

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []

    # Regions go LEFT TO RIGHT
    region_cursor_x = region_padding

    for region in sorted(region_rg.keys()):
        rg_x = region_cursor_x + region_padding  # absolute x of the first RG
        rg_max_height = 0
        rg_containers_for_region: List[Dict] = []

        for rg in sorted(region_rg[region].keys()):
            type_keys = region_rg[region][rg]
            type_y = rg_padding
            rg_content_w = 0

            for key in sorted(type_keys):
                nodes_in_band = groups[key]
                rows = (len(nodes_in_band) + COLS_PER_ROW - 1) // COLS_PER_ROW
                band_w = min(len(nodes_in_band), COLS_PER_ROW) * (CELL_W + h_gap) - h_gap
                for i, node in enumerate(nodes_in_band):
                    col = i % COLS_PER_ROW
                    row = i // COLS_PER_ROW
                    nx = rg_x + rg_padding + col * (CELL_W + h_gap)
                    ny = region_padding + type_y + row * (CELL_H + v_gap)
                    positions[node["id"]] = (nx, ny, CELL_W, CELL_H)
                type_y += rows * (CELL_H + v_gap) + type_v_gap
                rg_content_w = max(rg_content_w, band_w)

            rg_h = type_y + rg_padding
            rg_w = rg_content_w + 2 * rg_padding
            rg_max_height = max(rg_max_height, rg_h)

            rg_containers_for_region.append({
                "id": "rg_" + stable_id(region + "/" + rg),
                "label": rg,
                "style": BANDS_RG_STYLE,
                "x": rg_x,
                "y": region_padding,
                "w": rg_w,
                "h": rg_h,
                "parent": "1",
            })
            rg_x += rg_w + h_gap

        # Region container wraps all its RGs
        region_right = rg_x - h_gap + region_padding
        region_w = region_right - region_cursor_x
        region_h = rg_max_height + 2 * region_padding

        containers.append({
            "id": "region_" + stable_id(region),
            "label": region,
            "style": BANDS_REGION_STYLE,
            "x": region_cursor_x,
            "y": 0,
            "w": region_w,
            "h": region_h,
            "parent": "1",
        })
        containers.extend(rg_containers_for_region)

        region_cursor_x = region_right + region_padding  # next region's left edge

    # Position boundary nodes at top-left, shifting everything else down
    if boundary_nodes:
        shift = CELL_H + 40 + region_padding
        for nid in list(positions.keys()):
            x, y, w, h = positions[nid]
            positions[nid] = (x, y + shift, w, h)
        for c in containers:
            c["y"] += shift
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (region_padding + i * (CELL_W + 40), region_padding, CELL_W, CELL_H)

    return positions, containers


# ---------------------------------------------------------------------------
# VNET>SUBNET layout
# ---------------------------------------------------------------------------


def _build_network_membership(
    nodes: List[Dict], edges: List[Dict],
) -> Tuple[
    Dict[str, List[str]],   # vnet_id -> [subnet_ids]
    Dict[str, List[str]],   # subnet_id -> [node_ids placed in this subnet]
    List[str],               # unattached node ids
]:
    """Derive VNet/subnet membership from edge relationships.

    Uses subnet->vnet, nic->subnet, privateEndpoint->subnet, webApp->subnet,
    and vm->nic edges to place every resource into a subnet where possible.
    """
    node_by_id: Dict[str, Dict] = {normalize_id(n["id"]): n for n in nodes}

    # 1. Map subnets to their parent VNet
    vnet_subnets: Dict[str, List[str]] = defaultdict(list)
    subnet_vnet: Dict[str, str] = {}
    for e in edges:
        if e["kind"] == "subnet->vnet":
            sid = normalize_id(e["source"])
            vid = normalize_id(e["target"])
            if sid not in subnet_vnet:
                subnet_vnet[sid] = vid
                vnet_subnets[vid].append(sid)

    # Also handle subnets whose VNet is derivable from their ARM id
    for n in nodes:
        if n["type"] == "microsoft.network/virtualnetworks/subnets":
            nid = n["id"]
            if nid not in subnet_vnet and "/subnets/" in nid:
                vid = nid.split("/subnets/")[0]
                subnet_vnet[nid] = vid
                vnet_subnets[vid].append(nid)

    # Sort subnet lists deterministically
    for vid in vnet_subnets:
        vnet_subnets[vid].sort()

    # 2. Map NICs to their subnet
    nic_subnet: Dict[str, str] = {}
    for e in edges:
        if e["kind"] == "nic->subnet":
            nic_subnet[normalize_id(e["source"])] = normalize_id(e["target"])

    # 3. Map resources to their subnet
    subnet_members: Dict[str, List[str]] = defaultdict(list)
    placed: set = set()

    # Subnet nodes themselves belong to their VNet (not placed inside subnet boxes)
    subnet_ids = set(subnet_vnet.keys())
    vnet_ids = set(vnet_subnets.keys())

    # Place VMs via vm->nic->subnet chain
    for e in edges:
        if e["kind"] == "vm->nic":
            vm_id = normalize_id(e["source"])
            nic_id = normalize_id(e["target"])
            if nic_id in nic_subnet:
                sid = nic_subnet[nic_id]
                if vm_id not in placed:
                    subnet_members[sid].append(vm_id)
                    placed.add(vm_id)
                # Also place the NIC in the same subnet
                if nic_id not in placed:
                    subnet_members[sid].append(nic_id)
                    placed.add(nic_id)

    # Place NICs that weren't placed via VM
    for nic_id, sid in nic_subnet.items():
        if nic_id not in placed:
            subnet_members[sid].append(nic_id)
            placed.add(nic_id)

    # Place private endpoints
    for e in edges:
        if e["kind"] == "privateEndpoint->subnet":
            pe_id = normalize_id(e["source"])
            sid = normalize_id(e["target"])
            if pe_id not in placed:
                subnet_members[sid].append(pe_id)
                placed.add(pe_id)

    # Place web apps
    for e in edges:
        if e["kind"] == "webApp->subnet":
            wa_id = normalize_id(e["source"])
            sid = normalize_id(e["target"])
            if wa_id not in placed:
                subnet_members[sid].append(wa_id)
                placed.add(wa_id)

    # Place NSGs into their subnet (subnet->nsg)
    for e in edges:
        if e["kind"] == "subnet->nsg":
            nsg_id = normalize_id(e["target"])
            sid = normalize_id(e["source"])
            if nsg_id not in placed:
                subnet_members[sid].append(nsg_id)
                placed.add(nsg_id)

    # Place route tables into their subnet (subnet->routeTable)
    for e in edges:
        if e["kind"] == "subnet->routeTable":
            rt_id = normalize_id(e["target"])
            sid = normalize_id(e["source"])
            if rt_id not in placed:
                subnet_members[sid].append(rt_id)
                placed.add(rt_id)

    # Place ASGs into the subnet of their member NICs (nic->asg)
    for e in edges:
        if e["kind"] == "nic->asg":
            asg_id = normalize_id(e["target"])
            nic_id = normalize_id(e["source"])
            if asg_id not in placed and nic_id in nic_subnet:
                sid = nic_subnet[nic_id]
                subnet_members[sid].append(asg_id)
                placed.add(asg_id)

    # Place load balancers near their backend NICs
    for e in edges:
        if e["kind"] == "loadBalancer->backendNic":
            lb_id = normalize_id(e["source"])
            nic_id = normalize_id(e["target"])
            if lb_id not in placed and nic_id in nic_subnet:
                sid = nic_subnet[nic_id]
                subnet_members[sid].append(lb_id)
                placed.add(lb_id)

    # Place public IPs near their attachment
    for e in edges:
        if e["kind"] == "publicIp->attachment":
            pip_id = normalize_id(e["source"])
            nic_id = normalize_id(e["target"])
            if pip_id not in placed and nic_id in nic_subnet:
                sid = nic_subnet[nic_id]
                subnet_members[sid].append(pip_id)
                placed.add(pip_id)

    # Place privateEndpoint targets (e.g. SQL servers) near their PE's subnet
    for e in edges:
        if e["kind"] == "privateEndpoint->target":
            target_id = normalize_id(e["target"])
            pe_id = normalize_id(e["source"])
            if target_id not in placed:
                # find which subnet the PE is in
                for e2 in edges:
                    if e2["kind"] == "privateEndpoint->subnet" and normalize_id(e2["source"]) == pe_id:
                        sid = normalize_id(e2["target"])
                        subnet_members[sid].append(target_id)
                        placed.add(target_id)
                        break

    # Place resources that connect directly to a subnet (firewall, bastion, appGw, containerEnv)
    _direct_subnet_kinds = {
        "firewall->subnet", "bastion->subnet",
        "appGw->subnet", "containerEnv->subnet",
    }
    for e in edges:
        if e["kind"] in _direct_subnet_kinds:
            res_id = normalize_id(e["source"])
            sid = normalize_id(e["target"])
            if res_id not in placed:
                subnet_members[sid].append(res_id)
                placed.add(res_id)

    # Sort members deterministically
    for sid in subnet_members:
        subnet_members[sid].sort()

    # Prune vnet_subnets to only subnets that have at least one placed resource.
    # This prevents subnets from shared/hub VNets that don't serve any in-scope
    # resource from appearing as empty containers in the diagram.
    _referenced_subnets: set = set(subnet_members.keys())
    for vid in list(vnet_subnets.keys()):
        vnet_subnets[vid] = [sid for sid in vnet_subnets[vid] if sid in _referenced_subnets]
    vnet_subnets = {vid: sids for vid, sids in vnet_subnets.items() if sids}

    # Collect unattached nodes (not a VNet, not a subnet, not placed)
    unattached = []
    for n in nodes:
        nid = n["id"]
        if nid not in placed and nid not in subnet_ids and nid not in vnet_ids:
            unattached.append(nid)
    unattached.sort()

    return dict(vnet_subnets), dict(subnet_members), unattached


def _grid_layout(
    node_ids: List[str], start_x: int, start_y: int, cols: int = COLS_PER_ROW,
    spacing: float = 1.0,
) -> Tuple[Dict[str, Tuple[int, int, int, int]], int, int]:
    """Lay out a list of node IDs in a grid, returning positions and content size."""
    s = lambda v: round(v * spacing)
    h_gap = s(H_GAP)
    v_gap = s(V_GAP)
    positions: Dict[str, Tuple[int, int, int, int]] = {}
    if not node_ids:
        return positions, 0, 0
    rows = (len(node_ids) + cols - 1) // cols
    for i, nid in enumerate(node_ids):
        col = i % cols
        row = i // cols
        x = start_x + col * (CELL_W + h_gap)
        y = start_y + row * (CELL_H + v_gap)
        positions[nid] = (x, y, CELL_W, CELL_H)
    content_w = min(len(node_ids), cols) * (CELL_W + h_gap) - h_gap
    content_h = rows * (CELL_H + v_gap) - v_gap
    return positions, content_w, content_h


# ---------------------------------------------------------------------------
# Subnet tier color helpers
# ---------------------------------------------------------------------------

# (keyword_fragments, fillColor, strokeColor) — first match wins
_SUBNET_TIER_COLORS: List[Tuple[List[str], str, str]] = [
    (["fw", "firewall", "nva", "palo", "dmz"],                    "#FFEBEE", "#C62828"),
    (["gw", "gateway", "vpn", "er", "expressroute"],               "#F3E5F5", "#6A1B9A"),
    (["bastion", "jump", "paw"],                                   "#E0F7FA", "#00695C"),
    (["web", "front", "wfe", "ui", "ingress"],                     "#E3F2FD", "#1565C0"),
    (["app", "back", "api", "mid", "svc", "service", "worker"],    "#E8F5E9", "#2E7D32"),
    (["data", "db", "sql", "storage", "cache", "redis", "cosmos"], "#FFF3E0", "#E65100"),
    (["pe", "endpoint", "private"],                                "#FFF8E1", "#F57F17"),
    (["mgmt", "management", "ops", "admin", "infra", "shared",
      "core"],                                                     "#EDE7F6", "#4527A0"),
]

_SUBNET_TIER_BASE = (
    "rounded=1;whiteSpace=wrap;html=1;"
    "verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;"
    "fontSize=11;dashed=1;dashPattern=5 5;arcSize=8;opacity=70;"
)

HUB_VNET_FILL = "#E8E8E8"
HUB_VNET_STROKE = "#5D5D5D"
SPOKE_VNET_FILL = "#F5F5F5"
SPOKE_VNET_STROKE = "#9E9E9E"


def _subnet_tier_style(subnet_name: str) -> Optional[str]:
    """Return a draw.io style for a subnet based on name patterns, or None for the default."""
    name = subnet_name.lower()
    for keywords, fill, stroke in _SUBNET_TIER_COLORS:
        if any(kw in name for kw in keywords):
            return (
                f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                "fontColor=#1A1A1A;verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;"
                "fontSize=11;dashed=1;dashPattern=5 5;arcSize=8;opacity=70;"
            )
    return None


def _hub_vnet_style() -> str:
    return (
        f"rounded=1;whiteSpace=wrap;html=1;fillColor={HUB_VNET_FILL};strokeColor={HUB_VNET_STROKE};"
        "fontColor=#1A1A1A;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;"
        "fontSize=13;fontStyle=1;arcSize=6;opacity=70;"
    )


def _spoke_vnet_style() -> str:
    return (
        f"rounded=1;whiteSpace=wrap;html=1;fillColor={SPOKE_VNET_FILL};strokeColor={SPOKE_VNET_STROKE};"
        "fontColor=#1A1A1A;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;"
        "fontSize=13;fontStyle=1;arcSize=6;opacity=70;"
    )


# ---------------------------------------------------------------------------
# Hub VNet detection
# ---------------------------------------------------------------------------

_HUB_RESOURCE_TYPES = {
    "microsoft.network/azurefirewalls",
    "microsoft.network/virtualnetworkgateways",
    "microsoft.network/expressroutecircuits",
}
_HUB_NAME_PATTERNS = ["hub", "transit", "shared-net", "shared-network", "core-net", "connectivity"]
_HUB_PLACEMENT_EDGE_KINDS = {"firewall->subnet", "bastion->subnet", "appGw->subnet"}


def _detect_hub_vnet_ids(nodes: List[Dict], edges: List[Dict]) -> set:
    """Detect hub VNet IDs by presence of firewall/gateway resources or name patterns."""
    # Build subnet -> VNet mapping
    subnet_vnet: Dict[str, str] = {}
    for e in edges:
        if e["kind"] == "subnet->vnet":
            subnet_vnet[normalize_id(e["source"])] = normalize_id(e["target"])
    for n in nodes:
        if n.get("type", "") == "microsoft.network/virtualnetworks/subnets" and "/subnets/" in n["id"]:
            nid = n["id"]
            if nid not in subnet_vnet:
                subnet_vnet[nid] = nid.split("/subnets/")[0]

    # Build resource -> subnet mapping from placement edges
    resource_subnet: Dict[str, str] = {}
    for e in edges:
        if e["kind"] in _HUB_PLACEMENT_EDGE_KINDS:
            resource_subnet[normalize_id(e["source"])] = normalize_id(e["target"])

    hub_vnet_ids: set = set()

    # Hub by presence of firewall/gateway resource type inside a VNet
    for n in nodes:
        if n.get("type", "").lower() in _HUB_RESOURCE_TYPES:
            nid = normalize_id(n["id"])
            sub_id = resource_subnet.get(nid)
            if sub_id and sub_id in subnet_vnet:
                hub_vnet_ids.add(subnet_vnet[sub_id])
            # Also check ARM id: resource lives inside a subnet which lives inside a VNet
            for sn_id, vnet_id in subnet_vnet.items():
                if nid.startswith(sn_id + "/"):
                    hub_vnet_ids.add(vnet_id)

    # Hub by VNet name pattern
    for n in nodes:
        if n.get("type", "").lower() == "microsoft.network/virtualnetworks":
            name = n.get("name", "").lower()
            if any(p in name for p in _HUB_NAME_PATTERNS):
                hub_vnet_ids.add(n["id"])

    return hub_vnet_ids


def layout_nodes_vnet(
    nodes: List[Dict], edges: List[Dict], spacing: float = 1.0,
    subnet_colors: bool = False, hub_vnet_ids: Optional[set] = None,
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],    # node absolute positions
    List[Dict],                                # container rects (mixed abs/relative coords)
]:
    """Compute positions for the VNET>SUBNET layout mode.

    The *spacing* multiplier scales gaps and padding (≥1.0 = more whitespace).

    Groups VNets by Azure region, producing three levels of containers:
      Region container (absolute)  →  VNet container (relative to region)
        →  Subnet container (relative to VNet)

    Member node positions are absolute (parent layer handles placement).

    Returns:
      positions: node_id -> (x, y, w, h)  — absolute canvas coordinates
      containers: list of dicts with keys: id, label, style, x, y, w, h, parent
    """
    s = lambda v: round(v * spacing)
    vnet_padding = s(VNET_PADDING)
    vnet_header = s(VNET_HEADER)
    subnet_padding = s(SUBNET_PADDING)
    subnet_header = s(SUBNET_HEADER)
    subnet_h_gap = s(SUBNET_H_GAP)
    vnet_h_gap = s(VNET_H_GAP)
    region_padding = s(REGION_PADDING)
    unattached_padding = s(UNATTACHED_PADDING)
    vnet_region_padding = s(VNET_REGION_PADDING)
    vnet_region_header = s(VNET_REGION_HEADER)

    # Separate boundary nodes
    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]

    node_by_id: Dict[str, Dict] = {n["id"]: n for n in regular_nodes}
    vnet_subnets, subnet_members, unattached = _build_network_membership(regular_nodes, edges)
    # Remove boundary nodes from unattached
    boundary_ids = {bn["id"] for bn in boundary_nodes}
    unattached = [uid for uid in unattached if uid not in boundary_ids]

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []

    if hub_vnet_ids is None:
        hub_vnet_ids = set()

    # Group VNets by region for hierarchical layout
    all_vnets = sorted(vnet_subnets.keys())
    regions_to_vnets: Dict[str, List[str]] = defaultdict(list)
    for vnet_id in all_vnets:
        node = node_by_id.get(vnet_id)
        region_name = (node.get("location", "unknown") if node else "unknown")
        regions_to_vnets[region_name].append(vnet_id)
    for r in regions_to_vnets:
        # Hubs first, then non-hubs — each group sorted alphabetically
        regions_to_vnets[r].sort(key=lambda v: (0 if v in hub_vnet_ids else 1, v))

    # Regions are arranged left to right; region_cursor_x tracks the next region's left edge
    region_cursor_x = region_padding

    for region_name in sorted(regions_to_vnets.keys()):
        region_vnets = regions_to_vnets[region_name]
        region_container_id = "vnet_region_" + stable_id(region_name)

        # Absolute position of the region container
        r_abs_x = region_cursor_x
        r_abs_y = region_padding

        # VNets are laid out horizontally within the region.
        # Positions of VNets are RELATIVE to the region container.
        vnet_rel_cursor_x = vnet_region_padding   # relative X inside region, advances rightward
        vnet_rel_y = vnet_region_header + vnet_region_padding   # fixed relative Y for all VNets

        # Absolute Y baseline for VNet interiors (for computing member absolute coords)
        abs_vnet_y_base = r_abs_y + vnet_rel_y

        vnet_max_height = 0

        for vnet_id in region_vnets:
            subnet_ids = vnet_subnets.get(vnet_id, [])
            vnet_label = node_by_id[vnet_id]["name"] if vnet_id in node_by_id else vnet_id.split("/")[-1]
            vnet_container_id = "vnet_" + stable_id(vnet_id)

            # VNet position is RELATIVE to its region container
            vnet_in_region_x = vnet_rel_cursor_x
            vnet_in_region_y = vnet_rel_y

            # Absolute top-left of VNet box (used for computing member/subnet absolute coords)
            abs_vnet_x = r_abs_x + vnet_in_region_x
            abs_vnet_y = abs_vnet_y_base  # = r_abs_y + vnet_rel_y

            # Absolute start for the first subnet inside this VNet
            abs_inner_y = abs_vnet_y + vnet_header  # below VNet title bar
            subnet_cursor_abs_x = abs_vnet_x + vnet_padding  # first subnet starts here (absolute)

            vnet_content_h = 0

            for subnet_id in subnet_ids:
                members = subnet_members.get(subnet_id, [])
                subnet_label = (node_by_id[subnet_id]["name"] if subnet_id in node_by_id
                                else subnet_id.split("/")[-1])
                subnet_container_id = "subnet_" + stable_id(subnet_id)

                # Member node absolute positions (members are parented to the resource layer)
                inner_member_x = subnet_cursor_abs_x + subnet_padding
                inner_member_y = abs_inner_y + subnet_header
                cols = max(2, min(COLS_PER_ROW, len(members))) if members else 2
                member_pos, content_w, content_h = _grid_layout(
                    members, inner_member_x, inner_member_y, cols, spacing=spacing)
                positions.update(member_pos)

                # Subnet box dimensions
                subnet_w = max(content_w, CELL_W) + 2 * subnet_padding
                subnet_h = max(content_h, CELL_H // 2) + subnet_header + subnet_padding

                # Subnet position is RELATIVE to its VNet container
                subnet_rel_x = subnet_cursor_abs_x - abs_vnet_x  # = vnet_padding + prior_subnet_widths
                subnet_rel_y = vnet_header                         # starts right below VNet title

                sn_style = (
                    (_subnet_tier_style(subnet_label) or SUBNET_STYLE)
                    if subnet_colors else SUBNET_STYLE
                )
                containers.append({
                    "id": subnet_container_id,
                    "label": subnet_label,
                    "style": sn_style,
                    "x": subnet_rel_x,
                    "y": subnet_rel_y,
                    "w": subnet_w,
                    "h": subnet_h,
                    "parent": vnet_container_id,
                })

                vnet_content_h = max(vnet_content_h, subnet_h)
                subnet_cursor_abs_x += subnet_w + subnet_h_gap

            # VNet box dimensions
            if subnet_ids:
                vnet_w = (subnet_cursor_abs_x - subnet_h_gap) - abs_vnet_x + vnet_padding
            else:
                vnet_w = 200
            vnet_w = max(vnet_w, 200)
            vnet_h = vnet_content_h + vnet_header + 2 * vnet_padding

            # VNet position is RELATIVE to its region container
            if subnet_colors:
                is_hub = vnet_id in hub_vnet_ids
                vnet_style = _hub_vnet_style() if is_hub else _spoke_vnet_style()
            else:
                vnet_style = VNET_STYLE
            containers.append({
                "id": vnet_container_id,
                "label": vnet_label,
                "style": vnet_style,
                "x": vnet_in_region_x,
                "y": vnet_in_region_y,
                "w": vnet_w,
                "h": vnet_h,
                "parent": region_container_id,
            })

            vnet_max_height = max(vnet_max_height, vnet_h)
            vnet_rel_cursor_x += vnet_w + vnet_h_gap

        # Region container dimensions (absolute coordinates, parent is root layer)
        region_content_w = vnet_rel_cursor_x - vnet_h_gap + vnet_region_padding
        region_h = vnet_max_height + vnet_rel_y + vnet_region_padding
        region_w = max(region_content_w, 200)

        containers.append({
            "id": region_container_id,
            "label": region_name,
            "style": VNET_REGION_CONTAINER_STYLE,
            "x": r_abs_x,
            "y": r_abs_y,
            "w": region_w,
            "h": region_h,
            "parent": "1",
        })

        region_cursor_x += region_w + region_padding

    # Layout unattached nodes to the right of all region containers
    if unattached:
        unattached_id = "unattached_group"
        ua_abs_x = region_cursor_x
        ua_abs_y = region_padding
        inner_x = ua_abs_x + unattached_padding
        inner_y = ua_abs_y + vnet_header
        cols = min(COLS_PER_ROW, len(unattached))
        ua_pos, content_w, content_h = _grid_layout(unattached, inner_x, inner_y, cols, spacing=spacing)
        positions.update(ua_pos)

        ua_w = max(content_w, CELL_W) + 2 * unattached_padding
        ua_h = content_h + vnet_header + 2 * unattached_padding

        containers.append({
            "id": unattached_id,
            "label": "Other Resources",
            "style": UNATTACHED_STYLE,
            "x": ua_abs_x,
            "y": ua_abs_y,
            "w": ua_w,
            "h": ua_h,
            "parent": "1",
        })

    # Position boundary nodes at top-left, shifting all absolute-coord containers down
    if boundary_nodes:
        shift = CELL_H + 40 + region_padding
        for c in containers:
            # Only shift top-level (absolute) containers; nested ones use relative coords
            if c["parent"] == "1":
                c["y"] += shift
        for nid in list(positions.keys()):
            x, y, w, h = positions[nid]
            positions[nid] = (x, y + shift, w, h)
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (region_padding + i * (CELL_W + 40), region_padding, CELL_W, CELL_H)

    return positions, containers


# ---------------------------------------------------------------------------
# MSFT (Microsoft Architecture Center) layout
# ---------------------------------------------------------------------------

# Map Azure provider prefixes to friendly display names for type section headers
_TYPE_CATEGORY_MAP = {
    "microsoft.compute": "Compute",
    "microsoft.network": "Networking",
    "microsoft.storage": "Storage",
    "microsoft.sql": "Databases",
    "microsoft.documentdb": "Databases",
    "microsoft.dbformysql": "Databases",
    "microsoft.dbforpostgresql": "Databases",
    "microsoft.cache": "Databases",
    "microsoft.web": "Web",
    "microsoft.keyvault": "Security",
    "microsoft.authorization": "Security",
    "microsoft.managedidentity": "Identity",
    "microsoft.containerservice": "Containers",
    "microsoft.containerregistry": "Containers",
    "microsoft.app": "Containers",
    "microsoft.cognitiveservices": "AI + Machine Learning",
    "microsoft.search": "AI + Machine Learning",
    "microsoft.operationalinsights": "Monitoring",
    "microsoft.insights": "Monitoring",
    "microsoft.logic": "Integration",
    "microsoft.servicebus": "Integration",
    "microsoft.eventhub": "Integration",
}


def _type_category(resource_type: str) -> str:
    """Return a friendly category name for a resource type."""
    t = resource_type.lower()
    # Try exact provider prefix match
    provider = t.split("/")[0] if "/" in t else t
    cat = _TYPE_CATEGORY_MAP.get(provider)
    if cat:
        return cat
    return provider.replace("microsoft.", "").capitalize()


def layout_nodes_msft(
    nodes: List[Dict],
    cols: int = MSFT_COLS,
    spacing: float = 1.0,
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],   # node positions (relative to parent RG)
    List[Dict],                               # containers (regions + RGs)
    List[Dict],                               # type section headers
    Dict[str, str],                           # node_id -> parent container id
]:
    """Compute MSFT-mode layout: Region > RG > typed sections > resource grid.

    All resource coordinates are relative to their parent RG container.
    RG container coordinates are relative to their parent region container.
    Region container coordinates are absolute.

    The *spacing* multiplier scales gaps and padding (≥1.0 = more whitespace).
    Cell sizes (MSFT_CELL_W, MSFT_CELL_H) are unchanged.

    Returns:
      positions: node_id -> (x, y, w, h) relative to parent
      containers: list of region + RG container dicts
      type_headers: list of type section header dicts
      node_parents: node_id -> parent container id (the RG container)
    """
    s = lambda v: round(v * spacing)
    # Gaps/padding are scaled; cell sizes stay fixed
    x_gap = MSFT_X_STEP - MSFT_CELL_W          # base gap between cells
    y_gap = MSFT_Y_STEP - MSFT_CELL_H
    msft_x_step = MSFT_CELL_W + s(x_gap)       # scaled step
    msft_y_step = MSFT_CELL_H + s(y_gap)
    msft_rg_pad = s(MSFT_RG_PAD)
    msft_rg_header = s(MSFT_RG_HEADER)
    msft_type_header_h = s(MSFT_TYPE_HEADER_H)
    msft_rg_v_gap = s(MSFT_RG_V_GAP)
    msft_region_pad = s(MSFT_REGION_PAD)
    msft_region_header = s(MSFT_REGION_HEADER)

    # Separate boundary nodes
    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]

    node_by_id: Dict[str, Dict] = {n["id"]: n for n in regular_nodes}

    # Group by (region, rg, type)
    groups: Dict[Tuple[str, str, str], List[Dict]] = defaultdict(list)
    for n in regular_nodes:
        key = (
            n.get("location", "") or "unknown",
            n.get("resourceGroup", "") or "unknown",
            n.get("type", ""),
        )
        groups[key].append(n)

    # Sort within each group by (type, name, id) all lowercase
    for key in groups:
        groups[key].sort(key=lambda n: (n.get("type", "").lower(), n.get("name", "").lower(), n["id"].lower()))

    # Organize: region -> rg -> [(type, nodes)]
    region_rg_types: Dict[str, Dict[str, List[Tuple[str, List[Dict]]]]] = defaultdict(lambda: defaultdict(list))
    for key in sorted(groups.keys()):
        region, rg, rtype = key
        region_rg_types[region][rg].append((rtype, groups[key]))

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []
    type_headers: List[Dict] = []
    node_parents: Dict[str, str] = {}

    region_cursor_y = msft_region_pad

    for region in sorted(region_rg_types.keys()):
        region_id = "msft_region_" + stable_id(region)
        rgs = region_rg_types[region]

        rg_cursor_y = msft_region_header + msft_region_pad
        max_rg_w = 0

        for rg in sorted(rgs.keys()):
            rg_id = "msft_rg_" + stable_id(region + "/" + rg)
            type_groups = rgs[rg]

            # Sort type groups by category then type
            type_groups.sort(key=lambda t: (_type_category(t[0]).lower(), t[0].lower()))

            # Layout resources inside RG
            cursor_y = msft_rg_header + msft_rg_pad
            rg_content_w = 0

            for rtype, type_nodes in type_groups:
                category = _type_category(rtype)

                # Add type section header
                th_id = "msft_th_" + stable_id(rg_id + "/" + rtype)
                type_headers.append({
                    "id": th_id,
                    "label": category,
                    "x": msft_rg_pad,
                    "y": cursor_y,
                    "w": 120,
                    "h": msft_type_header_h,
                    "parent": rg_id,
                })
                cursor_y += msft_type_header_h

                # Layout type_nodes in grid
                n_in_row = min(cols, len(type_nodes)) if type_nodes else 1
                for i, node in enumerate(type_nodes):
                    col = i % cols
                    row = i // cols
                    nx = msft_rg_pad + col * msft_x_step
                    ny = cursor_y + row * msft_y_step
                    positions[node["id"]] = (nx, ny, MSFT_CELL_W, MSFT_CELL_H)
                    node_parents[node["id"]] = rg_id

                rows = (len(type_nodes) + cols - 1) // cols
                band_w = min(len(type_nodes), cols) * msft_x_step - (msft_x_step - MSFT_CELL_W)
                rg_content_w = max(rg_content_w, band_w)
                cursor_y += rows * msft_y_step

            # RG container size
            rg_w = max(rg_content_w, MSFT_CELL_W) + 2 * msft_rg_pad
            rg_h = cursor_y + msft_rg_pad

            containers.append({
                "id": rg_id,
                "label": rg,
                "style": MSFT_RG_STYLE,
                "x": msft_region_pad,
                "y": rg_cursor_y,
                "w": rg_w,
                "h": rg_h,
                "parent": region_id,
            })

            max_rg_w = max(max_rg_w, rg_w)
            rg_cursor_y += rg_h + msft_rg_v_gap

        # Region container size
        region_w = max_rg_w + 2 * msft_region_pad
        region_h = rg_cursor_y - msft_rg_v_gap + msft_region_pad

        containers.append({
            "id": region_id,
            "label": region,
            "style": MSFT_REGION_STYLE,
            "x": msft_region_pad,
            "y": region_cursor_y,
            "w": region_w,
            "h": region_h,
            "parent": "1",
        })

        region_cursor_y += region_h + msft_region_pad

    # Position boundary nodes above region containers
    if boundary_nodes:
        shift = MSFT_CELL_H + 40 + msft_region_pad
        for c in containers:
            c["y"] += shift
        for nid in list(positions.keys()):
            x, y, w, h = positions[nid]
            positions[nid] = (x, y + shift, w, h)
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (msft_region_pad + i * (MSFT_CELL_W + 40), msft_region_pad, MSFT_CELL_W, MSFT_CELL_H)
            node_parents[bn["id"]] = "1"

    return positions, containers, type_headers, node_parents


# ---------------------------------------------------------------------------
# SUB>REGION>RG>NET layout
# ---------------------------------------------------------------------------

# Layout constants for SUB>REGION>RG>NET mode
SUB_PAD = 50
SUB_HEADER = 40
SUB_V_GAP = 40

# Network types that get grouped into the "Networking" section inside an RG
_NETWORK_TYPES = {
    "microsoft.network/virtualnetworks",
    "microsoft.network/virtualnetworks/subnets",
    "microsoft.network/networksecuritygroups",
    "microsoft.network/applicationsecuritygroups",
    "microsoft.network/routetables",
    "microsoft.network/azurefirewalls",
    "microsoft.network/bastionhosts",
    "microsoft.network/applicationgateways",
    "microsoft.network/loadbalancers",
    "microsoft.network/publicipaddresses",
    "microsoft.network/privateendpoints",
    "microsoft.network/networkinterfaces",
    "microsoft.network/natgateways",
    "microsoft.network/firewallpolicies",
    "microsoft.network/virtualnetworkgateways",
    "microsoft.network/localnetworkgateways",
    "microsoft.network/connections",
}

# Style for subscription container
MSFT_SUB_STYLE = "shape=rectangle;rounded=1;fillColor=none;strokeColor=#0078D4;strokeWidth=2;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;spacingTop=5;arcSize=4;"

# Style for "Networking" section header inside an RG
MSFT_NET_SECTION_STYLE = "text;html=1;align=left;verticalAlign=top;resizable=0;points=[];autosize=1;strokeColor=none;fillColor=none;fontSize=11;fontStyle=3;fontColor=#0078D4;"

# BANDS-mode style for flat subscription/region/RG containers (no hierarchical nesting)
BANDS_SUB_STYLE = "shape=rectangle;rounded=1;fillColor=none;strokeColor=#0078D4;strokeWidth=2;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;spacingTop=5;arcSize=4;fontSize=13;fontStyle=1;fontColor=#0078D4;"
BANDS_REGION_STYLE = "shape=rectangle;dashed=1;fillColor=none;strokeColor=#999999;rounded=0;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;spacingTop=5;fontSize=11;fontStyle=2;"
BANDS_RG_STYLE = "rounded=1;fillColor=#f5f5f5;strokeColor=#cccccc;whiteSpace=wrap;html=1;verticalAlign=top;align=left;spacingLeft=8;spacingTop=5;fontSize=11;fontStyle=1;"


def _subscription_label(sub_id: str, nodes: List[Dict]) -> str:
    """Derive a display label for a subscription from its ID or first matching node."""
    if not sub_id or sub_id == "unknown":
        return "Unknown Subscription"
    # Use last 8 chars of subscription GUID as short label
    short = sub_id[-8:] if len(sub_id) > 8 else sub_id
    return f"Subscription ...{short}"


def layout_nodes_sub_rg_net(
    nodes: List[Dict],
    edges: List[Dict],
    cols: int = MSFT_COLS,
    spacing: float = 1.0,
    group_by_tag: Optional[List[str]] = None,
    layout_magic: bool = False,
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],   # node positions (relative to parent RG)
    List[Dict],                               # containers (subs + regions + RGs)
    List[Dict],                               # section headers
    Dict[str, str],                           # node_id -> parent container id
]:
    """Compute SUB>REGION>RG>NET layout: Subscription > Region > RG > Net|Other."""
    group_by_tag = group_by_tag or []
    degree_map = _collect_node_degrees(edges)

    s = lambda v: round(v * spacing)
    x_gap = MSFT_X_STEP - MSFT_CELL_W
    y_gap = MSFT_Y_STEP - MSFT_CELL_H
    msft_x_step = MSFT_CELL_W + s(x_gap)
    msft_y_step = MSFT_CELL_H + s(y_gap)
    msft_rg_pad = s(MSFT_RG_PAD)
    msft_rg_header = s(MSFT_RG_HEADER)
    msft_type_header_h = s(MSFT_TYPE_HEADER_H)
    msft_rg_v_gap = s(MSFT_RG_V_GAP)
    msft_region_pad = s(MSFT_REGION_PAD)
    msft_region_header = s(MSFT_REGION_HEADER)
    sub_pad = s(SUB_PAD)
    sub_header = s(SUB_HEADER)
    sub_v_gap = s(SUB_V_GAP)

    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]

    groups: Dict[Tuple[str, str, str, str], List[Dict]] = defaultdict(list)
    for n in regular_nodes:
        key = (
            n.get("subscriptionId", "") or "unknown",
            n.get("location", "") or "unknown",
            n.get("resourceGroup", "") or "unknown",
            n.get("type", ""),
        )
        groups[key].append(n)

    for key in groups:
        groups[key] = sorted(groups[key], key=lambda n: (n.get("name", "").lower(), n["id"].lower()))

    hierarchy: Dict[str, Dict[str, Dict[str, List[Tuple[str, List[Dict]]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for key in sorted(groups.keys()):
        sub, region, rg, rtype = key
        hierarchy[sub][region][rg].append((rtype, groups[key]))

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []
    type_headers: List[Dict] = []
    node_parents: Dict[str, str] = {}

    sub_cursor_y = sub_pad

    for sub in sorted(hierarchy.keys()):
        sub_id = "msft_sub_" + stable_id(sub)
        regions = hierarchy[sub]
        region_cursor_y = sub_header + sub_pad
        max_region_w = 0

        for region in sorted(regions.keys()):
            region_id = "msft_region_" + stable_id(sub + "/" + region)
            rgs = regions[region]
            rg_cursor_y = msft_region_header + msft_region_pad
            max_rg_w = 0

            for rg in sorted(rgs.keys()):
                rg_id = "msft_rg_" + stable_id(sub + "/" + region + "/" + rg)
                type_groups = rgs[rg]
                net_groups = [(t, ns) for t, ns in type_groups if t.lower() in _NETWORK_TYPES]
                other_groups = [(t, ns) for t, ns in type_groups if t.lower() not in _NETWORK_TYPES]

                if layout_magic:
                    net_groups.sort(
                        key=lambda item: (
                            -sum(degree_map.get(node["id"], 0) for node in item[1]),
                            item[0].lower(),
                        )
                    )
                else:
                    net_groups.sort(key=lambda item: item[0].lower())
                other_groups.sort(key=lambda item: (_type_category(item[0]).lower(), item[0].lower()))

                cursor_y = msft_rg_header + msft_rg_pad
                rg_content_w = 0

                if net_groups:
                    type_headers.append({
                        "id": "msft_th_" + stable_id(rg_id + "/Networking"),
                        "label": "Networking",
                        "x": msft_rg_pad,
                        "y": cursor_y,
                        "w": 120,
                        "h": msft_type_header_h,
                        "parent": rg_id,
                        "style": MSFT_NET_SECTION_STYLE,
                    })
                    cursor_y += msft_type_header_h

                    for rtype, type_nodes in net_groups:
                        sorted_nodes = _sorted_group_nodes(type_nodes, degree_map, layout_magic)
                        type_headers.append({
                            "id": "msft_th_" + stable_id(rg_id + "/" + rtype),
                            "label": rtype.split("/")[-1] if "/" in rtype else rtype,
                            "x": msft_rg_pad + 10,
                            "y": cursor_y,
                            "w": 160,
                            "h": msft_type_header_h,
                            "parent": rg_id,
                        })
                        cursor_y += msft_type_header_h

                        group_cols = _group_cols(len(sorted_nodes), cols, layout_magic)
                        for i, node in enumerate(sorted_nodes):
                            col = i % group_cols
                            row = i // group_cols
                            positions[node["id"]] = (
                                msft_rg_pad + col * msft_x_step,
                                cursor_y + row * msft_y_step,
                                MSFT_CELL_W,
                                MSFT_CELL_H,
                            )
                            node_parents[node["id"]] = rg_id

                        rows = (len(sorted_nodes) + group_cols - 1) // group_cols if sorted_nodes else 0
                        band_w = min(len(sorted_nodes), group_cols) * msft_x_step - (msft_x_step - MSFT_CELL_W) if sorted_nodes else MSFT_CELL_W
                        rg_content_w = max(rg_content_w, band_w)
                        cursor_y += rows * msft_y_step

                resource_sections = _resource_sections(other_groups, group_by_tag, degree_map, layout_magic)
                has_resource_nodes = any(section["type_groups"] for section in resource_sections)
                if has_resource_nodes:
                    type_headers.append({
                        "id": "msft_th_" + stable_id(rg_id + "/Resources"),
                        "label": "Resources",
                        "x": msft_rg_pad,
                        "y": cursor_y,
                        "w": 120,
                        "h": msft_type_header_h,
                        "parent": rg_id,
                    })
                    cursor_y += msft_type_header_h

                    for section in resource_sections:
                        section_label = section.get("label")
                        if section_label:
                            type_headers.append({
                                "id": "msft_th_" + stable_id(rg_id + "/section/" + section_label),
                                "label": section_label,
                                "x": msft_rg_pad + 10,
                                "y": cursor_y,
                                "w": 220,
                                "h": msft_type_header_h,
                                "parent": rg_id,
                                "style": MSFT_NET_SECTION_STYLE,
                            })
                            cursor_y += msft_type_header_h

                        for rtype, type_nodes in section["type_groups"]:
                            type_headers.append({
                                "id": "msft_th_" + stable_id(rg_id + "/resource/" + rtype + "/" + (section_label or "default")),
                                "label": _type_category(rtype),
                                "x": msft_rg_pad + 20,
                                "y": cursor_y,
                                "w": 160,
                                "h": msft_type_header_h,
                                "parent": rg_id,
                            })
                            cursor_y += msft_type_header_h

                            group_cols = _group_cols(len(type_nodes), cols, layout_magic)
                            for i, node in enumerate(type_nodes):
                                col = i % group_cols
                                row = i // group_cols
                                positions[node["id"]] = (
                                    msft_rg_pad + col * msft_x_step,
                                    cursor_y + row * msft_y_step,
                                    MSFT_CELL_W,
                                    MSFT_CELL_H,
                                )
                                node_parents[node["id"]] = rg_id

                            rows = (len(type_nodes) + group_cols - 1) // group_cols if type_nodes else 0
                            band_w = min(len(type_nodes), group_cols) * msft_x_step - (msft_x_step - MSFT_CELL_W) if type_nodes else MSFT_CELL_W
                            rg_content_w = max(rg_content_w, band_w)
                            cursor_y += rows * msft_y_step

                rg_w = max(rg_content_w, MSFT_CELL_W) + 2 * msft_rg_pad
                rg_h = cursor_y + msft_rg_pad
                containers.append({
                    "id": rg_id,
                    "label": rg,
                    "style": MSFT_RG_STYLE,
                    "x": msft_region_pad,
                    "y": rg_cursor_y,
                    "w": rg_w,
                    "h": rg_h,
                    "parent": region_id,
                })
                max_rg_w = max(max_rg_w, rg_w)
                rg_cursor_y += rg_h + msft_rg_v_gap

            region_w = max_rg_w + 2 * msft_region_pad
            region_h = rg_cursor_y - msft_rg_v_gap + msft_region_pad
            containers.append({
                "id": region_id,
                "label": region,
                "style": MSFT_REGION_STYLE,
                "x": sub_pad,
                "y": region_cursor_y,
                "w": region_w,
                "h": region_h,
                "parent": sub_id,
            })
            max_region_w = max(max_region_w, region_w)
            region_cursor_y += region_h + msft_region_pad

        sub_w = max_region_w + 2 * sub_pad
        sub_h = region_cursor_y - msft_region_pad + sub_pad
        containers.append({
            "id": sub_id,
            "label": _subscription_label(sub, nodes),
            "style": MSFT_SUB_STYLE,
            "x": sub_pad,
            "y": sub_cursor_y,
            "w": sub_w,
            "h": sub_h,
            "parent": "1",
        })
        sub_cursor_y += sub_h + sub_v_gap

    if boundary_nodes:
        shift = MSFT_CELL_H + 40 + sub_pad
        for c in containers:
            c["y"] += shift
        for nid in list(positions.keys()):
            x, y, w, h = positions[nid]
            positions[nid] = (x, y + shift, w, h)
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (sub_pad + i * (MSFT_CELL_W + 40), sub_pad, MSFT_CELL_W, MSFT_CELL_H)
            node_parents[bn["id"]] = "1"

    return positions, containers, type_headers, node_parents


# ---------------------------------------------------------------------------
# SUB>REGION>RG>NET flat BANDS layout (no hierarchical nesting)
# ---------------------------------------------------------------------------
# SUB>REGION>RG>NET flat BANDS layout (no hierarchical nesting)
# ---------------------------------------------------------------------------

BANDS_SUB_PAD = 30
BANDS_SUB_HEADER = 35
BANDS_RG_PAD = 20
BANDS_RG_HEADER = 28
BANDS_REGION_PAD = 25
BANDS_REGION_HEADER = 25


def layout_nodes_sub_rg_net_bands(
    nodes: List[Dict],
    edges: List[Dict],
    cols: int = COLS_PER_ROW,
    spacing: float = 1.0,
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],   # node absolute positions
    List[Dict],                               # flat containers (subs + regions + RGs)
]:
    """Compute flat BANDS layout for SUB>REGION>RG>NET.

    Unlike the MSFT nested variant, all containers use parent="1" (flat)
    and node positions are absolute. This produces a simpler visual with
    subscription/region/RG bands as background frames — no draw.io
    hierarchical parenting.

    Returns (positions, containers) for the BANDS rendering path.
    """
    s = lambda v: round(v * spacing)
    h_gap = s(H_GAP)
    v_gap = s(V_GAP)
    sub_pad = s(BANDS_SUB_PAD)
    sub_header = s(BANDS_SUB_HEADER)
    rg_pad = s(BANDS_RG_PAD)
    rg_header = s(BANDS_RG_HEADER)
    region_pad = s(BANDS_REGION_PAD)
    region_header = s(BANDS_REGION_HEADER)

    # Separate boundary nodes from regular nodes
    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]

    # Group regular nodes: sub -> region -> rg -> [nodes]
    hierarchy: Dict[str, Dict[str, Dict[str, List[Dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for n in regular_nodes:
        sub = n.get("subscriptionId", "") or "unknown"
        region = n.get("location", "") or "unknown"
        rg = n.get("resourceGroup", "") or "unknown"
        hierarchy[sub][region][rg].append(n)

    # Sort nodes within each group
    for sub in hierarchy.values():
        for region in sub.values():
            for rg_name, rg_nodes in region.items():
                rg_nodes.sort(key=lambda n: (n.get("type", "").lower(), n.get("name", "").lower(), n["id"].lower()))

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []

    cursor_y = sub_pad

    for sub in sorted(hierarchy.keys()):
        sub_start_y = cursor_y
        sub_x = sub_pad
        cursor_y += sub_header

        for region in sorted(hierarchy[sub].keys()):
            region_start_y = cursor_y
            region_x = sub_x + region_pad
            cursor_y += region_header

            rg_x = region_x + rg_pad
            rg_max_bottom = cursor_y

            for rg in sorted(hierarchy[sub][region].keys()):
                rg_start_y = cursor_y
                rg_nodes = hierarchy[sub][region][rg]
                cursor_y_rg = rg_start_y + rg_header

                # Lay out nodes in a flat grid
                for i, node in enumerate(rg_nodes):
                    col = i % cols
                    row = i // cols
                    nx = rg_x + rg_pad + col * (CELL_W + h_gap)
                    ny = cursor_y_rg + row * (CELL_H + v_gap)
                    positions[node["id"]] = (nx, ny, CELL_W, CELL_H)

                n_rows = max(1, (len(rg_nodes) + cols - 1) // cols)
                n_cols = min(len(rg_nodes), cols) if rg_nodes else 1
                rg_content_w = n_cols * (CELL_W + h_gap) - h_gap
                rg_bottom = cursor_y_rg + n_rows * (CELL_H + v_gap) - v_gap + rg_pad
                rg_w = rg_content_w + 2 * rg_pad
                rg_h = rg_bottom - rg_start_y

                containers.append({
                    "id": "bands_rg_" + stable_id(sub + "/" + region + "/" + rg),
                    "label": rg,
                    "style": BANDS_RG_STYLE,
                    "x": rg_x,
                    "y": rg_start_y,
                    "w": rg_w,
                    "h": rg_h,
                    "parent": "1",
                })

                rg_max_bottom = max(rg_max_bottom, rg_start_y + rg_h)
                cursor_y = rg_start_y + rg_h + v_gap

            # Region container
            region_w = max(c["x"] + c["w"] for c in containers if c["y"] >= region_start_y and c["y"] < rg_max_bottom + v_gap) - region_x + region_pad if containers else 200
            region_h = rg_max_bottom - region_start_y + region_pad

            containers.append({
                "id": "bands_region_" + stable_id(sub + "/" + region),
                "label": region,
                "style": BANDS_REGION_STYLE,
                "x": region_x,
                "y": region_start_y,
                "w": region_w,
                "h": region_h,
                "parent": "1",
            })

            cursor_y = region_start_y + region_h + region_pad

        # Subscription container
        sub_bottom = cursor_y
        sub_w = max(
            (c["x"] + c["w"] for c in containers if c["y"] >= sub_start_y),
            default=300,
        ) - sub_x + sub_pad
        sub_h = sub_bottom - sub_start_y

        containers.append({
            "id": "bands_sub_" + stable_id(sub),
            "label": _subscription_label(sub, nodes),
            "style": BANDS_SUB_STYLE,
            "x": sub_x,
            "y": sub_start_y,
            "w": sub_w,
            "h": sub_h,
            "parent": "1",
        })

        cursor_y = sub_start_y + sub_h + sub_pad

    # Position boundary nodes at the top-left, above all subscription containers
    if boundary_nodes:
        bx = sub_pad
        by = max(0, min((c["y"] for c in containers), default=sub_pad) - CELL_H - 40)
        if by < sub_pad:
            by = sub_pad
            # Shift everything down
            shift = CELL_H + 40 + sub_pad
            for c in containers:
                c["y"] += shift
            for nid in list(positions.keys()):
                x, y, w, h = positions[nid]
                positions[nid] = (x, y + shift, w, h)
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (bx + i * (CELL_W + 40), by, CELL_W, CELL_H)

    return positions, containers


def _build_network_context_annotations(
    nodes: List[Dict], edges: List[Dict],
) -> Dict[str, List[str]]:
    """Build compact network context annotation lines for each resource.

    Traverses vm->nic, nic->subnet/nsg/asg, subnet->vnet/nsg/routeTable
    edges and produces a summary for the annotation box rendered next to
    each compute resource in compact (networkDetail=compact) mode.

    Returns {resource_id: [label_lines]}.
    """
    node_by_id = {n["id"]: n for n in nodes}

    # Build outgoing edge index: source_id -> [(kind, target_id)]
    edges_from: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for e in edges:
        edges_from[e["source"]].append((e["kind"], e["target"]))

    def _name(nid: str) -> str:
        n = node_by_id.get(nid)
        return n.get("name", nid.split("/")[-1]) if n else nid.split("/")[-1]

    def _targets(nid: str, kind: str) -> List[str]:
        return [tgt for k, tgt in edges_from[nid] if k == kind]

    network_context: Dict[str, List[str]] = {}

    for node in nodes:
        nid = node["id"]
        if node.get("type", "").lower().startswith("__boundary__"):
            continue

        nics = _targets(nid, "vm->nic")
        if not nics:
            continue

        lines = ["Network:"]
        seen_subnets: set = set()

        for nic_id in nics:
            nsgs_from_nic = _targets(nic_id, "nic->nsg")
            asgs_from_nic = _targets(nic_id, "nic->asg")

            for subnet_id in _targets(nic_id, "nic->subnet"):
                if subnet_id in seen_subnets:
                    continue
                seen_subnets.add(subnet_id)

                vnets = _targets(subnet_id, "subnet->vnet")
                vnet_part = f" ({_name(vnets[0])})" if vnets else ""
                lines.append(f"  Subnet: {_name(subnet_id)}{vnet_part}")

                all_nsgs = list(dict.fromkeys(nsgs_from_nic + _targets(subnet_id, "subnet->nsg")))
                if all_nsgs:
                    lines.append(f"  NSG: {', '.join(_name(n) for n in all_nsgs)}")

                if asgs_from_nic:
                    lines.append(f"  ASG: {', '.join(_name(a) for a in asgs_from_nic)}")

                udrs = _targets(subnet_id, "subnet->routeTable")
                if udrs:
                    rt_node = node_by_id.get(udrs[0])
                    count = len((rt_node.get("properties") or {}).get("routes", [])) if rt_node else 0
                    suffix = f" ({count} routes)" if count else ""
                    lines.append(f"  UDR: {_name(udrs[0])}{suffix}")

        if len(lines) > 1:
            network_context[nid] = lines

    return network_context


# ---------------------------------------------------------------------------
# L2R mode helpers
# ---------------------------------------------------------------------------


def _l2r_find_direct_network_items(
    nodes: List[Dict],
    edges: List[Dict],
    seed_rgs: List[str],
    seed_tags: Optional[Dict[str, str]] = None,
    seed_tag_keys: Optional[List[str]] = None,
) -> Tuple[set, List[str]]:
    """Find network items directly attached to resources in the configured seed scope.

    Returns:
      direct_net_ids: set of node IDs to display in the network section
      indirect_lines: text lines for the far-right context info box
    """
    seed_rg_set = {r.lower() for r in seed_rgs}
    seed_tags = seed_tags or {}
    seed_tag_keys = seed_tag_keys or []
    node_by_id: Dict[str, Dict] = {normalize_id(n["id"]): n for n in nodes}

    def _matches_seed_scope(node: Dict) -> bool:
        if node.get("resourceGroup", "").lower() in seed_rg_set:
            return True

        tags = node.get("tags") or {}
        tags_by_lower = {
            str(key).strip().lower(): "" if value is None else str(value).strip()
            for key, value in tags.items()
            if str(key).strip()
        }

        for key, value in seed_tags.items():
            actual = tags_by_lower.get(key.lower())
            if actual is not None and actual.lower() == value.lower():
                return True

        for key in seed_tag_keys:
            if tags_by_lower.get(key.lower()):
                return True

        return False

    # Seed compute/app resources (in seed scope, not already a network type)
    seed_resource_ids = {
        normalize_id(n["id"]) for n in nodes
        if _matches_seed_scope(n)
        and not n.get("type", "").startswith("__boundary__")
    }

    # Build edge map: source -> [(target, kind)]
    edges_from: Dict[str, List] = defaultdict(list)
    for e in edges:
        edges_from[normalize_id(e["source"])].append(
            (normalize_id(e["target"]), e["kind"])
        )

    _direct_edge_kinds = {
        "vm->nic", "nic->subnet", "nic->nsg", "nic->asg",
        "privateEndpoint->subnet", "webApp->subnet", "containerEnv->subnet",
        "appGw->subnet", "firewall->subnet", "bastion->subnet",
        "loadBalancer->subnet", "natGateway->subnet", "nic->pip",
    }
    _expand_edge_kinds = {
        "nic->subnet", "nic->nsg", "nic->asg", "nic->pip",
        "subnet->vnet", "subnet->nsg", "subnet->routeTable",
    }

    direct_net_ids: set = set()

    # Step 1: direct network items one hop from seed resources
    for src_id in seed_resource_ids:
        for tgt_id, kind in edges_from.get(src_id, []):
            if kind not in _direct_edge_kinds:
                continue
            tgt = node_by_id.get(tgt_id)
            if tgt and tgt.get("type", "").lower() in _L2R_NETWORK_TYPES:
                direct_net_ids.add(normalize_id(tgt["id"]))

    # Step 2: expand from NICs → subnets → VNets/NSGs/UDRs
    to_expand = set(direct_net_ids)
    visited_expand: set = set()
    while to_expand:
        expanding = to_expand - visited_expand
        if not expanding:
            break
        visited_expand |= expanding
        to_expand = set()
        for nid in expanding:
            for tgt_id, kind in edges_from.get(nid, []):
                if kind not in _expand_edge_kinds:
                    continue
                tgt = node_by_id.get(tgt_id)
                if tgt and tgt.get("type", "").lower() in _L2R_NETWORK_TYPES:
                    normalized_tgt_id = normalize_id(tgt["id"])
                    direct_net_ids.add(normalized_tgt_id)
                    to_expand.add(normalized_tgt_id)

    # Step 3: collect indirect context info (not drawn, shown in text box)
    indirect_lines: List[str] = []

    peering_pairs: List[str] = []
    for nid in direct_net_ids:
        for tgt_id, kind in edges_from.get(nid, []):
            if kind == "vnet->peeredVnet":
                src_node = node_by_id.get(nid)
                tgt_node = node_by_id.get(tgt_id)
                if src_node and tgt_node:
                    peering_pairs.append(
                        f"  {src_node.get('name', nid)} \u2194 {tgt_node.get('name', tgt_id)}"
                    )
    if peering_pairs:
        indirect_lines.append("VNet Peerings:")
        indirect_lines.extend(peering_pairs)

    gw_names = [
        node_by_id[nid].get("name", nid)
        for nid in direct_net_ids
        if node_by_id.get(nid, {}).get("type", "").lower() in {
            "microsoft.network/virtualnetworkgateways",
            "microsoft.network/expressroutecircuits",
        }
    ]
    if gw_names:
        if indirect_lines:
            indirect_lines.append("")
        indirect_lines.append("VPN / ExpressRoute:")
        for name in gw_names:
            indirect_lines.append(f"  {name}")

    nsg_summaries_ctx = []
    for nid in direct_net_ids:
        node = node_by_id.get(nid, {})
        if node.get("type", "").lower() == "microsoft.network/networksecuritygroups":
            rules = _get(node.get("properties", {}), "securityRules") or []
            custom = [
                r for r in rules
                if int((_get(r, "properties", "priority") or 65000)) < 65000
            ]
            if custom:
                nsg_summaries_ctx.append(
                    f"  {node.get('name', nid)}: {len(custom)} custom rules"
                )
    if nsg_summaries_ctx:
        if indirect_lines:
            indirect_lines.append("")
        indirect_lines.append("NSG Custom Rules:")
        indirect_lines.extend(nsg_summaries_ctx)

    udr_summaries_ctx = []
    for nid in direct_net_ids:
        node = node_by_id.get(nid, {})
        if node.get("type", "").lower() == "microsoft.network/routetables":
            routes = _get(node.get("properties", {}), "routes") or []
            if routes:
                udr_summaries_ctx.append(
                    f"  {node.get('name', nid)}: {len(routes)} routes"
                )
    if udr_summaries_ctx:
        if indirect_lines:
            indirect_lines.append("")
        indirect_lines.append("User-Defined Routes:")
        indirect_lines.extend(udr_summaries_ctx)

    return direct_net_ids, indirect_lines


def layout_nodes_l2r(
    nodes: List[Dict],
    edges: List[Dict],
    seed_rgs: List[str],
    seed_tags: Optional[Dict[str, str]] = None,
    seed_tag_keys: Optional[List[str]] = None,
    spacing: float = 1.0,
    group_by_tag: Optional[List[str]] = None,
    layout_magic: bool = False,
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],
    List[Dict],
    List[Dict],
    Dict[str, str],
    List[str],
]:
    """L2R layout: Sub > Region > RG hierarchy, resources left / network right."""
    group_by_tag = group_by_tag or []
    degree_map = _collect_node_degrees(edges)

    s = lambda v: round(v * spacing)
    x_step = L2R_CELL_W + s(L2R_X_STEP - L2R_CELL_W)
    y_step = L2R_CELL_H + s(L2R_Y_STEP - L2R_CELL_H)
    rg_pad = s(L2R_RG_PAD)
    rg_header = s(L2R_RG_HEADER)
    rg_v_gap = s(L2R_RG_V_GAP)
    section_gap = s(L2R_SECTION_GAP)
    section_header_h = s(L2R_SECTION_HEADER_H)
    region_pad = s(L2R_REGION_PAD)
    region_header = s(L2R_REGION_HEADER)
    region_v_gap = s(L2R_REGION_V_GAP)
    sub_pad = s(L2R_SUB_PAD)
    sub_header = s(L2R_SUB_HEADER)

    direct_net_ids, indirect_info = _l2r_find_direct_network_items(
        nodes, edges, seed_rgs, seed_tags, seed_tag_keys,
    )
    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []
    type_headers: List[Dict] = []
    node_parents: Dict[str, str] = {}

    sub_region_rg: Dict[str, Dict[str, Dict[str, Dict[str, List[Dict]]]]] = (
        defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"resources": [], "network": []})))
    )
    for n in regular_nodes:
        ntype = n.get("type", "").lower()
        is_net = ntype in _L2R_NETWORK_TYPES
        if is_net and n["id"] not in direct_net_ids:
            continue
        sub = n.get("subscriptionId", "") or "unknown"
        region = n.get("location", "") or "unknown"
        rg = n.get("resourceGroup", "") or "unknown"
        section = "network" if is_net else "resources"
        sub_region_rg[sub][region][rg][section].append(n)

    for sub_id in sub_region_rg:
        for region in sub_region_rg[sub_id]:
            for rg in sub_region_rg[sub_id][region]:
                resources = sub_region_rg[sub_id][region][rg]["resources"]
                resources.sort(
                    key=lambda n: (
                        _tag_group_label(n, group_by_tag).lower() if group_by_tag else "",
                        -degree_map.get(n["id"], 0) if layout_magic else 0,
                        n.get("type", "").lower(),
                        n.get("name", "").lower(),
                    )
                )
                sub_region_rg[sub_id][region][rg]["network"].sort(
                    key=lambda n: (
                        -degree_map.get(n["id"], 0) if layout_magic else 0,
                        n.get("type", "").lower(),
                        n.get("name", "").lower(),
                    )
                )

    sub_cursor_y = sub_pad
    for sub_id in sorted(sub_region_rg.keys()):
        sub_cont_id = "l2r_sub_" + stable_id(sub_id)
        regions = sub_region_rg[sub_id]
        region_cursor_y = sub_header + sub_pad
        max_region_w = 0

        for region in sorted(regions.keys()):
            region_cont_id = "l2r_region_" + stable_id(sub_id + "/" + region)
            rgs = regions[region]
            rg_cursor_y = region_header + region_pad
            max_rg_w = 0

            for rg in sorted(rgs.keys()):
                rg_cont_id = "l2r_rg_" + stable_id(sub_id + "/" + region + "/" + rg)
                res_nodes = rgs[rg]["resources"]
                net_nodes = rgs[rg]["network"]

                res_cols = _group_cols(len(res_nodes), L2R_RESOURCE_COLS, layout_magic) if res_nodes else 1
                res_rows = (len(res_nodes) + res_cols - 1) // res_cols if res_nodes else 0
                res_grid_w = (res_cols - 1) * x_step + L2R_CELL_W if res_nodes else 0
                res_grid_h = (res_rows - 1) * y_step + L2R_CELL_H if res_nodes else 0

                net_cols = _group_cols(len(net_nodes), L2R_NETWORK_COLS, layout_magic) if net_nodes else 1
                net_rows = (len(net_nodes) + net_cols - 1) // net_cols if net_nodes else 0
                net_grid_w = (net_cols - 1) * x_step + L2R_CELL_W if net_nodes else 0
                net_grid_h = (net_rows - 1) * y_step + L2R_CELL_H if net_nodes else 0

                content_y = rg_header + rg_pad
                nodes_y = content_y + section_header_h
                res_start_x = rg_pad
                net_start_x = (
                    rg_pad + res_grid_w + section_gap
                    if res_nodes and net_nodes
                    else (rg_pad + res_grid_w if res_nodes else rg_pad)
                )

                for i, node in enumerate(res_nodes):
                    col = i % res_cols
                    row = i // res_cols
                    positions[node["id"]] = (
                        res_start_x + col * x_step,
                        nodes_y + row * y_step,
                        L2R_CELL_W,
                        L2R_CELL_H,
                    )
                    node_parents[node["id"]] = rg_cont_id

                for i, node in enumerate(net_nodes):
                    col = i % net_cols
                    row = i // net_cols
                    positions[node["id"]] = (
                        net_start_x + col * x_step,
                        nodes_y + row * y_step,
                        L2R_CELL_W,
                        L2R_CELL_H,
                    )
                    node_parents[node["id"]] = rg_cont_id

                if res_nodes:
                    type_headers.append({
                        "id": "l2r_sh_res_" + rg_cont_id,
                        "label": "Resources",
                        "x": res_start_x,
                        "y": content_y,
                        "w": max(res_grid_w, 70),
                        "h": section_header_h,
                        "parent": rg_cont_id,
                        "style": L2R_SECTION_HEADER_RESOURCE_STYLE,
                    })
                if net_nodes:
                    type_headers.append({
                        "id": "l2r_sh_net_" + rg_cont_id,
                        "label": "Network",
                        "x": net_start_x,
                        "y": content_y,
                        "w": max(net_grid_w, 70),
                        "h": section_header_h,
                        "parent": rg_cont_id,
                        "style": L2R_SECTION_HEADER_NETWORK_STYLE,
                    })

                total_w = (
                    (res_grid_w if res_nodes else 0)
                    + (section_gap if res_nodes and net_nodes else 0)
                    + (net_grid_w if net_nodes else 0)
                )
                section_max_h = max(res_grid_h if res_nodes else 0, net_grid_h if net_nodes else 0)
                rg_w = max(total_w, L2R_CELL_W) + 2 * rg_pad
                rg_h = nodes_y + section_max_h + rg_pad

                containers.append({
                    "id": rg_cont_id,
                    "label": rg,
                    "style": L2R_RG_STYLE,
                    "x": region_pad,
                    "y": rg_cursor_y,
                    "w": rg_w,
                    "h": rg_h,
                    "parent": region_cont_id,
                })
                max_rg_w = max(max_rg_w, rg_w)
                rg_cursor_y += rg_h + rg_v_gap

            region_w = max_rg_w + 2 * region_pad
            region_h = rg_cursor_y - rg_v_gap + region_pad
            containers.append({
                "id": region_cont_id,
                "label": region,
                "style": L2R_REGION_STYLE,
                "x": sub_pad,
                "y": region_cursor_y,
                "w": region_w,
                "h": region_h,
                "parent": sub_cont_id,
            })
            max_region_w = max(max_region_w, region_w)
            region_cursor_y += region_h + region_v_gap

        sub_w = max_region_w + 2 * sub_pad
        sub_h = region_cursor_y - region_v_gap + sub_pad
        containers.append({
            "id": sub_cont_id,
            "label": _subscription_label(sub_id, nodes),
            "style": L2R_SUB_STYLE,
            "x": sub_pad,
            "y": sub_cursor_y,
            "w": sub_w,
            "h": sub_h,
            "parent": "1",
        })
        sub_cursor_y += sub_h + 40

    if boundary_nodes:
        shift_y = L2R_CELL_H + 40
        for cont in containers:
            if cont.get("parent") == "1":
                cont["y"] += shift_y
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (
                sub_pad + i * (L2R_CELL_W + 40),
                sub_pad,
                L2R_CELL_W,
                L2R_CELL_H,
            )
            node_parents[bn["id"]] = LAYER_RESOURCES

    return positions, containers, type_headers, node_parents, indirect_info


def _render_l2r_mode(
    cfg: Config,
    nodes: List[Dict],
    edges: List[Dict],
    icon_map: Dict[str, str],
    msft_icons: Optional[Dict[str, Path]] = None,
) -> None:
    """Render the diagram in L2R (Left-to-Right) style."""
    sp = _spacing_factor(cfg.spacing)
    positions, containers, type_headers, node_parents, indirect_info = layout_nodes_l2r(
        nodes, edges, cfg.seedResourceGroups, cfg.seedTags, cfg.seedTagKeys, spacing=sp,
        group_by_tag=cfg.groupByTag, layout_magic=cfg.layoutMagic,
    )

    icons_used: Dict[str, Any] = {"mapped": {}, "fallback": [], "unknown": []}
    mxfile, root = _build_mxfile_root(cfg)
    container_positions = _container_absolute_positions(containers)
    hub_roles = _hub_role_map(nodes, edges)

    for cont in _topo_sort_containers(containers):
        cont_parent = LAYER_CONTAINERS if cont["parent"] == "1" else cont["parent"]
        cc = ET.SubElement(root, "mxCell")
        cc.set("id", cont["id"])
        cc.set("value", cont["label"])
        cc.set("style", cont["style"])
        cc.set("vertex", "1")
        cc.set("parent", cont_parent)
        cc.set("connectable", "0")
        cg = ET.SubElement(cc, "mxGeometry")
        cg.set("x", str(cont["x"]))
        cg.set("y", str(cont["y"]))
        cg.set("width", str(cont["w"]))
        cg.set("height", str(cont["h"]))
        cg.set("as", "geometry")

    for th in type_headers:
        abs_x, abs_y = _absolute_child_position(th["x"], th["y"], th["parent"], container_positions)
        tc = ET.SubElement(root, "mxCell")
        tc.set("id", th["id"])
        tc.set("value", th["label"])
        tc.set("style", th.get("style", MSFT_TYPE_HEADER_STYLE))
        tc.set("vertex", "1")
        tc.set("parent", LAYER_LABELS)
        tg = ET.SubElement(tc, "mxGeometry")
        tg.set("x", str(abs_x))
        tg.set("y", str(abs_y))
        tg.set("width", str(th["w"]))
        tg.set("height", str(th["h"]))
        tg.set("as", "geometry")

    node_id_map: Dict[str, str] = {}
    visible_node_ids = set(positions.keys())
    for node in nodes:
        nid = node["id"]
        sid = stable_id(nid)
        node_id_map[nid] = sid
        if nid not in positions:
            continue
        parent_id = node_parents.get(nid, LAYER_RESOURCES)
        abs_x, abs_y = _absolute_child_position(*positions[nid][:2], parent_id, container_positions)
        w, h = positions[nid][2], positions[nid][3]
        render_node = dict(node)
        role = hub_roles.get(nid)
        if role and render_node.get("type", "").lower() == "microsoft.network/virtualnetworks":
            render_node["displayName"] = f"{render_node.get('name', nid)} ({role})"
        style = _node_style(render_node, icon_map, msft_icons)
        t = render_node.get("type", "")
        if style == UNKNOWN_STYLE:
            if t not in icons_used["unknown"]:
                icons_used["unknown"].append(t)
        elif "data:image/svg+xml" in style:
            if t not in icons_used["fallback"]:
                icons_used["fallback"].append(t)
        elif style != EXTERNAL_STYLE:
            icons_used["mapped"][t] = icons_used["mapped"].get(t, 0) + 1
        _emit_resource_cell(root, render_node, sid, style, abs_x, abs_y, w, h, parent_id=LAYER_RESOURCES)

    _emit_resource_metadata_boxes(root, nodes, node_id_map, positions, node_parents, container_positions)

    legend_anchor_x = max((c["x"] + c["w"] for c in containers if c.get("parent") == "1"), default=100) + 60
    legend_anchor_y = 60
    inventory_lines = _diagram_inventory_lines(nodes, visible_node_ids)
    if inventory_lines:
        inventory_h = _emit_text_panel(
            root,
            "l2r_inventory_box",
            inventory_lines,
            x=legend_anchor_x,
            y=legend_anchor_y,
            width=320,
            style=L2R_CONTEXT_BOX_STYLE,
        )
        legend_anchor_y += inventory_h + 20
    context_lines = _nic_ip_context_lines(nodes)
    if indirect_info:
        if context_lines:
            context_lines.append("")
        context_lines.extend(indirect_info)
    if context_lines:
        context_h = _emit_text_panel(
            root,
            "l2r_netctx_box",
            ["Network Context", "──────────────────────"] + context_lines,
            x=legend_anchor_x,
            y=legend_anchor_y,
            width=320,
            style=L2R_CONTEXT_BOX_STYLE,
        )
        legend_anchor_y += context_h + 20

    _emit_legend_box(root, "l2r_network_legend", legend_anchor_x, legend_anchor_y)

    for e in edges:
        if e["kind"] not in _L2R_DRAW_EDGE_KINDS:
            continue
        src_raw = normalize_id(e["source"])
        tgt_raw = normalize_id(e["target"])
        src = node_id_map.get(src_raw) or node_id_map.get(e["source"])
        tgt = node_id_map.get(tgt_raw) or node_id_map.get(e["target"])
        if not src or not tgt:
            continue
        if e["source"] not in visible_node_ids and src_raw not in visible_node_ids:
            continue
        if e["target"] not in visible_node_ids and tgt_raw not in visible_node_ids:
            continue
        edge_id = f"e_{stable_id(e['source'] + e['target'] + e['kind'])}"
        ec = ET.SubElement(root, "mxCell")
        ec.set("id", edge_id)
        ec.set("value", _edge_label(e["kind"]) if cfg.edgeLabels else "")
        ec.set("style", L2R_EDGE_STYLE)
        ec.set("edge", "1")
        ec.set("source", src)
        ec.set("target", tgt)
        ec.set("parent", LAYER_TRAFFIC_EDGES)
        eg = ET.SubElement(ec, "mxGeometry")
        eg.set("relative", "1")
        eg.set("as", "geometry")

    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    out_path = cfg.out("diagram.drawio")
    cfg.ensure_output_dir()
    tree.write(str(out_path), xml_declaration=True, encoding="utf-8")
    log.info("Wrote %s (L2R mode)", out_path)

    cfg.out("icons_used.json").write_text(json.dumps(icons_used, indent=2, sort_keys=True))
    assets_dir = Path(__file__).parent.parent.parent / "assets"
    _rebuild_fallback_library(assets_dir, msft_icons or {})
    _try_export(cfg, out_path, "svg")
    _try_export(cfg, out_path, "png")


# ---------------------------------------------------------------------------
# HUB>SPOKE layout
# ---------------------------------------------------------------------------
# HUB>SPOKE layout
# ---------------------------------------------------------------------------

HS_TIER_GAP = 80         # vertical gap between tiers
HS_VNET_H_GAP = 60       # horizontal gap between VNets within a tier
HS_VNET_PAD = 20         # padding inside a VNet container
HS_VNET_HEADER = 40      # VNet title bar height
HS_SUBNET_PAD = 15       # padding inside a subnet container
HS_SUBNET_HEADER = 30    # subnet title bar height
HS_SUBNET_V_GAP = 10     # vertical gap between stacked subnets within a VNet
HS_RESOURCE_COLS = 4     # max resource columns per subnet
HS_MIN_VNET_W = 240      # minimum VNet container width
HS_CANVAS_X = 60         # left margin
HS_CANVAS_Y = 40         # top margin

HS_ISOLATED_VNET_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;fillColor=#FFF9C4;strokeColor=#F9A825;"
    "fontColor=#4E342E;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;"
    "fontSize=13;fontStyle=1;arcSize=6;opacity=70;"
)


def layout_nodes_hub_spoke(
    nodes: List[Dict],
    edges: List[Dict],
    spacing: float = 1.0,
    subnet_colors: bool = False,
    hub_vnet_ids: Optional[set] = None,
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],  # absolute positions
    List[Dict],                             # containers
]:
    """HUB>SPOKE layout: top-down traffic flow visualization.

    Tier arrangement (top → bottom):
      1. Internet / On-Prem boundary nodes
      2. Hub VNet(s)  — contain firewall / gateway subnets
      3. Spoke VNet(s) — peered to a hub
      4. Isolated VNets  — not peered to any hub
      5. Unattached resources

    Within each VNet, subnets are stacked vertically so the diagram reads
    naturally from top to bottom.  Tier colours applied when subnet_colors=True.
    """
    s = lambda v: round(v * spacing)
    vnet_pad    = s(HS_VNET_PAD)
    vnet_header = s(HS_VNET_HEADER)
    sn_pad      = s(HS_SUBNET_PAD)
    sn_header   = s(HS_SUBNET_HEADER)
    sn_v_gap    = s(HS_SUBNET_V_GAP)
    vnet_h_gap  = s(HS_VNET_H_GAP)
    tier_gap    = s(HS_TIER_GAP)
    h_gap       = s(H_GAP)
    v_gap       = s(V_GAP)

    boundary_nodes = [n for n in nodes if n.get("type", "").startswith("__boundary__")]
    regular_nodes  = [n for n in nodes if not n.get("type", "").startswith("__boundary__")]
    boundary_ids   = {bn["id"] for bn in boundary_nodes}

    node_by_id: Dict[str, Dict] = {n["id"]: n for n in regular_nodes}
    vnet_subnets, subnet_members, unattached = _build_network_membership(regular_nodes, edges)
    unattached = [uid for uid in unattached if uid not in boundary_ids]

    if hub_vnet_ids is None:
        hub_vnet_ids = _detect_hub_vnet_ids(regular_nodes, edges)

    # Classify VNets into hub / spoke / isolated
    peered_to_hub: set = set()
    for e in edges:
        if e["kind"] == "vnet->peeredVnet":
            src = normalize_id(e["source"])
            tgt = normalize_id(e["target"])
            if src in hub_vnet_ids:
                peered_to_hub.add(tgt)
            if tgt in hub_vnet_ids:
                peered_to_hub.add(src)

    all_vnet_ids  = set(vnet_subnets.keys())
    hub_vnets     = sorted(v for v in all_vnet_ids if v in hub_vnet_ids)
    spoke_vnets   = sorted(v for v in all_vnet_ids if v in peered_to_hub and v not in hub_vnet_ids)
    isolated_vnets = sorted(v for v in all_vnet_ids if v not in hub_vnet_ids and v not in peered_to_hub)

    positions:  Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []

    def _vnet_label(vnet_id: str) -> str:
        n = node_by_id.get(vnet_id)
        return n["name"] if n else vnet_id.split("/")[-1]

    def _subnet_label(subnet_id: str) -> str:
        n = node_by_id.get(subnet_id)
        return n["name"] if n else subnet_id.split("/")[-1]

    def _layout_vnet(vnet_id: str, abs_x: int, abs_y: int, is_hub: bool, is_isolated: bool) -> Tuple[int, int]:
        """Place one VNet at (abs_x, abs_y). Returns (vnet_w, vnet_h)."""
        subnet_ids  = vnet_subnets.get(vnet_id, [])
        vnet_cid    = "hs_vnet_" + stable_id(vnet_id)
        label       = _vnet_label(vnet_id)

        if subnet_colors:
            if is_isolated:
                vnet_style = HS_ISOLATED_VNET_STYLE
            elif is_hub:
                vnet_style = _hub_vnet_style()
            else:
                vnet_style = _spoke_vnet_style()
        else:
            vnet_style = VNET_STYLE

        # Stack subnets vertically inside the VNet
        sn_rel_y     = vnet_header + vnet_pad   # starts right below title bar
        max_sn_w     = 0
        total_sn_h   = 0

        for sn_id in subnet_ids:
            members   = subnet_members.get(sn_id, [])
            sn_label  = _subnet_label(sn_id)
            sn_cid    = "hs_subnet_" + stable_id(sn_id)

            # Absolute member positions (parented to LAYER_RESOURCES)
            abs_member_x = abs_x + vnet_pad + sn_pad
            abs_member_y = abs_y + sn_rel_y + sn_header
            cols = max(1, min(HS_RESOURCE_COLS, len(members))) if members else 1
            member_pos, content_w, content_h = _grid_layout(members, abs_member_x, abs_member_y, cols, spacing=spacing)
            positions.update(member_pos)

            sn_w = max(content_w, CELL_W) + 2 * sn_pad
            sn_h = (content_h + sn_header + sn_pad) if members else (sn_header + sn_pad + CELL_H // 2)

            sn_style = ((_subnet_tier_style(sn_label) or SUBNET_STYLE) if subnet_colors else SUBNET_STYLE)
            containers.append({
                "id":     sn_cid,
                "label":  sn_label,
                "style":  sn_style,
                "x":      vnet_pad,       # relative to VNet
                "y":      sn_rel_y,       # relative to VNet
                "w":      sn_w,
                "h":      sn_h,
                "parent": vnet_cid,
            })

            max_sn_w    = max(max_sn_w, sn_w)
            sn_rel_y   += sn_h + sn_v_gap
            total_sn_h += sn_h + sn_v_gap

        if total_sn_h > 0:
            total_sn_h -= sn_v_gap  # remove trailing gap

        vnet_w = max(max_sn_w + 2 * vnet_pad, HS_MIN_VNET_W)
        vnet_h = (total_sn_h + vnet_header + 2 * vnet_pad) if subnet_ids else (vnet_header + 2 * vnet_pad + CELL_H)

        containers.append({
            "id":     vnet_cid,
            "label":  label,
            "style":  vnet_style,
            "x":      abs_x,
            "y":      abs_y,
            "w":      vnet_w,
            "h":      vnet_h,
            "parent": "1",
        })
        return vnet_w, vnet_h

    current_y = HS_CANVAS_Y

    # Tier 0: boundary nodes
    if boundary_nodes:
        for i, bn in enumerate(boundary_nodes):
            positions[bn["id"]] = (HS_CANVAS_X + i * (CELL_W + 60), current_y, CELL_W, CELL_H)
        current_y += CELL_H + tier_gap

    def _layout_tier(vnet_list: List[str], is_hub: bool, is_isolated: bool) -> int:
        """Lay out a tier of VNets horizontally. Returns the maximum VNet height."""
        cursor_x = HS_CANVAS_X
        max_h = 0
        for vnet_id in vnet_list:
            vw, vh = _layout_vnet(vnet_id, cursor_x, current_y, is_hub=is_hub, is_isolated=is_isolated)
            cursor_x += vw + vnet_h_gap
            max_h = max(max_h, vh)
        return max_h

    if hub_vnets:
        current_y += _layout_tier(hub_vnets, is_hub=True, is_isolated=False) + tier_gap

    if spoke_vnets:
        current_y += _layout_tier(spoke_vnets, is_hub=False, is_isolated=False) + tier_gap

    if isolated_vnets:
        current_y += _layout_tier(isolated_vnets, is_hub=False, is_isolated=True) + tier_gap

    # Unattached resources
    if unattached:
        ua_cid  = "hs_unattached"
        inner_x = HS_CANVAS_X + HS_VNET_PAD
        inner_y = current_y + vnet_header
        cols    = min(HS_RESOURCE_COLS, len(unattached))
        ua_pos, content_w, content_h = _grid_layout(unattached, inner_x, inner_y, cols, spacing=spacing)
        positions.update(ua_pos)
        ua_w = max(content_w, CELL_W) + 2 * HS_VNET_PAD
        ua_h = content_h + vnet_header + 2 * HS_VNET_PAD
        containers.append({
            "id":     ua_cid,
            "label":  "Other Resources",
            "style":  UNATTACHED_STYLE,
            "x":      HS_CANVAS_X,
            "y":      current_y,
            "w":      ua_w,
            "h":      ua_h,
            "parent": "1",
        })

    return positions, containers


def generate_drawio(cfg: Config) -> None:
    _validate_render_surface(cfg)
    graph_path = cfg.out("graph.json")
    if not graph_path.exists():
        raise FileNotFoundError("graph.json not found. Run 'graph' first.")
    graph = load_json_file(
        graph_path,
        context="Draw.io stage graph artifact",
        expected_type=dict,
        advice="Fix graph.json or rerun the graph stage.",
    )
    nodes: List[Dict] = graph["nodes"]
    edges: List[Dict] = graph["edges"]

    # Inject Internet / On-Premises boundary nodes
    nodes, edges = _inject_boundary_nodes(nodes, edges)
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in nodes}

    # Compact network detail mode: suppress plumbing node types and replace
    # with per-resource annotation boxes summarising NIC/Subnet/NSG/ASG/UDR.
    compact_mode = cfg.networkDetail == "compact"
    compact_hidden_ids: set = set()
    net_context_annotations: Dict[str, List[str]] = {}
    if compact_mode:
        compact_hidden_ids = {
            n["id"] for n in nodes
            if n.get("type", "").lower() in _COMPACT_HIDDEN_TYPES
        }
        net_context_annotations = _build_network_context_annotations(nodes, edges)

    # In full mode (BANDS/REGION>RG>TYPE layouts), subnets from shared VNets that
    # have no in-scope resources would appear as noise.  Compute the set of
    # "used" subnets — any subnet referenced by a direct resource->subnet edge —
    # and mark unreferenced subnets as orphaned so we can skip them.
    _subnet_placement_kinds = {
        "nic->subnet", "privateEndpoint->subnet", "webApp->subnet",
        "containerEnv->subnet", "appGw->subnet",
        "firewall->subnet", "bastion->subnet",
    }
    _used_subnet_ids: set = {
        normalize_id(e["target"])
        for e in edges
        if e["kind"] in _subnet_placement_kinds
    }
    orphaned_subnet_ids: set = {
        n["id"]
        for n in nodes
        if n.get("type", "").lower() == "microsoft.network/virtualnetworks/subnets"
        and n["id"] not in _used_subnet_ids
    }

    # Find assets dir relative to this file
    assets_dir = Path(__file__).parent.parent.parent / "assets"
    icon_map = _load_icon_map(assets_dir)
    msft_icons = _load_msft_icon_index(assets_dir)

    if cfg.diagramMode == "L2R":
        _render_l2r_mode(cfg, nodes, edges, icon_map, msft_icons)
        return

    if cfg.diagramMode == "MSFT":
        _render_msft_mode(cfg, nodes, edges, icon_map, msft_icons)
        return

    raise ValueError(f"Unsupported diagramMode: {cfg.diagramMode!r}")

    containers: List[Dict] = []
    sp = _spacing_factor(cfg.spacing)
    if cfg.layout == "VNET>SUBNET":
        hub_ids = _detect_hub_vnet_ids(nodes, edges) if cfg.subnetColors else set()
        positions, containers = layout_nodes_vnet(
            nodes, edges, spacing=sp,
            subnet_colors=cfg.subnetColors, hub_vnet_ids=hub_ids,
        )
    elif cfg.layout == "HUB>SPOKE":
        hub_ids = _detect_hub_vnet_ids(nodes, edges)
        positions, containers = layout_nodes_hub_spoke(
            nodes, edges, spacing=sp,
            subnet_colors=cfg.subnetColors, hub_vnet_ids=hub_ids,
        )
    elif cfg.layout == "SUB>REGION>RG>NET":
        positions, containers = layout_nodes_sub_rg_net_bands(nodes, edges, spacing=sp)
    else:
        positions, containers = layout_nodes(nodes, spacing=sp)
    icons_used = {"mapped": {}, "fallback": [], "unknown": []}

    # Build XML (uses shared skeleton with layers)
    mxfile, root = _build_mxfile_root(cfg)

    # Emit container group cells in topological order (parents before children)
    container_id_set: set = set()
    for cont in _topo_sort_containers(containers):
        container_id_set.add(cont["id"])
        # Top-level containers (parent="1") go on the Containers layer
        cont_parent = LAYER_CONTAINERS if cont["parent"] == "1" else cont["parent"]
        cc = ET.SubElement(root, "mxCell")
        cc.set("id", cont["id"])
        cc.set("value", cont["label"])
        cc.set("style", cont["style"])
        cc.set("vertex", "1")
        cc.set("parent", cont_parent)
        cc.set("connectable", "0")
        cg = ET.SubElement(cc, "mxGeometry")
        cg.set("x", str(cont["x"]))
        cg.set("y", str(cont["y"]))
        cg.set("width", str(cont["w"]))
        cg.set("height", str(cont["h"]))
        cg.set("as", "geometry")

    # Add subnet icon decorations inside VNET>SUBNET and HUB>SPOKE subnet containers
    if cfg.layout in {"VNET>SUBNET", "HUB>SPOKE"}:
        for cont in containers:
            if cont["id"].startswith("subnet_") or cont["id"].startswith("hs_subnet_"):
                icon_id = cont["id"] + "_icon"
                ic = ET.SubElement(root, "mxCell")
                ic.set("id", icon_id)
                ic.set("value", "")
                ic.set("style", SUBNET_ICON_DECORATION_STYLE)
                ic.set("vertex", "1")
                ic.set("parent", cont["id"])
                ig = ET.SubElement(ic, "mxGeometry")
                # Position at top-right of the subnet container
                ig.set("x", str(cont["w"] - 30))
                ig.set("y", "4")
                ig.set("width", "24")
                ig.set("height", "24")
                ig.set("as", "geometry")

    node_id_map: Dict[str, str] = {}
    container_node_id_map: Dict[str, str] = {}
    emitted_node_ids: set[str] = set()

    # In VNET>SUBNET mode, VNet and subnet nodes are represented as containers
    # so they should not also be emitted as icon cells.
    vnet_subnet_types = {
        "microsoft.network/virtualnetworks",
        "microsoft.network/virtualnetworks/subnets",
    }
    is_vnet_layout = cfg.layout in {"VNET>SUBNET", "HUB>SPOKE"}

    for node in nodes:
        nid = node["id"]
        sid = stable_id(nid)
        node_id_map[nid] = sid

        # Skip VNet/subnet nodes in VNET>SUBNET mode — shown as containers
        if is_vnet_layout and node.get("type", "") in vnet_subnet_types:
            node_type = node.get("type", "").lower()
            if node_type == "microsoft.network/virtualnetworks":
                container_node_id_map[nid] = (
                    "hs_vnet_" + stable_id(nid)
                    if cfg.layout == "HUB>SPOKE"
                    else "vnet_" + stable_id(nid)
                )
            elif node_type == "microsoft.network/virtualnetworks/subnets":
                container_node_id_map[nid] = (
                    "hs_subnet_" + stable_id(nid)
                    if cfg.layout == "HUB>SPOKE"
                    else "subnet_" + stable_id(nid)
                )
            continue

        # Skip subnets that have no in-scope resources attached (orphaned subnets
        # from shared/hub VNets that serve other teams outside the seed RGs).
        if not is_vnet_layout and nid in orphaned_subnet_ids:
            continue

        # Skip plumbing nodes in compact mode
        if compact_mode and nid in compact_hidden_ids:
            continue

        # Skip nodes with no computed position (shouldn't happen, but guard)
        if nid not in positions:
            continue

        pos = positions[nid]
        x, y, w, h = pos
        style = _node_style(node, icon_map, msft_icons)
        t = node.get("type", "")
        if style == EXTERNAL_STYLE:
            pass
        elif style == UNKNOWN_STYLE:
            if t not in icons_used["unknown"]:
                icons_used["unknown"].append(t)
        elif "data:image/svg+xml" in style:
            if t not in icons_used["fallback"]:
                icons_used["fallback"].append(t)
        else:
            icons_used["mapped"][t] = icons_used["mapped"].get(t, 0) + 1

        _emit_resource_cell(root, node, sid, style, x, y, w, h, parent_id=LAYER_RESOURCES)
        emitted_node_ids.add(sid)

    # Add UDR callouts for route tables (full mode only — compact uses annotations)
    route_table_nodes = [] if compact_mode else [
        n for n in nodes if n.get("type", "") == "microsoft.network/routetables"
    ]
    udr_edge_sources = {}
    for e in edges:
        if e["kind"] == "subnet->routeTable":
            udr_edge_sources[e["target"]] = e["source"]

    for rt_node in route_table_nodes:
        rt_id = rt_node["id"]
        routes = _get(rt_node.get("properties", {}), "routes") or []
        if not routes:
            continue
        label_lines = ["Routes:"]
        for r in routes:
            rp = _get(r, "properties") or {}
            prefix = rp.get("addressPrefix", "?")
            hop = rp.get("nextHopType", "?")
            hop_ip = rp.get("nextHopIpAddress", "")
            if hop_ip:
                hop = f"{hop}({hop_ip})"
            label_lines.append(f"  {prefix} → {hop}")
        callout_label = "\n".join(label_lines)
        subnet_pos = None
        if rt_id in udr_edge_sources:
            subnet_id = udr_edge_sources[rt_id]
            subnet_pos = positions.get(subnet_id)
        if subnet_pos is None:
            rt_pos = positions.get(rt_id, (0, 0, CELL_W, CELL_H))
            cx, cy = rt_pos[0] + rt_pos[2] + 20, rt_pos[1]
        else:
            cx, cy = subnet_pos[0] + subnet_pos[2] + 20, subnet_pos[1]

        callout_id = "udr_" + stable_id(rt_id)
        co = ET.SubElement(root, "mxCell")
        co.set("id", callout_id)
        co.set("value", callout_label)
        co.set("style", UDR_CALLOUT_STYLE)
        co.set("vertex", "1")
        co.set("parent", LAYER_LABELS)
        cog = ET.SubElement(co, "mxGeometry")
        cog.set("x", str(cx))
        cog.set("y", str(cy))
        cog.set("width", "180")
        cog.set("height", str(max(60, 20 * len(label_lines))))
        cog.set("as", "geometry")

        # Attach callout to route table node with udr edge
        rt_sid = node_id_map.get(rt_id)
        if rt_sid:
            edge_id = "udr_edge_" + stable_id(rt_id)
            ec = ET.SubElement(root, "mxCell")
            ec.set("id", edge_id)
            ec.set("value", "UDR")
            ec.set("style", EDGE_STYLE_ASSOCIATION)
            ec.set("edge", "1")
            ec.set("source", rt_sid)
            ec.set("target", callout_id)
            ec.set("parent", LAYER_ASSOC_EDGES)
            eg = ET.SubElement(ec, "mxGeometry")
            eg.set("relative", "1")
            eg.set("as", "geometry")

    # Add NSG rule callouts (full mode only — compact uses annotations)
    nsg_summaries = {} if compact_mode else extract_nsg_summaries(nodes, edges)
    for nsg_id in sorted(nsg_summaries.keys(), key=lambda s: (
        (node_by_id.get(s) or {}).get("name", ""), s,
    )):
        summary = nsg_summaries[nsg_id]
        if not summary["rules"]:
            continue
        nsg_sid = node_id_map.get(nsg_id)
        if not nsg_sid:
            continue
        nsg_pos = positions.get(nsg_id)
        if not nsg_pos:
            continue

        panel_label = _format_nsg_panel_label(summary)
        panel_id = "nsg_panel_" + stable_id(nsg_id)
        n_lines = panel_label.count("\n") + 1
        panel_w = 220
        panel_h = max(50, 16 * n_lines + 12)

        # Position below the NSG node
        cx = nsg_pos[0]
        cy = nsg_pos[1] + nsg_pos[3] + 20

        pc = ET.SubElement(root, "mxCell")
        pc.set("id", panel_id)
        pc.set("value", panel_label)
        pc.set("style", NSG_CALLOUT_STYLE)
        pc.set("vertex", "1")
        pc.set("parent", LAYER_LABELS)
        pg = ET.SubElement(pc, "mxGeometry")
        pg.set("x", str(cx))
        pg.set("y", str(cy))
        pg.set("width", str(panel_w))
        pg.set("height", str(panel_h))
        pg.set("as", "geometry")

        # Connect NSG to its panel
        nsg_edge_id = "nsg_edge_" + stable_id(nsg_id)
        ne = ET.SubElement(root, "mxCell")
        ne.set("id", nsg_edge_id)
        ne.set("value", "")
        ne.set("style", EDGE_STYLE_ASSOCIATION)
        ne.set("edge", "1")
        ne.set("source", nsg_sid)
        ne.set("target", panel_id)
        ne.set("parent", LAYER_ASSOC_EDGES)
        neg = ET.SubElement(ne, "mxGeometry")
        neg.set("relative", "1")
        neg.set("as", "geometry")

    # Add attribute info boxes for resources that have metadata
    ATTR_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;strokeColor=#9673a6;dashed=1;strokeWidth=2;"
    for node in nodes:
        attrs = node.get("attributes", [])
        if not attrs:
            continue
        nid = node["id"]
        sid = node_id_map.get(nid)
        if not sid:
            continue
        pos = positions.get(nid)
        if not pos:
            continue
        x, y, w, h = pos
        # Place attribute box to the left of the resource icon
        box_w = 180
        line_h = 16
        box_h = max(40, 12 + line_h * len(attrs))
        box_x = x - box_w - 10
        box_y = y

        attr_label = "\n".join(attrs)
        attr_id = "attr_" + stable_id(nid)
        ab = ET.SubElement(root, "mxCell")
        ab.set("id", attr_id)
        ab.set("value", attr_label)
        ab.set("style", ATTR_BOX_STYLE)
        ab.set("vertex", "1")
        ab.set("parent", LAYER_LABELS)
        abg = ET.SubElement(ab, "mxGeometry")
        abg.set("x", str(box_x))
        abg.set("y", str(box_y))
        abg.set("width", str(box_w))
        abg.set("height", str(box_h))
        abg.set("as", "geometry")

        # Connect attribute box to resource
        ae_id = "attr_edge_" + stable_id(nid)
        ae = ET.SubElement(root, "mxCell")
        ae.set("id", ae_id)
        ae.set("value", "")
        ae.set("style", ATTR_EDGE_STYLE)
        ae.set("edge", "1")
        ae.set("source", attr_id)
        ae.set("target", sid)
        ae.set("parent", LAYER_ASSOC_EDGES)
        aeg = ET.SubElement(ae, "mxGeometry")
        aeg.set("relative", "1")
        aeg.set("as", "geometry")

    # Compact mode: network context annotation boxes (one per compute resource)
    if compact_mode:
        for nid, lines in net_context_annotations.items():
            sid = node_id_map.get(nid)
            if not sid:
                continue
            pos = positions.get(nid)
            if not pos:
                continue
            x, y, w, h = pos
            line_h = 16
            box_w = 210
            box_h = max(44, 10 + line_h * len(lines))
            # Place annotation to the right of the resource icon
            box_x = x + w + 12
            box_y = y

            ann_id = "netctx_" + stable_id(nid)
            ac = ET.SubElement(root, "mxCell")
            ac.set("id", ann_id)
            ac.set("value", "\n".join(lines))
            ac.set("style", NET_CONTEXT_STYLE)
            ac.set("vertex", "1")
            ac.set("parent", LAYER_LABELS)
            acg = ET.SubElement(ac, "mxGeometry")
            acg.set("x", str(box_x))
            acg.set("y", str(box_y))
            acg.set("width", str(box_w))
            acg.set("height", str(box_h))
            acg.set("as", "geometry")

            # Dashed connector from resource to annotation
            ae_id = "netctx_edge_" + stable_id(nid)
            ae = ET.SubElement(root, "mxCell")
            ae.set("id", ae_id)
            ae.set("value", "")
            ae.set("style", NET_CONTEXT_EDGE_STYLE)
            ae.set("edge", "1")
            ae.set("source", sid)
            ae.set("target", ann_id)
            ae.set("parent", LAYER_ASSOC_EDGES)
            aeg = ET.SubElement(ae, "mxGeometry")
            aeg.set("relative", "1")
            aeg.set("as", "geometry")

    # Add edges with differentiated styles
    valid_edge_endpoint_ids = container_id_set | emitted_node_ids
    for i, e in enumerate(edges):
        src = container_node_id_map.get(e["source"]) or node_id_map.get(e["source"])
        tgt = container_node_id_map.get(e["target"]) or node_id_map.get(e["target"])
        if not src or not tgt:
            continue
        # In compact mode skip edges that touch hidden plumbing nodes
        if compact_mode and (e["source"] in compact_hidden_ids or e["target"] in compact_hidden_ids):
            continue
        # Skip edges that touch orphaned (unscoped) subnets
        if not is_vnet_layout and (e["source"] in orphaned_subnet_ids or e["target"] in orphaned_subnet_ids):
            continue
        if src not in valid_edge_endpoint_ids or tgt not in valid_edge_endpoint_ids:
            continue
        if e["kind"] == "subnet->routeTable":
            continue  # shown via callout
        edge_id = f"e_{stable_id(e['source'] + e['target'] + e['kind'])}"
        ec = ET.SubElement(root, "mxCell")
        ec.set("id", edge_id)
        ec.set("value", _edge_label(e["kind"]) if cfg.edgeLabels else "")
        ec.set("style", _edge_style(e["kind"], msft=False))
        ec.set("edge", "1")
        ec.set("source", src)
        ec.set("target", tgt)
        ec.set("parent", _edge_layer(e["kind"]))
        eg = ET.SubElement(ec, "mxGeometry")
        eg.set("relative", "1")
        eg.set("as", "geometry")

    # Write diagram.drawio
    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    out_path = cfg.out("diagram.drawio")
    cfg.ensure_output_dir()
    tree.write(str(out_path), xml_declaration=True, encoding="utf-8")
    log.info("Wrote %s", out_path)

    # Write icons_used.json
    cfg.out("icons_used.json").write_text(json.dumps(icons_used, indent=2, sort_keys=True))

    # Regenerate fallback library whenever MSFT icons are present
    _rebuild_fallback_library(assets_dir, msft_icons)

    # Optional image exports
    _try_export(cfg, out_path, "svg")
    _try_export(cfg, out_path, "png")


# ---------------------------------------------------------------------------
# UDR / Route Table helpers
# ---------------------------------------------------------------------------

MAX_UDR_ROUTES_SHOWN = 8


def extract_route_summaries(
    nodes: List[Dict], edges: List[Dict],
) -> Tuple[
    Dict[str, Dict],            # subnet_id -> {rt_name, rt_id, routes: [...]}
    Dict[str, List[str]],       # vnet_id -> [subnet_names_with_udr]
]:
    """Extract UDR summaries for subnets and VNets.

    Returns:
      subnet_udr: subnet_id -> route table summary dict
      vnet_udr_rollup: vnet_id -> list of subnet names that have UDRs
    """
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in nodes}

    # Build subnet -> routeTable mapping from edges
    subnet_to_rt: Dict[str, str] = {}
    for e in edges:
        if e["kind"] == "subnet->routeTable":
            subnet_to_rt[normalize_id(e["source"])] = normalize_id(e["target"])

    # Build subnet -> vnet mapping
    subnet_to_vnet: Dict[str, str] = {}
    for e in edges:
        if e["kind"] == "subnet->vnet":
            subnet_to_vnet[normalize_id(e["source"])] = normalize_id(e["target"])
    for n in nodes:
        if n["type"] == "microsoft.network/virtualnetworks/subnets":
            nid = n["id"]
            if nid not in subnet_to_vnet and "/subnets/" in nid:
                subnet_to_vnet[nid] = nid.split("/subnets/")[0]

    subnet_udr: Dict[str, Dict] = {}
    vnet_udr_subnets: Dict[str, List[str]] = defaultdict(list)

    for subnet_id in sorted(subnet_to_rt.keys()):
        rt_id = subnet_to_rt[subnet_id]
        rt_node = node_by_id.get(rt_id)
        if not rt_node:
            continue

        rt_name = rt_node.get("name", rt_id.split("/")[-1])
        raw_routes = _get(rt_node.get("properties", {}), "routes") or []

        # Sort routes deterministically
        routes = []
        for r in raw_routes:
            rp = _get(r, "properties") or {}
            routes.append({
                "name": r.get("name", ""),
                "addressPrefix": rp.get("addressPrefix", "?"),
                "nextHopType": rp.get("nextHopType", "?"),
                "nextHopIpAddress": rp.get("nextHopIpAddress", ""),
            })
        routes.sort(key=lambda r: (
            r["addressPrefix"], r["nextHopType"],
            r["nextHopIpAddress"], r["name"],
        ))

        subnet_udr[subnet_id] = {
            "rt_name": rt_name,
            "rt_id": rt_id,
            "routes": routes,
        }

        # VNet rollup
        vnet_id = subnet_to_vnet.get(subnet_id)
        subnet_name = node_by_id.get(subnet_id, {}).get("name", subnet_id.split("/")[-1])
        if vnet_id:
            vnet_udr_subnets[vnet_id].append(subnet_name)

    # Sort VNet rollup lists
    for vid in vnet_udr_subnets:
        vnet_udr_subnets[vid].sort()

    return subnet_udr, dict(vnet_udr_subnets)


MAX_NSG_RULES_SHOWN = 6


def extract_nsg_summaries(
    nodes: List[Dict], edges: List[Dict],
) -> Dict[str, Dict]:
    """Extract NSG rule summaries for NSG nodes.

    Returns:
      nsg_id -> {nsg_name, rules: [{name, priority, direction, access, protocol,
                                     src, dst, dstPort}]}
    """
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in nodes}

    # Identify which subnets/NICs reference which NSGs
    nsg_refs: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        if e["kind"] in ("subnet->nsg", "nic->nsg"):
            nsg_id = normalize_id(e["target"])
            src_name = node_by_id.get(normalize_id(e["source"]), {}).get("name", "")
            if src_name:
                nsg_refs[nsg_id].append(src_name)

    nsg_summaries: Dict[str, Dict] = {}

    # Build ASG ID -> name lookup for resolving ASG references in rules
    asg_name_map: Dict[str, str] = {}
    for n in nodes:
        if n["type"] == "microsoft.network/applicationsecuritygroups":
            asg_name_map[n["id"]] = n.get("name", n["id"].split("/")[-1])

    for n in nodes:
        if n["type"] != "microsoft.network/networksecuritygroups":
            continue
        nid = n["id"]
        raw_rules = _get(n.get("properties", {}), "securityRules") or []
        rules = []
        for r in raw_rules:
            rp = _get(r, "properties") or {}
            # Resolve source: prefer ASG names over address prefix
            src_asgs = rp.get("sourceApplicationSecurityGroups") or []
            if src_asgs:
                src = ",".join(
                    asg_name_map.get(normalize_id(a.get("id", "")), a.get("id", "").split("/")[-1])
                    for a in src_asgs
                )
            else:
                src = rp.get("sourceAddressPrefix", "*")
            # Resolve destination: prefer ASG names over address prefix
            dst_asgs = rp.get("destinationApplicationSecurityGroups") or []
            if dst_asgs:
                dst = ",".join(
                    asg_name_map.get(normalize_id(a.get("id", "")), a.get("id", "").split("/")[-1])
                    for a in dst_asgs
                )
            else:
                dst = rp.get("destinationAddressPrefix", "*")
            rules.append({
                "name": r.get("name", ""),
                "priority": rp.get("priority", 0),
                "direction": rp.get("direction", ""),
                "access": rp.get("access", ""),
                "protocol": rp.get("protocol", "*"),
                "src": src,
                "dst": dst,
                "dstPort": rp.get("destinationPortRange", "*"),
            })
        rules.sort(key=lambda r: (r["direction"], r["priority"], r["name"]))

        nsg_summaries[nid] = {
            "nsg_name": n.get("name", nid.split("/")[-1]),
            "rules": rules,
            "attached_to": sorted(set(nsg_refs.get(nid, []))),
        }

    return nsg_summaries


def _format_nsg_panel_label(summary: Dict) -> str:
    """Build the text label for an NSG panel node."""
    lines = [f"NSG: {summary['nsg_name']}"]
    if summary.get("attached_to"):
        lines.append(f"Attached: {', '.join(summary['attached_to'])}")
    rules = summary["rules"]
    shown = rules[:MAX_NSG_RULES_SHOWN]
    for r in shown:
        icon = "\u2705" if r["access"] == "Allow" else "\u274c"
        lines.append(
            f"{icon} {r['direction'][:2]} P{r['priority']} "
            f"{r['protocol']} {r['src']}\u2192{r['dst']}:{r['dstPort']}"
        )
    remaining = len(rules) - len(shown)
    if remaining > 0:
        lines.append(f"\u2026(+{remaining} more)")
    return "\n".join(lines)


def _format_udr_panel_label(summary: Dict) -> str:
    """Build the text label for a UDR panel node."""
    lines = [f"UDR: {summary['rt_name']}"]
    routes = summary["routes"]
    shown = routes[:MAX_UDR_ROUTES_SHOWN]
    for r in shown:
        hop = r["nextHopType"]
        if r["nextHopIpAddress"]:
            hop = f"{hop} ({r['nextHopIpAddress']})"
        lines.append(f"{r['addressPrefix']} \u2192 {hop}")
    remaining = len(routes) - len(shown)
    if remaining > 0:
        lines.append(f"\u2026(+{remaining} more)")
    return "\n".join(lines)


# Layer IDs for draw.io layer separation
LAYER_CONTAINERS = "layer_containers"
LAYER_RESOURCES = "layer_resources"
LAYER_TRAFFIC_EDGES = "layer_traffic_edges"
LAYER_ASSOC_EDGES = "layer_assoc_edges"
LAYER_LABELS = "layer_labels"

_LAYERS = [
    (LAYER_CONTAINERS, "Containers"),
    (LAYER_RESOURCES, "Resources"),
    (LAYER_TRAFFIC_EDGES, "Traffic Edges"),
    (LAYER_ASSOC_EDGES, "Association Edges"),
    (LAYER_LABELS, "Labels"),
]

_LAYER_ROOT_IDS = {"0", "1", LAYER_CONTAINERS, LAYER_RESOURCES,
                   LAYER_TRAFFIC_EDGES, LAYER_ASSOC_EDGES, LAYER_LABELS}


def _edge_layer(kind: str) -> str:
    """Return the layer ID for an edge based on its kind."""
    return LAYER_ASSOC_EDGES if kind in _ASSOCIATION_EDGE_KINDS else LAYER_TRAFFIC_EDGES


def _topo_sort_containers(containers: List[Dict]) -> List[Dict]:
    """Return containers sorted so that parent containers appear before their children."""
    by_id = {c["id"]: c for c in containers}
    result: List[Dict] = []
    visited: set = set()

    def visit(c_id: str) -> None:
        if c_id in visited:
            return
        c = by_id[c_id]
        parent = c.get("parent", "1")
        if parent not in _LAYER_ROOT_IDS and parent in by_id:
            visit(parent)
        visited.add(c_id)
        result.append(c)

    for c in containers:
        visit(c["id"])
    return result


def _emit_resource_cell(
    root: ET.Element, node: Dict, sid: str, style: str,
    x: int, y: int, w: int, h: int, parent_id: str = "1",
) -> None:
    """Emit a resource node as a UserObject with ARM metadata + mxCell child.

    Stores ARM ID, type, RG, subscription, and location as data-* attributes
    on the UserObject element for downstream tooling or manual inspection.
    The label (value) is set on the UserObject; draw.io reads it from there.
    """
    uo = ET.SubElement(root, "UserObject")
    label = node.get("displayName") or node.get("name", sid)
    if node.get("isExternal") and "(external)" not in label.lower():
        label = f"{label} (external)"
    uo.set("label", label)
    uo.set("id", sid)
    uo.set("data-arm-id", node.get("id", ""))
    uo.set("data-type", node.get("type", ""))
    uo.set("data-resource-group", node.get("resourceGroup", ""))
    uo.set("data-subscription", node.get("subscriptionId", ""))
    uo.set("data-location", node.get("location", ""))

    cell = ET.SubElement(uo, "mxCell")
    cell.set("style", style)
    cell.set("vertex", "1")
    # Also set value on mxCell for backwards compatibility with test queries
    cell.set("value", label)
    cell.set("parent", parent_id)
    geo = ET.SubElement(cell, "mxGeometry")
    geo.set("x", str(x))
    geo.set("y", str(y))
    geo.set("width", str(w))
    geo.set("height", str(h))
    geo.set("as", "geometry")


def _build_mxfile_root(cfg: Config) -> Tuple[ET.Element, ET.Element]:
    """Create the mxfile/diagram/mxGraphModel/root skeleton and return (mxfile, root).

    Creates named layers: Containers, Resources, Traffic Edges, Association Edges, Labels.
    All layers are children of cell "0" (like cell "1").
    """
    mxfile = ET.Element("mxfile")
    diagram = ET.SubElement(mxfile, "diagram")
    diagram.set("name", cfg.app)
    diagram.set("id", stable_id(cfg.app))
    model = ET.SubElement(diagram, "mxGraphModel")
    for k, v in [("dx", "1422"), ("dy", "762"), ("grid", "1"), ("gridSize", "10"),
                 ("guides", "1"), ("tooltips", "1"), ("connect", "1"), ("arrows", "1"),
                 ("fold", "1"), ("page", "1"), ("pageScale", "1"),
                 ("pageWidth", "1654"), ("pageHeight", "1169"),
                 ("math", "0"), ("shadow", "0")]:
        model.set(k, v)
    root = ET.SubElement(model, "root")
    cell0 = ET.SubElement(root, "mxCell")
    cell0.set("id", "0")
    # Default layer (backwards compatible — used as fallback parent)
    cell1 = ET.SubElement(root, "mxCell")
    cell1.set("id", "1")
    cell1.set("parent", "0")
    # Named layers
    for layer_id, layer_name in _LAYERS:
        lc = ET.SubElement(root, "mxCell")
        lc.set("id", layer_id)
        lc.set("value", layer_name)
        lc.set("parent", "0")
    return mxfile, root


def _render_msft_mode(
    cfg: Config,
    nodes: List[Dict],
    edges: List[Dict],
    icon_map: Dict[str, str],
    msft_icons: Optional[Dict[str, Path]] = None,
) -> None:
    """Render the diagram in MSFT (Microsoft Architecture Center) style."""
    sp = _spacing_factor(cfg.spacing)
    positions, containers, type_headers, node_parents = layout_nodes_sub_rg_net(
        nodes, edges, spacing=sp, group_by_tag=cfg.groupByTag, layout_magic=cfg.layoutMagic,
    )
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in nodes}
    hub_roles = _hub_role_map(nodes, edges)
    container_positions = _container_absolute_positions(containers)

    icons_used: Dict[str, Any] = {"mapped": {}, "fallback": [], "unknown": []}
    mxfile, root = _build_mxfile_root(cfg)

    for cont in _topo_sort_containers(containers):
        cont_parent = LAYER_CONTAINERS if cont["parent"] == "1" else cont["parent"]
        cc = ET.SubElement(root, "mxCell")
        cc.set("id", cont["id"])
        cc.set("value", cont["label"])
        cc.set("style", cont["style"])
        cc.set("vertex", "1")
        cc.set("parent", cont_parent)
        cc.set("connectable", "0")
        cg = ET.SubElement(cc, "mxGeometry")
        cg.set("x", str(cont["x"]))
        cg.set("y", str(cont["y"]))
        cg.set("width", str(cont["w"]))
        cg.set("height", str(cont["h"]))
        cg.set("as", "geometry")

    for th in type_headers:
        abs_x, abs_y = _absolute_child_position(th["x"], th["y"], th["parent"], container_positions)
        tc = ET.SubElement(root, "mxCell")
        tc.set("id", th["id"])
        tc.set("value", th["label"])
        tc.set("style", th.get("style", MSFT_TYPE_HEADER_STYLE))
        tc.set("vertex", "1")
        tc.set("parent", LAYER_LABELS)
        tg = ET.SubElement(tc, "mxGeometry")
        tg.set("x", str(abs_x))
        tg.set("y", str(abs_y))
        tg.set("width", str(th["w"]))
        tg.set("height", str(th["h"]))
        tg.set("as", "geometry")

    node_id_map: Dict[str, str] = {}
    visible_node_ids = set(positions.keys())
    for node in nodes:
        nid = node["id"]
        sid = stable_id(nid)
        node_id_map[nid] = sid
        if nid not in positions:
            continue
        parent_id = node_parents.get(nid, "1")
        abs_x, abs_y = _absolute_child_position(*positions[nid][:2], parent_id, container_positions)
        w, h = positions[nid][2], positions[nid][3]
        render_node = dict(node)
        role = hub_roles.get(nid)
        if role and render_node.get("type", "").lower() == "microsoft.network/virtualnetworks":
            render_node["displayName"] = f"{render_node.get('name', nid)} ({role})"
        style = _node_style(render_node, icon_map, msft_icons)
        t = render_node.get("type", "")
        if style == UNKNOWN_STYLE:
            if t not in icons_used["unknown"]:
                icons_used["unknown"].append(t)
        elif "data:image/svg+xml" in style:
            if t not in icons_used["fallback"]:
                icons_used["fallback"].append(t)
        elif style != EXTERNAL_STYLE:
            icons_used["mapped"][t] = icons_used["mapped"].get(t, 0) + 1
        _emit_resource_cell(root, render_node, sid, style, abs_x, abs_y, w, h, parent_id=LAYER_RESOURCES)

    _emit_resource_metadata_boxes(root, nodes, node_id_map, positions, node_parents, container_positions)

    subnet_udr, _ = extract_route_summaries(nodes, edges)
    panel_base_x = max((c["x"] + c["w"] for c in containers if c["parent"] == "1"), default=0) + 40
    panel_cursor_y = MSFT_REGION_PAD
    for subnet_id in sorted(subnet_udr.keys(), key=lambda s: ((node_by_id.get(s) or {}).get("name", ""), s)):
        summary = subnet_udr[subnet_id]
        panel_label = _format_udr_panel_label(summary)
        panel_id = "msft_udr_" + stable_id(subnet_id)
        panel_h = max(60, 18 * (panel_label.count("\n") + 1) + 16)
        pc = ET.SubElement(root, "mxCell")
        pc.set("id", panel_id)
        pc.set("value", panel_label)
        pc.set("style", MSFT_UDR_PANEL_STYLE)
        pc.set("vertex", "1")
        pc.set("parent", LAYER_LABELS)
        pg = ET.SubElement(pc, "mxGeometry")
        pg.set("x", str(panel_base_x))
        pg.set("y", str(panel_cursor_y))
        pg.set("width", str(220))
        pg.set("height", str(panel_h))
        pg.set("as", "geometry")
        subnet_sid = node_id_map.get(subnet_id)
        if subnet_sid:
            ue = ET.SubElement(root, "mxCell")
            ue.set("id", "msft_udr_edge_" + stable_id(subnet_id))
            ue.set("value", "udr_detail")
            ue.set("style", _edge_style("udr_detail", msft=True))
            ue.set("edge", "1")
            ue.set("source", subnet_sid)
            ue.set("target", panel_id)
            ue.set("parent", LAYER_ASSOC_EDGES)
            ueg = ET.SubElement(ue, "mxGeometry")
            ueg.set("relative", "1")
            ueg.set("as", "geometry")
        panel_cursor_y += panel_h + 15

    nsg_summaries = extract_nsg_summaries(nodes, edges)
    nsg_panel_x = panel_base_x + 240
    nsg_cursor_y = MSFT_REGION_PAD
    for nsg_id in sorted(nsg_summaries.keys(), key=lambda s: ((node_by_id.get(s) or {}).get("name", ""), s)):
        summary = nsg_summaries[nsg_id]
        if not summary["rules"]:
            continue
        panel_label = _format_nsg_panel_label(summary)
        panel_id = "msft_nsg_" + stable_id(nsg_id)
        panel_h = max(60, 18 * (panel_label.count("\n") + 1) + 16)
        pc = ET.SubElement(root, "mxCell")
        pc.set("id", panel_id)
        pc.set("value", panel_label)
        pc.set("style", MSFT_NSG_PANEL_STYLE)
        pc.set("vertex", "1")
        pc.set("parent", LAYER_LABELS)
        pg = ET.SubElement(pc, "mxGeometry")
        pg.set("x", str(nsg_panel_x))
        pg.set("y", str(nsg_cursor_y))
        pg.set("width", str(260))
        pg.set("height", str(panel_h))
        pg.set("as", "geometry")
        nsg_sid = node_id_map.get(nsg_id)
        if nsg_sid:
            ne = ET.SubElement(root, "mxCell")
            ne.set("id", "msft_nsg_edge_" + stable_id(nsg_id))
            ne.set("value", "nsg_detail")
            ne.set("style", _edge_style("nsg_detail", msft=True))
            ne.set("edge", "1")
            ne.set("source", nsg_sid)
            ne.set("target", panel_id)
            ne.set("parent", LAYER_ASSOC_EDGES)
            neg = ET.SubElement(ne, "mxGeometry")
            neg.set("relative", "1")
            neg.set("as", "geometry")
        nsg_cursor_y += panel_h + 15

    panel_stack_y = max(panel_cursor_y, nsg_cursor_y) + 10
    inventory_lines = _diagram_inventory_lines(nodes, visible_node_ids)
    if inventory_lines:
        inventory_h = _emit_text_panel(
            root,
            "msft_inventory_box",
            inventory_lines,
            x=panel_base_x,
            y=panel_stack_y,
            width=320,
            style=L2R_CONTEXT_BOX_STYLE,
        )
        panel_stack_y += inventory_h + 10
    _emit_legend_box(root, "msft_network_legend", panel_base_x, panel_stack_y)

    for e in edges:
        src = node_id_map.get(e["source"])
        tgt = node_id_map.get(e["target"])
        if not src or not tgt:
            continue
        if e["kind"] == "subnet->routeTable":
            continue
        edge_id = f"e_{stable_id(e['source'] + e['target'] + e['kind'])}"
        ec = ET.SubElement(root, "mxCell")
        ec.set("id", edge_id)
        ec.set("value", _edge_label(e["kind"]) if cfg.edgeLabels else "")
        ec.set("style", _edge_style(e["kind"], msft=True))
        ec.set("edge", "1")
        ec.set("source", src)
        ec.set("target", tgt)
        ec.set("parent", _edge_layer(e["kind"]))
        eg = ET.SubElement(ec, "mxGeometry")
        eg.set("relative", "1")
        eg.set("as", "geometry")

    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    out_path = cfg.out("diagram.drawio")
    cfg.ensure_output_dir()
    tree.write(str(out_path), xml_declaration=True, encoding="utf-8")
    log.info("Wrote %s (MSFT mode)", out_path)

    cfg.out("icons_used.json").write_text(json.dumps(icons_used, indent=2, sort_keys=True))
    assets_dir = Path(__file__).parent.parent.parent / "assets"
    _rebuild_fallback_library(assets_dir, msft_icons or {})
    _try_export(cfg, out_path, "svg")
    _try_export(cfg, out_path, "png")


def _try_export(cfg: Config, drawio_path: Path, fmt: str) -> None:
    import shutil
    if not shutil.which("drawio"):
        log.debug("drawio CLI not found; skipping %s export.", fmt)
        return
    out = cfg.out(f"diagram.{fmt}")
    cmd = ["drawio", "--export", "--format", fmt, "--output", str(out), str(drawio_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        log.info("Exported %s to %s", fmt.upper(), out)
    else:
        log.warning("%s export failed: %s", fmt.upper(), result.stderr.strip())
