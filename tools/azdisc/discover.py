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
    return f"resources | where resourceGroup in~ ({quoted}) | project id, name, type, location, subscriptionId, resourceGroup, properties"


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

    for iteration in range(_MAX_ITERATIONS):
        referenced: Set[str] = set()
        for r in collected.values():
            referenced.update(extract_arm_ids(r.get("properties", {})))
            referenced.add(normalize_id(r["id"]))
        referenced = {normalize_id(i) for i in referenced}

        # Derive parent resource IDs for child resources (e.g. VNET from subnet ID).
        # This ensures cross-resource-group parent resources are fetched even when
        # they are not directly referenced in any property.
        parent_ids = _derive_parent_ids(referenced)
        referenced.update(parent_ids)

        missing = referenced - set(collected.keys()) - unresolved
        if not missing:
            log.info("Expansion converged after %d iteration(s).", iteration)
            break
        log.info("Iteration %d: fetching %d missing resources", iteration + 1, len(missing))
        fetched = query_by_ids(sorted(missing), cfg.subscriptions)
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
