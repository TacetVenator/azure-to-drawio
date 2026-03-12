"""Graph model: normalize inventory into nodes and edges."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .util import normalize_id, stable_id

log = logging.getLogger(__name__)

# Resource types that are child/attribute resources.  These are merged into
# their parent node as metadata instead of appearing as standalone icons.
CHILD_RESOURCE_TYPES = {
    "microsoft.compute/virtualmachines/extensions",
    "microsoft.sql/servers/firewallrules",
    "microsoft.sql/servers/administrators",
    "microsoft.network/networksecuritygroups/securityrules",
    "microsoft.network/virtualnetworks/subnets/providers",
}


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


def _is_child_resource(resource_type: str) -> bool:
    """Return True if the resource type should be merged into its parent."""
    t = resource_type.lower()
    if t in CHILD_RESOURCE_TYPES:
        return True
    # Heuristic: types with 3+ path segments after the provider are child resources
    # e.g. microsoft.compute/virtualmachines/extensions has 3 segments
    parts = t.split("/")
    if len(parts) >= 3 and parts[0] != "microsoft.network":
        return True
    return False


def _find_parent_id(resource_id: str, resource_type: str) -> Optional[str]:
    """Derive the parent resource ID from a child resource ID."""
    nid = normalize_id(resource_id)
    # Split off the last two path segments (childType/childName)
    parts = nid.rsplit("/", 2)
    if len(parts) >= 3:
        return parts[0]
    return None


def _infer_type_from_id(arm_id: str) -> str:
    """Best-effort resource type inference from an ARM resource ID.

    For example:
      .../microsoft.network/virtualnetworks/foo/subnets/bar
        -> microsoft.network/virtualnetworks/subnets
      .../microsoft.network/virtualnetworks/foo
        -> microsoft.network/virtualnetworks
    Falls back to ``external/unknown`` when the pattern is unrecognisable.
    """
    nid = normalize_id(arm_id)
    # Find the /providers/ segment and extract type tokens after it
    idx = nid.rfind("/providers/")
    if idx == -1:
        return "external/unknown"
    after = nid[idx + len("/providers/"):]
    # Tokens alternate: provider, type, name, type, name ...
    parts = after.split("/")
    if len(parts) < 3:
        return "external/unknown"
    # provider = parts[0], then pairs of (type_segment, name)
    type_parts = [parts[0]]  # e.g. "microsoft.network"
    for i in range(1, len(parts) - 1, 2):
        type_parts.append(parts[i])  # e.g. "virtualnetworks", "subnets"
    return "/".join(type_parts)


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
        "childResources": [],
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

        elif t == "microsoft.network/azurefirewalls":
            for ipc in _get(p, "ipConfigurations") or []:
                add_edge(nid, _get(ipc, "properties", "subnet", "id"), "firewall->subnet")
                add_edge(nid, _get(ipc, "properties", "publicIPAddress", "id"), "firewall->publicIp")

        elif t == "microsoft.network/bastionhosts":
            for ipc in _get(p, "ipConfigurations") or []:
                add_edge(nid, _get(ipc, "properties", "subnet", "id"), "bastion->subnet")
                add_edge(nid, _get(ipc, "properties", "publicIPAddress", "id"), "bastion->publicIp")

        elif t == "microsoft.app/containerapps":
            add_edge(nid, _get(p, "managedEnvironmentId"), "containerApp->environment")

        elif t == "microsoft.app/managedenvironments":
            add_edge(nid, _get(p, "vnetConfiguration", "infrastructureSubnetId"), "containerEnv->subnet")

        elif t == "microsoft.insights/components":
            add_edge(nid, _get(p, "WorkspaceResourceId"), "appInsights->workspace")

        elif t == "microsoft.logic/workflows":
            for param in (_get(p, "parameters") or {}).values():
                if isinstance(param, dict) and param.get("type") == "string":
                    val = param.get("value", "")
                    if isinstance(val, str) and "/providers/" in val:
                        add_edge(nid, val, "logicApp->connection")

        elif t == "microsoft.network/applicationgateways":
            for ipc in _get(p, "gatewayIPConfigurations") or []:
                add_edge(nid, _get(ipc, "properties", "subnet", "id"), "appGw->subnet")
            for pool in _get(p, "backendAddressPools") or []:
                for addr in _get(pool, "properties", "backendAddresses") or []:
                    add_edge(nid, _get(addr, "fqdn"), "appGw->backend")

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


def _collect_attributes(node: Dict) -> List[str]:
    """Extract key attributes from a resource's properties for display."""
    attrs: List[str] = []
    t = node.get("type", "")
    p = node.get("properties", {})

    if t == "microsoft.compute/virtualmachines":
        vm_size = _get(p, "hardwareProfile", "vmSize")
        if vm_size:
            attrs.append(f"SKU: {vm_size}")
        img = _get(p, "storageProfile", "imageReference")
        if img and isinstance(img, dict):
            publisher = img.get("publisher", "")
            offer = img.get("offer", "")
            sku = img.get("sku", "")
            parts = [s for s in [publisher, offer, sku] if s]
            if parts:
                attrs.append(f"Image: {'/'.join(parts)}")
            elif img.get("id"):
                # Shared image gallery reference
                attrs.append(f"Image: {img['id'].split('/')[-1]}")
        os_type = _get(p, "storageProfile", "osDisk", "osType")
        if os_type:
            attrs.append(f"OS: {os_type}")

    elif t in ("microsoft.sql/servers", "microsoft.sql/servers/databases"):
        sku = node.get("properties", {}).get("sku") or {}
        if isinstance(sku, dict) and sku.get("name"):
            attrs.append(f"SKU: {sku['name']}")
            if sku.get("tier"):
                attrs.append(f"Tier: {sku['tier']}")

    # Add child resources as attributes
    for child in node.get("childResources", []):
        child_name = child.get("name", "")
        child_type = child.get("type", "").split("/")[-1]
        if child_name:
            attrs.append(f"{child_type}: {child_name}")

    return attrs


def build_graph(cfg: Config) -> Dict:
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' first.")
    inventory: List[Dict] = json.loads(inv_path.read_text())

    unresolved_path = cfg.out("unresolved.json")
    unresolved: List[str] = json.loads(unresolved_path.read_text()) if unresolved_path.exists() else []

    # Separate child resources from standalone resources
    parent_resources = []
    child_resources = []
    for r in inventory:
        rtype = (r.get("type") or "").lower()
        if _is_child_resource(rtype):
            child_resources.append(r)
        else:
            parent_resources.append(r)

    nodes = [build_node(r) for r in parent_resources]
    node_map: Dict[str, Dict] = {n["id"]: n for n in nodes}

    # Merge child resources into their parent nodes
    for child in child_resources:
        parent_id = _find_parent_id(child.get("id", ""), child.get("type", ""))
        if parent_id and parent_id in node_map:
            node_map[parent_id]["childResources"].append({
                "name": child.get("name", ""),
                "type": (child.get("type") or "").lower(),
                "properties": child.get("properties") or {},
            })
        else:
            # No parent found — keep as standalone node
            nodes.append(build_node(child))
            node_map[child.get("id", "").lower()] = nodes[-1]

    node_ids = {n["id"] for n in nodes}

    # Collect display attributes for each node
    for node in nodes:
        node["attributes"] = _collect_attributes(node)

    # Add external placeholder nodes for unresolved references
    for uid in unresolved:
        if uid not in node_ids:
            nodes.append({
                "id": uid,
                "stableId": stable_id(uid),
                "name": uid.split("/")[-1],
                "type": _infer_type_from_id(uid),
                "location": "",
                "resourceGroup": "",
                "subscriptionId": "",
                "properties": {},
                "isExternal": True,
                "childResources": [],
                "attributes": [],
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
