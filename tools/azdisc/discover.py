"""Seed and transitive expansion of Azure resources via ARG."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Set

from .arg import query, query_by_ids
from .config import Config
from .util import extract_arm_ids, normalize_id

log = logging.getLogger(__name__)

_MAX_ITERATIONS = 50


def _rg_filter(rgs: List[str]) -> str:
    quoted = ", ".join(f"'{rg.lower()}'" for rg in rgs)
    return f"resources | where resourceGroup in~ ({quoted}) | project id, name, type, location, subscriptionId, resourceGroup, tags, sku, kind, systemData, properties"


def _safe_get(obj, *keys):
    """Safe nested get for extracting properties."""
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


def _extract_related_ids(resource: Dict) -> Set[str]:
    """Extract only directly-related ARM IDs from a resource.

    Instead of walking every property and following every ARM ID (which causes
    unbounded tenant-wide expansion), this function only follows known
    relationship types that produce useful diagram context:

      - VM -> NICs, managed disks
      - NIC -> subnet, NSG, ASGs
      - Subnet -> parent VNET, NSG, route table
      - VNET -> peered VNETs (one hop only)
      - Private endpoint -> subnet, target service
      - Load balancer -> backend NICs
      - Public IP -> attached resource
      - Web app -> app service plan, VNET integration subnet
      - Firewall / Bastion -> subnet, public IP
      - Container app -> managed environment
      - Managed environment -> subnet
      - App insights -> workspace
      - App gateway -> subnet
      - NSG -> ASGs referenced in rules
    """
    ids: Set[str] = set()
    t = (resource.get("type") or "").lower()
    p = resource.get("properties") or {}

    def _add(raw):
        if raw and isinstance(raw, str) and "/providers/" in raw.lower():
            ids.add(normalize_id(raw))

    if t == "microsoft.compute/virtualmachines":
        for ni in _safe_get(p, "networkProfile", "networkInterfaces") or []:
            _add(_safe_get(ni, "id"))
        _add(_safe_get(p, "storageProfile", "osDisk", "managedDisk", "id"))
        for dd in _safe_get(p, "storageProfile", "dataDisks") or []:
            _add(_safe_get(dd, "managedDisk", "id"))

    elif t == "microsoft.network/networkinterfaces":
        _add(_safe_get(p, "networkSecurityGroup", "id"))
        for ipc in _safe_get(p, "ipConfigurations") or []:
            _add(_safe_get(ipc, "properties", "subnet", "id"))
            for asg in _safe_get(ipc, "properties", "applicationSecurityGroups") or []:
                _add(_safe_get(asg, "id"))

    elif t == "microsoft.network/virtualnetworks":
        for peer in _safe_get(p, "virtualNetworkPeerings") or []:
            _add(_safe_get(peer, "properties", "remoteVirtualNetwork", "id"))

    elif t == "microsoft.network/virtualnetworks/subnets" or "/subnets/" in (resource.get("id") or "").lower():
        _add(_safe_get(p, "networkSecurityGroup", "id"))
        rt_id = _safe_get(p, "routeTable", "id")
        if rt_id:
            ids.add(normalize_id(rt_id))
            # Always try to resolve UDR even if in different RG/sub
            # Add parent RG and subscription for cross-sub scenarios
            parts = rt_id.split("/")
            if "subscriptions" in parts and "resourceGroups" in parts:
                try:
                    sub_idx = parts.index("subscriptions") + 1
                    rg_idx = parts.index("resourceGroups") + 1
                    sub_id = parts[sub_idx]
                    rg_name = parts[rg_idx]
                    ids.add(f"/subscriptions/{sub_id}/resourceGroups/{rg_name}")
                except Exception:
                    pass

    elif t == "microsoft.network/networksecuritygroups":
        for rule in _safe_get(p, "securityRules") or []:
            rp = _safe_get(rule, "properties") or {}
            for asg in rp.get("sourceApplicationSecurityGroups") or []:
                _add(_safe_get(asg, "id"))
            for asg in rp.get("destinationApplicationSecurityGroups") or []:
                _add(_safe_get(asg, "id"))

    elif t == "microsoft.network/privateendpoints":
        _add(_safe_get(p, "subnet", "id"))
        for conn in _safe_get(p, "privateLinkServiceConnections") or []:
            _add(_safe_get(conn, "properties", "privateLinkServiceId"))

    elif t == "microsoft.network/loadbalancers":
        for pool in _safe_get(p, "backendAddressPools") or []:
            for ipc in _safe_get(pool, "properties", "backendIPConfigurations") or []:
                ipc_id = _safe_get(ipc, "id")
                if ipc_id:
                    nic_id = normalize_id(ipc_id).split("/ipconfigurations/")[0]
                    ids.add(nic_id)

    elif t == "microsoft.network/publicipaddresses":
        raw = _safe_get(p, "ipConfiguration", "id")
        if raw:
            nic_id = normalize_id(raw).split("/ipconfigurations/")[0]
            ids.add(nic_id)

    elif t == "microsoft.web/sites":
        _add(_safe_get(p, "serverFarmId"))
        _add(_safe_get(p, "virtualNetworkSubnetId"))

    elif t == "microsoft.network/azurefirewalls":
        for ipc in _safe_get(p, "ipConfigurations") or []:
            _add(_safe_get(ipc, "properties", "subnet", "id"))
            _add(_safe_get(ipc, "properties", "publicIPAddress", "id"))

    elif t == "microsoft.network/bastionhosts":
        for ipc in _safe_get(p, "ipConfigurations") or []:
            _add(_safe_get(ipc, "properties", "subnet", "id"))
            _add(_safe_get(ipc, "properties", "publicIPAddress", "id"))

    elif t == "microsoft.app/containerapps":
        _add(_safe_get(p, "managedEnvironmentId"))

    elif t == "microsoft.app/managedenvironments":
        _add(_safe_get(p, "vnetConfiguration", "infrastructureSubnetId"))

    elif t == "microsoft.insights/components":
        _add(_safe_get(p, "WorkspaceResourceId"))

    elif t == "microsoft.network/applicationgateways":
        for ipc in _safe_get(p, "gatewayIPConfigurations") or []:
            _add(_safe_get(ipc, "properties", "subnet", "id"))

    elif t == "microsoft.network/routetables":
        # Route tables are leaf resources — don't chase next-hop references
        # which can point to appliances across the tenant.
        pass

    return ids


def _derive_parent_ids(referenced: Set[str]) -> Set[str]:
    """Derive parent resource IDs from child resource IDs.

    For example, a subnet ID like
      /subscriptions/.../virtualnetworks/spoke-vnet01/subnets/cprmg-subnet01
    yields the parent VNET ID:
      /subscriptions/.../virtualnetworks/spoke-vnet01

    This ensures cross-resource-group parent resources are discovered during
    expansion even when no property explicitly references them.
    """
    parents: Set[str] = set()
    for rid in referenced:
        nid = normalize_id(rid)
        # Subnet -> parent VNET
        if "/subnets/" in nid:
            vnet_id = nid.split("/subnets/")[0]
            parents.add(vnet_id)
    return parents


def _synthesize_subnets_from_vnets(
    collected: Dict[str, Dict], unresolved: Set[str],
) -> None:
    """For unresolved subnet IDs, synthesize entries from parent VNET properties.

    Azure Resource Graph sometimes does not return subnets as standalone
    resources.  When the parent VNET *is* in the inventory, we can extract
    the subnet details from its ``properties.subnets`` array and add them
    as first-class resources.
    """
    resolved_from_vnet: Set[str] = set()
    for uid in list(unresolved):
        nid = normalize_id(uid)
        if "/subnets/" not in nid:
            continue
        vnet_id = nid.split("/subnets/")[0]
        vnet = collected.get(vnet_id)
        if vnet is None:
            continue
        subnet_name = nid.split("/subnets/")[-1]
        for sn in vnet.get("properties", {}).get("subnets", []):
            sn_id = normalize_id(sn.get("id", ""))
            if sn_id == nid or sn.get("name", "").lower() == subnet_name:
                # Build a synthetic resource entry matching ARG shape
                collected[nid] = {
                    "id": sn.get("id", uid),
                    "name": sn.get("name", subnet_name),
                    "type": "Microsoft.Network/virtualNetworks/subnets",
                    "location": vnet.get("location", ""),
                    "subscriptionId": vnet.get("subscriptionId", ""),
                    "resourceGroup": vnet.get("resourceGroup", ""),
                    "properties": sn.get("properties", {}),
                }
                resolved_from_vnet.add(uid)
                log.info("Synthesized subnet %s from parent VNET", subnet_name)
                break
    unresolved -= resolved_from_vnet


def run_seed(cfg: Config) -> List[Dict]:
    log.info("Seeding resources from RGs: %s", cfg.seedResourceGroups)
    rows = query(_rg_filter(cfg.seedResourceGroups), cfg.subscriptions)
    cfg.ensure_output_dir()
    out = cfg.out("seed.json")
    out.write_text(json.dumps(rows, indent=2, sort_keys=True))
    log.info("Wrote %d seed resources to %s", len(rows), out)
    return rows


def run_expand(cfg: Config) -> None:
    seed_path = cfg.out("seed.json")
    if not seed_path.exists():
        raise FileNotFoundError(f"seed.json not found at {seed_path}. Run 'seed' first.")
    seed: List[Dict] = json.loads(seed_path.read_text())

    collected: Dict[str, Dict] = {normalize_id(r["id"]): r for r in seed}
    unresolved: Set[str] = set()

    use_scoped = cfg.expandScope == "related"
    if use_scoped:
        log.info("Using scoped expansion (expandScope=related). Set expandScope=all to follow every ARM reference.")
    else:
        log.info("Using full expansion (expandScope=all). All ARM references will be followed.")

    for iteration in range(_MAX_ITERATIONS):
        referenced: Set[str] = set()
        for r in collected.values():
            if use_scoped:
                referenced.update(_extract_related_ids(r))
            else:
                referenced.update(extract_arm_ids(r.get("properties", {})))
            referenced.add(normalize_id(r["id"]))
        referenced = {normalize_id(i) for i in referenced}

        # Derive parent resource IDs for child resources (e.g. VNET from subnet ID).
        parent_ids = _derive_parent_ids(referenced)
        referenced.update(parent_ids)

        missing = referenced - set(collected.keys()) - unresolved
        if not missing:
            log.info("Expansion converged after %d iteration(s).", iteration)
            break
        log.info("Iteration %d: fetching %d missing resources", iteration + 1, len(missing))
        # Support cross-subscription/resource group fetch
        fetched = []
        for m in sorted(missing):
            # If m is a full ARM ID, try to fetch from all subscriptions
            if m.startswith("/subscriptions/"):
                fetched.extend(query_by_ids([m], cfg.subscriptions))
            else:
                fetched.extend(query_by_ids([m], cfg.subscriptions))
        fetched_ids = set()
        for r in fetched:
            nid = normalize_id(r["id"])
            collected[nid] = r
            fetched_ids.add(nid)
        still_missing = missing - fetched_ids
        unresolved.update(still_missing)
        log.debug("Still unresolved: %d", len(still_missing))
    else:
        log.warning("Expansion hit max iterations (%d).", _MAX_ITERATIONS)

    # Synthesize subnet entries from parent VNET properties for any subnets
    # that could not be fetched directly from ARG (common for cross-RG refs).
    _synthesize_subnets_from_vnets(collected, unresolved)

    inventory = sorted(collected.values(), key=lambda r: normalize_id(r["id"]))
    cfg.ensure_output_dir()
    cfg.out("inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True))
    cfg.out("unresolved.json").write_text(json.dumps(sorted(unresolved), indent=2))
    log.info("Wrote inventory (%d resources) and unresolved (%d IDs)", len(inventory), len(unresolved))


def run_rbac(cfg: Config) -> None:
    if not cfg.includeRbac:
        log.info("RBAC disabled in config.")
        return
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' first.")
    inventory: List[Dict] = json.loads(inv_path.read_text())
    scopes = {normalize_id(r["id"]) for r in inventory}
    scopes.update({r.get("resourceGroup", "").lower() for r in inventory if r.get("resourceGroup")})

    # Query role assignments via authorizationresources
    kusto = "authorizationresources | where type =~ 'microsoft.authorization/roleassignments' | project id, name, type, properties"
    rows = query(kusto, cfg.subscriptions)
    # Filter to relevant scopes
    relevant = [r for r in rows if normalize_id(r.get("properties", {}).get("scope", "")) in scopes or
                any(normalize_id(r.get("properties", {}).get("scope", "")).startswith(s) for s in scopes)]
    cfg.ensure_output_dir()
    cfg.out("rbac.json").write_text(json.dumps(relevant, indent=2, sort_keys=True))
    log.info("Wrote %d RBAC assignments to rbac.json", len(relevant))
