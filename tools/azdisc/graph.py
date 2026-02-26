"""Graph model: normalize inventory into nodes and edges."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .util import normalize_id, stable_id

log = logging.getLogger(__name__)


def _get(obj: Any, *keys) -> Any:
    """Safe nested get."""
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        elif isinstance(obj, list) and isinstance(k, int):
            obj = obj[k] if k < len(obj) else None
        else:
            return None
        if obj is None:
            return None
    return obj


def build_node(resource: Dict, is_external: bool = False) -> Dict:
    nid = normalize_id(resource.get("id", ""))
    return {
        "id": nid,
        "stableId": stable_id(nid),
        "name": resource.get("name", ""),
        "type": resource.get("type", "external/unknown").lower(),
        "location": resource.get("location", "").lower(),
        "resourceGroup": resource.get("resourceGroup", "").lower(),
        "subscriptionId": resource.get("subscriptionId", ""),
        "properties": resource.get("properties") or {},
        "isExternal": is_external,
    }


def extract_edges(nodes: List[Dict]) -> List[Dict]:
    """Extract explicit edges from resource properties."""
    edges: List[Dict] = []
    node_ids = {n["id"] for n in nodes}

    def add_edge(src: str, dst_raw: Optional[str], kind: str) -> None:
        if not dst_raw:
            return
        dst = normalize_id(dst_raw)
        if not dst:
            return
        edges.append({
            "source": normalize_id(src),
            "target": dst,
            "kind": kind,
        })

    for node in nodes:
        nid = node["id"]
        t = node["type"]
        p = node["properties"]

        if t == "microsoft.compute/virtualmachines":
            for ni in _get(p, "networkProfile", "networkInterfaces") or []:
                add_edge(nid, _get(ni, "id"), "vm->nic")
            add_edge(nid, _get(p, "storageProfile", "osDisk", "managedDisk", "id"), "vm->disk")
            for dd in _get(p, "storageProfile", "dataDisks") or []:
                add_edge(nid, _get(dd, "managedDisk", "id"), "vm->disk")

        elif t == "microsoft.network/networkinterfaces":
            add_edge(nid, _get(p, "networkSecurityGroup", "id"), "nic->nsg")
            for ipc in _get(p, "ipConfigurations") or []:
                add_edge(nid, _get(ipc, "properties", "subnet", "id"), "nic->subnet")

        elif t == "microsoft.network/virtualnetworks":
            for peer in _get(p, "virtualNetworkPeerings") or []:
                add_edge(nid, _get(peer, "properties", "remoteVirtualNetwork", "id"), "vnet->peeredVnet")

        elif t == "microsoft.network/virtualnetworks/subnets" or "/subnets/" in nid:
            # subnet -> vnet: parent of ID before /subnets/
            if "/subnets/" in nid:
                vnet_id = nid.split("/subnets/")[0]
                add_edge(nid, vnet_id, "subnet->vnet")
            add_edge(nid, _get(p, "networkSecurityGroup", "id"), "subnet->nsg")
            add_edge(nid, _get(p, "routeTable", "id"), "subnet->routeTable")

        elif t == "microsoft.network/privateendpoints":
            add_edge(nid, _get(p, "subnet", "id"), "privateEndpoint->subnet")
            for conn in _get(p, "privateLinkServiceConnections") or []:
                add_edge(nid, _get(conn, "properties", "privateLinkServiceId"), "privateEndpoint->target")

        elif t == "microsoft.network/loadbalancers":
            for pool in _get(p, "backendAddressPools") or []:
                for ipc in _get(pool, "properties", "backendIPConfigurations") or []:
                    ipc_id = _get(ipc, "id")
                    if ipc_id:
                        # normalize to NIC parent
                        nic_id = normalize_id(ipc_id).split("/ipconfigurations/")[0]
                        add_edge(nid, nic_id, "loadBalancer->backendNic")

        elif t == "microsoft.network/publicipaddresses":
            raw = _get(p, "ipConfiguration", "id")
            if raw:
                nic_id = normalize_id(raw).split("/ipconfigurations/")[0]
                add_edge(nid, nic_id, "publicIp->attachment")

        elif t == "microsoft.web/sites":
            add_edge(nid, _get(p, "serverFarmId"), "webApp->appServicePlan")
            add_edge(nid, _get(p, "virtualNetworkSubnetId"), "webApp->subnet")

    # Deduplicate edges
    seen = set()
    unique = []
    for e in edges:
        key = (e["source"], e["target"], e["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return sorted(unique, key=lambda e: (e["source"], e["target"], e["kind"]))


def add_rbac_edges(edges: List[Dict], rbac: List[Dict]) -> List[Dict]:
    """Add RBAC scope -> roleAssignment edges."""
    for r in rbac:
        scope = normalize_id(_get(r, "properties", "scope") or "")
        rid = normalize_id(r.get("id", ""))
        if scope and rid:
            edges.append({"source": scope, "target": rid, "kind": "rbac_assignment"})
    return edges


def build_graph(cfg: Config) -> Dict:
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' first.")
    inventory: List[Dict] = json.loads(inv_path.read_text())

    unresolved_path = cfg.out("unresolved.json")
    unresolved: List[str] = json.loads(unresolved_path.read_text()) if unresolved_path.exists() else []

    nodes = [build_node(r) for r in inventory]
    node_ids = {n["id"] for n in nodes}

    # Add external placeholder nodes for unresolved references
    for uid in unresolved:
        if uid not in node_ids:
            nodes.append({
                "id": uid,
                "stableId": stable_id(uid),
                "name": uid.split("/")[-1] if "/" in uid else uid,
                "type": "external/unknown",
                "location": "",
                "resourceGroup": "",
                "subscriptionId": "",
                "properties": {},
                "isExternal": True,
            })
            node_ids.add(uid)

    nodes.sort(key=lambda n: (n["resourceGroup"], n["type"], n["name"], n["id"]))

    edges = extract_edges(nodes)

    # Add RBAC edges if available
    rbac_path = cfg.out("rbac.json")
    if rbac_path.exists():
        rbac = json.loads(rbac_path.read_text())
        edges = add_rbac_edges(edges, rbac)

    graph = {"nodes": nodes, "edges": edges}
    cfg.ensure_output_dir()
    cfg.out("graph.json").write_text(json.dumps(graph, indent=2, sort_keys=True))
    log.info("Wrote graph: %d nodes, %d edges", len(nodes), len(edges))
    return graph
