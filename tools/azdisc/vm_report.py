"""Focused per-VM report pack generation."""
from __future__ import annotations

import csv
import json
import logging
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .config import Config
from .docs import generate_docs
from .drawio import generate_drawio
from .graph import build_graph
from .insights import generate_vm_details_csv
from .master_report import generate_master_report
from .util import load_json_file, normalize_id

log = logging.getLogger(__name__)

_VM_TYPE = "microsoft.compute/virtualmachines"
_VM_REPORT_FIELDS = [
    "Name", "ResourceId", "SubscriptionId", "ResourceGroup", "Location", "VmSize", "OsType",
    "PowerState", "AvailabilityZone", "ImageReference", "NicNames", "SubnetNames", "VnetNames",
    "NsgNames", "AsgNames", "RouteTableNames", "PublicIpNames", "LoadBalancerNames", "DiskNames", "ExtensionNames",
]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "vm"


def _load_json(path: Path, expected_type: type, context: str) -> Any:
    return load_json_file(
        path,
        context=context,
        expected_type=expected_type,
        advice=f"Fix {path.name} or regenerate the prerequisite artifact before creating VM report packs.",
    )


def _load_optional_json(path: Path, expected_type: type, context: str) -> Any:
    if not path.exists():
        return expected_type()
    return _load_json(path, expected_type, context)


def _node_label(node: Optional[Dict[str, Any]], fallback: str) -> str:
    if node:
        return str(node.get("name") or fallback)
    return fallback


def _build_adjacency(edges: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    adjacency: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        source = normalize_id(edge["source"])
        target = normalize_id(edge["target"])
        entry = {"source": source, "target": target, "kind": edge["kind"]}
        adjacency[source].append(entry)
        adjacency[target].append(entry)
    return adjacency


def _neighbor(edge: Dict[str, Any], current: str) -> str:
    return edge["target"] if edge["source"] == current else edge["source"]


def _collect_vm_slice_ids(vm_id: str, node_by_id: Dict[str, Dict[str, Any]], edges: List[Dict[str, Any]]) -> Set[str]:
    adjacency = _build_adjacency(edges)
    included: Set[str] = {vm_id}

    vm_edge_kinds = {"vm->nic", "vm->disk"}
    nic_edge_kinds = {"nic->subnet", "nic->nsg", "nic->asg", "publicIp->attachment", "loadBalancer->backendNic"}
    subnet_edge_kinds = {"subnet->vnet", "subnet->nsg", "subnet->routeTable", "nic->subnet"}
    vnet_edge_kinds = {"subnet->vnet", "vnet->peeredVnet"}

    nic_ids: Set[str] = set()
    subnet_ids: Set[str] = set()
    vnet_ids: Set[str] = set()

    for edge in adjacency.get(vm_id, []):
        if edge["kind"] not in vm_edge_kinds:
            continue
        neighbor = _neighbor(edge, vm_id)
        included.add(neighbor)
        if edge["kind"] == "vm->nic":
            nic_ids.add(neighbor)

    for nic_id in sorted(nic_ids):
        for edge in adjacency.get(nic_id, []):
            if edge["kind"] not in nic_edge_kinds:
                continue
            neighbor = _neighbor(edge, nic_id)
            included.add(neighbor)
            if edge["kind"] == "nic->subnet":
                subnet_ids.add(neighbor)

    for subnet_id in sorted(subnet_ids):
        for edge in adjacency.get(subnet_id, []):
            if edge["kind"] not in subnet_edge_kinds:
                continue
            neighbor = _neighbor(edge, subnet_id)
            included.add(neighbor)
            if edge["kind"] == "subnet->vnet":
                vnet_ids.add(neighbor)

    for vnet_id in sorted(vnet_ids):
        for edge in adjacency.get(vnet_id, []):
            if edge["kind"] not in vnet_edge_kinds:
                continue
            included.add(_neighbor(edge, vnet_id))

    for node_id in list(included):
        node = node_by_id.get(node_id)
        if node and node.get("isExternal"):
            continue
        for edge in adjacency.get(node_id, []):
            other = _neighbor(edge, node_id)
            if other in included:
                continue
            other_node = node_by_id.get(other)
            if other_node and other_node.get("isExternal"):
                included.add(other)

    return included


def _filter_rbac_rows(rbac_rows: List[Dict[str, Any]], inventory: List[Dict[str, Any]], included_ids: Set[str]) -> List[Dict[str, Any]]:
    rg_scopes = {
        normalize_id(f"/subscriptions/{r.get('subscriptionId')}/resourceGroups/{r.get('resourceGroup')}")
        for r in inventory
        if r.get("subscriptionId") and r.get("resourceGroup")
    }
    filtered: List[Dict[str, Any]] = []
    for row in rbac_rows:
        scope = normalize_id(((row.get("properties") or {}).get("scope") or ""))
        if not scope:
            continue
        if scope in included_ids or scope in rg_scopes or any(rid.startswith(scope + "/") for rid in included_ids):
            filtered.append(row)
    return filtered


def _filter_policy_rows(policy_rows: List[Dict[str, Any]], included_ids: Set[str]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in policy_rows:
        resource_id = normalize_id(row.get("resourceId") or ((row.get("properties") or {}).get("resourceId") or ""))
        if resource_id and resource_id in included_ids:
            filtered.append(row)
    return filtered


def _find_neighbors(node_id: str, edges: List[Dict[str, Any]], kind: Optional[str] = None) -> List[str]:
    matches: List[str] = []
    for edge in edges:
        if kind and edge["kind"] != kind:
            continue
        source = normalize_id(edge["source"])
        target = normalize_id(edge["target"])
        if source == node_id:
            matches.append(target)
        elif target == node_id:
            matches.append(source)
    return sorted(set(matches))


def _write_vm_csv(path: Path, row: Dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_VM_REPORT_FIELDS)
        writer.writeheader()
        writer.writerow(row)


def _build_vm_row(vm_resource: Dict[str, Any], node_by_id: Dict[str, Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    vm_id = normalize_id(vm_resource.get("id") or "")
    props = vm_resource.get("properties") or {}
    storage = props.get("storageProfile") or {}
    image = storage.get("imageReference") or {}
    image_ref = "/".join(str(image.get(key) or "") for key in ("publisher", "offer", "sku", "version") if image.get(key))
    zones = vm_resource.get("zones") or props.get("zones") or []

    nic_ids = _find_neighbors(vm_id, edges, "vm->nic")
    disk_ids = _find_neighbors(vm_id, edges, "vm->disk")
    subnet_ids: Set[str] = set()
    nsg_ids: Set[str] = set()
    asg_ids: Set[str] = set()
    public_ip_ids: Set[str] = set()
    load_balancer_ids: Set[str] = set()
    route_table_ids: Set[str] = set()
    vnet_ids: Set[str] = set()

    for nic_id in nic_ids:
        subnet_ids.update(_find_neighbors(nic_id, edges, "nic->subnet"))
        nsg_ids.update(_find_neighbors(nic_id, edges, "nic->nsg"))
        asg_ids.update(_find_neighbors(nic_id, edges, "nic->asg"))
        public_ip_ids.update(_find_neighbors(nic_id, edges, "publicIp->attachment"))
        load_balancer_ids.update(_find_neighbors(nic_id, edges, "loadBalancer->backendNic"))

    for subnet_id in subnet_ids:
        nsg_ids.update(_find_neighbors(subnet_id, edges, "subnet->nsg"))
        route_table_ids.update(_find_neighbors(subnet_id, edges, "subnet->routeTable"))
        vnet_ids.update(_find_neighbors(subnet_id, edges, "subnet->vnet"))

    extensions = [
        child.get("name", "")
        for child in node_by_id.get(vm_id, {}).get("childResources", [])
        if child.get("name")
    ]

    return {
        "Name": vm_resource.get("name", ""),
        "ResourceId": vm_resource.get("id", ""),
        "SubscriptionId": vm_resource.get("subscriptionId", ""),
        "ResourceGroup": vm_resource.get("resourceGroup", ""),
        "Location": vm_resource.get("location", ""),
        "VmSize": ((props.get("hardwareProfile") or {}).get("vmSize") or ""),
        "OsType": ((storage.get("osDisk") or {}).get("osType") or ""),
        "PowerState": (((props.get("extended") or {}).get("instanceView") or {}).get("powerState") or {}).get("code", ""),
        "AvailabilityZone": ",".join(str(zone) for zone in zones),
        "ImageReference": image_ref,
        "NicNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in nic_ids),
        "SubnetNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(subnet_ids)),
        "VnetNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(vnet_ids)),
        "NsgNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(nsg_ids)),
        "AsgNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(asg_ids)),
        "RouteTableNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(route_table_ids)),
        "PublicIpNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(public_ip_ids)),
        "LoadBalancerNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in sorted(load_balancer_ids)),
        "DiskNames": "; ".join(_node_label(node_by_id.get(rid), rid.split("/")[-1]) for rid in disk_ids),
        "ExtensionNames": "; ".join(sorted(extensions)),
    }


def _write_vm_report(path: Path, vm_resource: Dict[str, Any], graph: Dict[str, Any]) -> None:
    vm_id = normalize_id(vm_resource.get("id") or "")
    node_by_id = {normalize_id(node["id"]): node for node in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    vm_node = node_by_id.get(vm_id, {})
    props = vm_resource.get("properties") or {}
    storage = props.get("storageProfile") or {}
    row = _build_vm_row(vm_resource, node_by_id, edges)
    nic_ids = _find_neighbors(vm_id, edges, "vm->nic")
    subnet_ids = sorted({subnet for nic_id in nic_ids for subnet in _find_neighbors(nic_id, edges, "nic->subnet")})
    public_ip_ids = sorted({pip for nic_id in nic_ids for pip in _find_neighbors(nic_id, edges, "publicIp->attachment")})
    attrs = vm_node.get("attributes", [])

    lines = [
        f"# VM Report - {vm_resource.get('name', 'unknown-vm')}",
        "",
        "## Identity",
        "",
        f"- Resource ID: `{vm_resource.get('id', '')}`",
        f"- Subscription: `{vm_resource.get('subscriptionId', '')}`",
        f"- Resource group: `{vm_resource.get('resourceGroup', '')}`",
        f"- Location: `{vm_resource.get('location', '')}`",
        "",
        "## Compute",
        "",
        f"- SKU: `{row['VmSize'] or 'unknown'}`",
        f"- OS type: `{row['OsType'] or 'unknown'}`",
        f"- Power state: `{row['PowerState'] or 'unknown'}`",
        f"- Availability zones: `{row['AvailabilityZone'] or 'none surfaced'}`",
        f"- Image reference: `{row['ImageReference'] or 'unknown'}`",
        "",
        "## Storage",
        "",
        f"- OS disk SKU: `{((storage.get('osDisk') or {}).get('managedDisk') or {}).get('storageAccountType', 'unknown')}`",
        f"- Attached disks: {row['DiskNames'] or '_none discovered_'}",
        "",
        "## Networking",
        "",
        f"- NICs: {row['NicNames'] or '_none discovered_'}",
        f"- Subnets: {row['SubnetNames'] or '_none discovered_'}",
        f"- VNets: {row['VnetNames'] or '_none discovered_'}",
        f"- NSGs: {row['NsgNames'] or '_none discovered_'}",
        f"- ASGs: {row['AsgNames'] or '_none discovered_'}",
        f"- Route tables: {row['RouteTableNames'] or '_none discovered_'}",
        f"- Public IPs: {row['PublicIpNames'] or '_none discovered_'}",
        f"- Load balancers: {row['LoadBalancerNames'] or '_none discovered_'}",
        "",
        "## Extensions",
        "",
        f"- Extensions: {row['ExtensionNames'] or '_none discovered_'}",
        "",
        "## Diagram Context",
        "",
        f"- Nodes in focused graph: {len(graph.get('nodes', []))}",
        f"- Relationships in focused graph: {len(edges)}",
        "",
    ]
    if attrs:
        lines.extend(["## Display Attributes", ""])
        for attr in attrs:
            lines.append(f"- {attr}")
        lines.append("")
    if subnet_ids:
        lines.extend(["## Subnet Attachment", ""])
        for subnet_id in subnet_ids:
            subnet = node_by_id.get(subnet_id)
            lines.append(f"- `{_node_label(subnet, subnet_id.split('/')[-1])}`")
        lines.append("")
    if public_ip_ids:
        lines.extend(["## Public Exposure", ""])
        for public_ip_id in public_ip_ids:
            pip = node_by_id.get(public_ip_id)
            lines.append(f"- `{_node_label(pip, public_ip_id.split('/')[-1])}`")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_vm_index(root: Path, summaries: List[Dict[str, Any]]) -> None:
    lines = ["# VM Report Packs", "", "## Available VMs", ""]
    for summary in summaries:
        slug = summary["slug"]
        lines.append(f"- [{summary['name']}](./{slug}/vm_report.md)")
    (root / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_vm_report_packs(cfg: Config) -> List[Dict[str, Any]]:
    inventory_path = cfg.out("inventory.json")
    graph_path = cfg.out("graph.json")
    if not inventory_path.exists() or not graph_path.exists():
        raise FileNotFoundError("inventory.json and graph.json must exist before generating VM report packs.")

    inventory: List[Dict[str, Any]] = _load_json(inventory_path, list, "VM report inventory")
    graph: Dict[str, Any] = _load_json(graph_path, dict, "VM report graph")
    unresolved: List[str] = _load_optional_json(cfg.out("unresolved.json"), list, "VM report unresolved")
    rbac_rows: List[Dict[str, Any]] = _load_optional_json(cfg.out("rbac.json"), list, "VM report RBAC")
    policy_rows: List[Dict[str, Any]] = _load_optional_json(cfg.out("policy.json"), list, "VM report policy")

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_by_id = {normalize_id(node["id"]): node for node in nodes}
    inventory_by_id = {normalize_id(resource["id"]): resource for resource in inventory if resource.get("id")}
    vm_resources = [
        resource for resource in inventory
        if normalize_id(resource.get("type") or "") == _VM_TYPE and normalize_id(resource.get("id") or "") in node_by_id
    ]
    if not vm_resources:
        log.info("No VMs found in inventory; skipping VM report pack generation.")
        return []

    root = Path(cfg.outputDir) / "vms"
    root.mkdir(parents=True, exist_ok=True)
    summaries: List[Dict[str, Any]] = []

    for vm_resource in sorted(
        vm_resources,
        key=lambda item: (str(item.get("subscriptionId") or ""), str(item.get("resourceGroup") or ""), str(item.get("name") or "")),
    ):
        vm_id = normalize_id(vm_resource.get("id") or "")
        included_ids = _collect_vm_slice_ids(vm_id, node_by_id, edges)
        projected_inventory = []
        seen_inventory_ids: Set[str] = set()
        for resource in inventory:
            rid = normalize_id(resource.get("id") or "")
            if not rid:
                continue
            if rid in included_ids or any(rid.startswith(parent_id + "/") for parent_id in included_ids):
                if rid not in seen_inventory_ids:
                    projected_inventory.append(resource)
                    seen_inventory_ids.add(rid)
        projected_unresolved = sorted({rid for rid in unresolved if normalize_id(rid) in included_ids})
        projected_rbac = _filter_rbac_rows(rbac_rows, projected_inventory, included_ids)
        projected_policy = _filter_policy_rows(policy_rows, included_ids)

        slug = _slugify(str(vm_resource.get("name") or vm_id.split("/")[-1]))
        vm_dir = root / slug
        vm_dir.mkdir(parents=True, exist_ok=True)
        slice_cfg = replace(cfg, outputDir=str(vm_dir), app=f"{cfg.app} - {vm_resource.get('name', slug)}", includeVmDetails=True)

        slice_cfg.out("inventory.json").write_text(json.dumps(projected_inventory, indent=2, sort_keys=True), encoding="utf-8")
        slice_cfg.out("unresolved.json").write_text(json.dumps(projected_unresolved, indent=2), encoding="utf-8")
        if projected_rbac:
            slice_cfg.out("rbac.json").write_text(json.dumps(projected_rbac, indent=2, sort_keys=True), encoding="utf-8")
        elif slice_cfg.out("rbac.json").exists():
            slice_cfg.out("rbac.json").unlink()
        if projected_policy:
            slice_cfg.out("policy.json").write_text(json.dumps(projected_policy, indent=2, sort_keys=True), encoding="utf-8")
        elif slice_cfg.out("policy.json").exists():
            slice_cfg.out("policy.json").unlink()

        slice_graph = build_graph(slice_cfg)
        generate_drawio(slice_cfg)
        generate_vm_details_csv(slice_cfg)
        vm_node_by_id = {normalize_id(node["id"]): node for node in slice_graph.get("nodes", [])}
        vm_row = _build_vm_row(vm_resource, vm_node_by_id, slice_graph.get("edges", []))
        _write_vm_csv(slice_cfg.out("vm_report.csv"), vm_row)
        _write_vm_report(slice_cfg.out("vm_report.md"), vm_resource, slice_graph)
        generate_docs(slice_cfg)
        generate_master_report(slice_cfg)
        summaries.append({"name": vm_resource.get("name", slug), "slug": slug, "resourceId": vm_id})

    _write_vm_index(root, summaries)
    log.info("Wrote %d VM report pack(s) under %s", len(summaries), root)
    return summaries
