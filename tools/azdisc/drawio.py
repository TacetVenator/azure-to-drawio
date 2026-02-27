"""Draw.io diagram generator."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .util import normalize_id, stable_id

log = logging.getLogger(__name__)

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

# Default style strings
EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;exitX=0.5;exitY=1;exitDx=0;exitDy=0;"
GROUP_STYLE = "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];shape=mxgraph.azure.groups.subscription;labelPosition=top;verticalLabelPosition=top;align=center;verticalAlign=bottom;fillColor=#dae8fc;strokeColor=#6c8ebf;fontColor=#000000;"
RG_STYLE = "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];shape=mxgraph.azure.groups.resource_group;labelPosition=top;verticalLabelPosition=top;align=center;verticalAlign=bottom;fillColor=#fff2cc;strokeColor=#d6b656;fontColor=#000000;"
UNKNOWN_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
EXTERNAL_STYLE = "ellipse;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;verticalLabelPosition=bottom;verticalAlign=top;align=center;"
UDR_CALLOUT_STYLE = "shape=callout;fillColor=#fff2cc;strokeColor=#d6b656;align=left;verticalAlign=top;spacingLeft=5;fontSize=10;"
ATTR_BOX_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;fontSize=10;"
VNET_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;fontSize=13;fontStyle=1;arcSize=6;opacity=50;"
SUBNET_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;verticalAlign=top;align=left;spacingLeft=8;spacingTop=4;fontSize=11;dashed=1;dashPattern=5 5;arcSize=8;opacity=60;"
UNATTACHED_STYLE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#999999;verticalAlign=top;align=left;spacingLeft=10;spacingTop=5;fontSize=13;fontStyle=1;arcSize=6;dashed=1;dashPattern=8 4;"


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
        return json.loads(icon_map_path.read_text())
    return {}


def _node_style(node: Dict, icon_map: Dict[str, str]) -> str:
    if node.get("isExternal"):
        return EXTERNAL_STYLE
    t = node.get("type", "")
    style = icon_map.get(t)
    if style:
        return style
    # Try partial match on type suffix
    parts = t.split("/")
    if len(parts) >= 2:
        style = icon_map.get(parts[-1])
        if style:
            return style
    return UNKNOWN_STYLE


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


def layout_nodes(nodes: List[Dict]) -> Dict[str, Tuple[int, int, int, int]]:
    """
    Compute deterministic (x, y, w, h) positions.
    Hierarchy: REGION > RG > TYPE band (left-to-right grid with wrapping).
    Returns dict: node_id -> (x, y, w, h).
    """
    # Group by (region, rg, type)
    from collections import defaultdict
    groups: Dict[Tuple[str, str, str], List[Dict]] = defaultdict(list)
    for n in nodes:
        key = (n.get("location", ""), n.get("resourceGroup", ""), n.get("type", ""))
        groups[key].append(n)

    # Sort within each group deterministically
    for key in groups:
        groups[key].sort(key=lambda n: (n.get("name", ""), n["id"]))

    # Organize by region -> rg
    region_rg: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))
    for key in sorted(groups.keys()):
        region, rg, _ = key
        region_rg[region][rg].append(key)

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    region_y = REGION_PADDING

    for region in sorted(region_rg.keys()):
        rg_x = REGION_PADDING
        rg_max_height = 0

        for rg in sorted(region_rg[region].keys()):
            type_keys = region_rg[region][rg]
            type_y = RG_PADDING
            rg_width = 0

            for key in sorted(type_keys):
                nodes_in_band = groups[key]
                rows = (len(nodes_in_band) + COLS_PER_ROW - 1) // COLS_PER_ROW
                band_w = min(len(nodes_in_band), COLS_PER_ROW) * (CELL_W + H_GAP) - H_GAP
                for i, node in enumerate(nodes_in_band):
                    col = i % COLS_PER_ROW
                    row = i // COLS_PER_ROW
                    nx = rg_x + RG_PADDING + col * (CELL_W + H_GAP)
                    ny = region_y + type_y + row * (CELL_H + V_GAP)
                    positions[node["id"]] = (nx, ny, CELL_W, CELL_H)
                type_y += rows * (CELL_H + V_GAP) + TYPE_V_GAP
                rg_width = max(rg_width, band_w)

            rg_height = type_y + RG_PADDING
            rg_max_height = max(rg_max_height, rg_height)
            rg_x += rg_width + 2 * RG_PADDING + H_GAP

        region_y += rg_max_height + REGION_PADDING

    return positions


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
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in nodes}

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

    # Sort members deterministically
    for sid in subnet_members:
        subnet_members[sid].sort()

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
) -> Tuple[Dict[str, Tuple[int, int, int, int]], int, int]:
    """Lay out a list of node IDs in a grid, returning positions and content size."""
    positions: Dict[str, Tuple[int, int, int, int]] = {}
    if not node_ids:
        return positions, 0, 0
    rows = (len(node_ids) + cols - 1) // cols
    for i, nid in enumerate(node_ids):
        col = i % cols
        row = i // cols
        x = start_x + col * (CELL_W + H_GAP)
        y = start_y + row * (CELL_H + V_GAP)
        positions[nid] = (x, y, CELL_W, CELL_H)
    content_w = min(len(node_ids), cols) * (CELL_W + H_GAP) - H_GAP
    content_h = rows * (CELL_H + V_GAP) - V_GAP
    return positions, content_w, content_h


def layout_nodes_vnet(
    nodes: List[Dict], edges: List[Dict],
) -> Tuple[
    Dict[str, Tuple[int, int, int, int]],    # node positions
    List[Dict],                                # container rects for VNets/subnets
]:
    """Compute positions for the VNET>SUBNET layout mode.

    Returns:
      positions: node_id -> (x, y, w, h)
      containers: list of dicts with keys: id, label, style, x, y, w, h, parent
    """
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in nodes}
    vnet_subnets, subnet_members, unattached = _build_network_membership(nodes, edges)

    positions: Dict[str, Tuple[int, int, int, int]] = {}
    containers: List[Dict] = []

    cursor_x = REGION_PADDING

    # Sort VNets deterministically
    all_vnets = sorted(vnet_subnets.keys())

    for vnet_id in all_vnets:
        subnet_ids = vnet_subnets[vnet_id]
        vnet_label = node_by_id[vnet_id]["name"] if vnet_id in node_by_id else vnet_id.split("/")[-1]
        vnet_container_id = "vnet_" + stable_id(vnet_id)

        vnet_inner_x = cursor_x + VNET_PADDING
        vnet_inner_y = REGION_PADDING + VNET_HEADER
        subnet_cursor_x = vnet_inner_x
        vnet_content_h = 0

        for subnet_id in subnet_ids:
            members = subnet_members.get(subnet_id, [])
            subnet_label = node_by_id[subnet_id]["name"] if subnet_id in node_by_id else subnet_id.split("/")[-1]
            subnet_container_id = "subnet_" + stable_id(subnet_id)

            # Layout member nodes inside this subnet
            inner_x = subnet_cursor_x + SUBNET_PADDING
            inner_y = vnet_inner_y + SUBNET_HEADER
            cols = max(2, min(COLS_PER_ROW, len(members))) if members else 2
            member_pos, content_w, content_h = _grid_layout(members, inner_x, inner_y, cols)
            positions.update(member_pos)

            # Subnet box dimensions
            subnet_w = max(content_w, CELL_W) + 2 * SUBNET_PADDING
            subnet_h = max(content_h, CELL_H // 2) + SUBNET_HEADER + SUBNET_PADDING

            containers.append({
                "id": subnet_container_id,
                "label": subnet_label,
                "style": SUBNET_STYLE,
                "x": subnet_cursor_x,
                "y": vnet_inner_y,
                "w": subnet_w,
                "h": subnet_h,
                "parent": vnet_container_id,
            })

            vnet_content_h = max(vnet_content_h, subnet_h)
            subnet_cursor_x += subnet_w + SUBNET_H_GAP

        # VNet box dimensions
        vnet_w = (subnet_cursor_x - SUBNET_H_GAP) - cursor_x + VNET_PADDING
        vnet_h = vnet_content_h + VNET_HEADER + VNET_PADDING + VNET_PADDING

        # Ensure minimum width
        vnet_w = max(vnet_w, 200)

        containers.append({
            "id": vnet_container_id,
            "label": vnet_label,
            "style": VNET_STYLE,
            "x": cursor_x,
            "y": REGION_PADDING,
            "w": vnet_w,
            "h": vnet_h,
            "parent": "1",
        })

        cursor_x += vnet_w + VNET_H_GAP

    # Layout unattached nodes
    if unattached:
        unattached_label = "Other Resources"
        unattached_id = "unattached_group"
        inner_x = cursor_x + UNATTACHED_PADDING
        inner_y = REGION_PADDING + VNET_HEADER
        cols = min(COLS_PER_ROW, len(unattached))
        ua_pos, content_w, content_h = _grid_layout(unattached, inner_x, inner_y, cols)
        positions.update(ua_pos)

        ua_w = max(content_w, CELL_W) + 2 * UNATTACHED_PADDING
        ua_h = content_h + VNET_HEADER + 2 * UNATTACHED_PADDING

        containers.append({
            "id": unattached_id,
            "label": unattached_label,
            "style": UNATTACHED_STYLE,
            "x": cursor_x,
            "y": REGION_PADDING,
            "w": ua_w,
            "h": ua_h,
            "parent": "1",
        })

    return positions, containers


def generate_drawio(cfg: Config) -> None:
    graph_path = cfg.out("graph.json")
    if not graph_path.exists():
        raise FileNotFoundError("graph.json not found. Run 'graph' first.")
    graph = json.loads(graph_path.read_text())
    nodes: List[Dict] = graph["nodes"]
    edges: List[Dict] = graph["edges"]

    # Find assets dir relative to this file
    assets_dir = Path(__file__).parent.parent.parent / "assets"
    icon_map = _load_icon_map(assets_dir)

    containers: List[Dict] = []
    if cfg.layout == "VNET>SUBNET":
        positions, containers = layout_nodes_vnet(nodes, edges)
    else:
        positions = layout_nodes(nodes)
    icons_used = {"mapped": {}, "fallback": [], "unknown": []}

    # Build XML
    mxfile = ET.Element("mxfile")
    diagram = ET.SubElement(mxfile, "diagram")
    diagram.set("name", cfg.app)
    diagram.set("id", stable_id(cfg.app))
    model = ET.SubElement(diagram, "mxGraphModel")
    model.set("dx", "1422")
    model.set("dy", "762")
    model.set("grid", "1")
    model.set("gridSize", "10")
    model.set("guides", "1")
    model.set("tooltips", "1")
    model.set("connect", "1")
    model.set("arrows", "1")
    model.set("fold", "1")
    model.set("page", "1")
    model.set("pageScale", "1")
    model.set("pageWidth", "1654")
    model.set("pageHeight", "1169")
    model.set("math", "0")
    model.set("shadow", "0")
    root = ET.SubElement(model, "root")

    # Mandatory cells
    cell0 = ET.SubElement(root, "mxCell")
    cell0.set("id", "0")
    cell1 = ET.SubElement(root, "mxCell")
    cell1.set("id", "1")
    cell1.set("parent", "0")

    # Emit container group cells (VNet/subnet boxes) for VNET>SUBNET mode
    container_id_set: set = set()
    for cont in containers:
        container_id_set.add(cont["id"])
        cc = ET.SubElement(root, "mxCell")
        cc.set("id", cont["id"])
        cc.set("value", cont["label"])
        cc.set("style", cont["style"])
        cc.set("vertex", "1")
        cc.set("parent", cont["parent"])
        cc.set("connectable", "0")
        cg = ET.SubElement(cc, "mxGeometry")
        cg.set("x", str(cont["x"]))
        cg.set("y", str(cont["y"]))
        cg.set("width", str(cont["w"]))
        cg.set("height", str(cont["h"]))
        cg.set("as", "geometry")

    node_id_map: Dict[str, str] = {}

    # In VNET>SUBNET mode, VNet and subnet nodes are represented as containers
    # so they should not also be emitted as icon cells.
    vnet_subnet_types = {
        "microsoft.network/virtualnetworks",
        "microsoft.network/virtualnetworks/subnets",
    }
    is_vnet_layout = cfg.layout == "VNET>SUBNET"

    for node in nodes:
        nid = node["id"]
        sid = stable_id(nid)
        node_id_map[nid] = sid

        # Skip VNet/subnet nodes in VNET>SUBNET mode — shown as containers
        if is_vnet_layout and node.get("type", "") in vnet_subnet_types:
            continue

        # Skip nodes with no computed position (shouldn't happen, but guard)
        if nid not in positions:
            continue

        pos = positions[nid]
        x, y, w, h = pos
        style = _node_style(node, icon_map)
        t = node.get("type", "")
        if style != EXTERNAL_STYLE and style != UNKNOWN_STYLE:
            icons_used["mapped"][t] = icons_used["mapped"].get(t, 0) + 1
        elif node.get("isExternal"):
            pass
        else:
            if t not in icons_used["unknown"]:
                icons_used["unknown"].append(t)

        label = node.get("name", nid.split("/")[-1])
        cell = ET.SubElement(root, "mxCell")
        cell.set("id", sid)
        cell.set("value", label)
        cell.set("style", style)
        cell.set("vertex", "1")
        cell.set("parent", "1")
        geo = ET.SubElement(cell, "mxGeometry")
        geo.set("x", str(x))
        geo.set("y", str(y))
        geo.set("width", str(w))
        geo.set("height", str(h))
        geo.set("as", "geometry")

    # Add UDR callouts for route tables
    route_table_nodes = [n for n in nodes if n.get("type", "") == "microsoft.network/routetables"]
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
        co.set("parent", "1")
        cog = ET.SubElement(co, "mxGeometry")
        cog.set("x", str(cx))
        cog.set("y", str(cy))
        cog.set("width", "180")
        cog.set("height", str(max(60, 20 * len(label_lines))))
        cog.set("as", "geometry")

        # Attach callout to subnet with udr edge
        if rt_id in udr_edge_sources:
            subnet_sid = stable_id(udr_edge_sources[rt_id])
            edge_id = "udr_edge_" + stable_id(rt_id)
            ec = ET.SubElement(root, "mxCell")
            ec.set("id", edge_id)
            ec.set("value", "UDR")
            ec.set("style", EDGE_STYLE)
            ec.set("edge", "1")
            ec.set("source", subnet_sid)
            ec.set("target", callout_id)
            ec.set("parent", "1")
            eg = ET.SubElement(ec, "mxGeometry")
            eg.set("relative", "1")
            eg.set("as", "geometry")

    # Add attribute info boxes for resources that have metadata
    ATTR_EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;strokeColor=#9673a6;dashed=1;"
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
        ab.set("parent", "1")
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
        ae.set("parent", "1")
        aeg = ET.SubElement(ae, "mxGeometry")
        aeg.set("relative", "1")
        aeg.set("as", "geometry")

    # Add edges
    for i, e in enumerate(edges):
        src = node_id_map.get(e["source"])
        tgt = node_id_map.get(e["target"])
        if not src or not tgt:
            continue
        if e["kind"] == "subnet->routeTable":
            continue  # shown via callout
        edge_id = f"e_{stable_id(e['source'] + e['target'] + e['kind'])}"
        ec = ET.SubElement(root, "mxCell")
        ec.set("id", edge_id)
        ec.set("value", e["kind"])
        ec.set("style", EDGE_STYLE)
        ec.set("edge", "1")
        ec.set("source", src)
        ec.set("target", tgt)
        ec.set("parent", "1")
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

    # Optional image exports
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
