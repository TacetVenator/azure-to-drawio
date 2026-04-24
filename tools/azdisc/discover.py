"""Seed and transitive expansion of Azure resources via ARG."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .arg import query, query_by_ids, resolve_subscriptions
from .azcli import run_az_json
from .config import Config
from .inventory import generate_software_inventory_csv
from .util import extract_arm_ids, load_json_file, normalize_id

log = logging.getLogger(__name__)

_MAX_ITERATIONS = 50
_POLICY_BATCH_SIZE = 100
_RESOURCE_PROJECT = "project id, name, type, location, subscriptionId, resourceGroup, tags, sku, kind, systemData, properties"
_DEEP_MATCH_FIELD = "matchedSearchStrings"
_DEEP_REASON_FIELD = "discoveryEvidence"
_RELATED_REVIEW_REPORT = "related_review.md"
_EXPAND_REASONS_FILE = "expand_reasons.json"
_EXPAND_REASONS_REPORT = "expand_reasons.md"


def _kusto_quote(value: str) -> str:
    return value.replace("'", "''")


def _rg_filter(rgs: List[str]) -> str:
    quoted = ", ".join(f"'{rg.lower()}'" for rg in rgs)
    return f"resources | where resourceGroup in~ ({quoted}) | {_RESOURCE_PROJECT}"




def _role_definition_lookup(subscriptions: List[str]) -> Dict[str, str]:
    rows = query(
        "authorizationresources | where type =~ 'microsoft.authorization/roledefinitions' "
        "| project id, name, type, properties",
        subscriptions,
    )
    lookup: Dict[str, str] = {}
    for row in rows:
        role_id = normalize_id(row.get("id") or "")
        props = row.get("properties") or {}
        role_name = props.get("roleName") or props.get("roleDefinitionName") or row.get("name")
        if role_id and role_name:
            lookup[role_id] = str(role_name)
    return lookup


def _resolve_principal_name(principal_id: str, principal_type: str) -> Optional[str]:
    principal_id = str(principal_id or "").strip()
    if not principal_id:
        return None
    kind = str(principal_type or "").strip().lower()
    commands: List[List[str]]
    if kind == "user":
        commands = [["ad", "user", "show", "--id", principal_id]]
    elif kind == "group":
        commands = [["ad", "group", "show", "--group", principal_id]]
    elif kind in {"serviceprincipal", "service principal"}:
        commands = [["ad", "sp", "show", "--id", principal_id]]
    else:
        commands = [
            ["ad", "user", "show", "--id", principal_id],
            ["ad", "group", "show", "--group", principal_id],
            ["ad", "sp", "show", "--id", principal_id],
        ]

    for command in commands:
        try:
            data = run_az_json(command, expected_type=dict, advice="Re-run the command with --debug or verify the signed-in identity has directory read permissions.")
        except RuntimeError:
            continue
        for key in ("displayName", "userPrincipalName", "appDisplayName", "mailNickname"):
            value = data.get(key)
            if value:
                return str(value)
    return None


def _enrich_rbac_rows(rows: List[Dict[str, Any]], cfg: Config) -> List[Dict[str, Any]]:
    role_lookup = _role_definition_lookup(resolve_subscriptions(cfg.subscriptions, cfg.seedManagementGroups))
    principal_cache: Dict[str, Optional[str]] = {}
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        props = dict(item.get("properties") or {})
        role_definition_id = normalize_id(props.get("roleDefinitionId") or item.get("roleDefinitionId") or "")
        if role_definition_id and role_definition_id in role_lookup:
            role_name = role_lookup[role_definition_id]
            item["roleDefinitionName"] = role_name
            props["roleDefinitionName"] = role_name

        principal_id = str(props.get("principalId") or item.get("principalId") or "").strip()
        existing_name = (
            props.get("principalDisplayName")
            or props.get("principalName")
            or props.get("displayName")
            or item.get("principalDisplayName")
            or item.get("principalName")
            or item.get("displayName")
        )
        if existing_name:
            display_name = str(existing_name)
            item["principalDisplayName"] = display_name
            props["principalDisplayName"] = display_name
            props["principalResolutionSource"] = "assignment"
            props["principalResolutionStatus"] = "provided"
        elif cfg.resolvePrincipalNames and principal_id:
            if principal_id not in principal_cache:
                principal_cache[principal_id] = _resolve_principal_name(
                    principal_id,
                    str(props.get("principalType") or item.get("principalType") or ""),
                )
            resolved = principal_cache[principal_id]
            if resolved:
                item["principalDisplayName"] = resolved
                props["principalDisplayName"] = resolved
                props["principalResolutionSource"] = "entra"
                props["principalResolutionStatus"] = "resolved"
            else:
                props["principalResolutionSource"] = "entra"
                props["principalResolutionStatus"] = "unresolved"
        elif principal_id:
            props["principalResolutionSource"] = "disabled"
            props["principalResolutionStatus"] = "unresolved"

        item["properties"] = props
        enriched.append(item)
    return enriched



def _query_with_cfg(kusto: str, cfg: Config) -> List[Dict[str, Any]]:
    try:
        return query(kusto, cfg.subscriptions, cfg.seedManagementGroups)
    except TypeError:
        return query(kusto, cfg.subscriptions)


def _query_by_ids_with_cfg(ids: List[str], cfg: Config) -> List[Dict[str, Any]]:
    try:
        return query_by_ids(ids, cfg.subscriptions, cfg.seedManagementGroups)
    except TypeError:
        return query_by_ids(ids, cfg.subscriptions)


def _query_reverse_related_with_cfg(kusto: str, cfg: Config) -> List[Dict[str, Any]]:
    try:
        return query(kusto, cfg.subscriptions, cfg.seedManagementGroups)
    except TypeError:
        return query(kusto, cfg.subscriptions)


def _seed_query(cfg: Config) -> str:
    if cfg.seedEntireSubscriptions or (cfg.seedManagementGroups and not (cfg.seedResourceGroups or cfg.seedResourceIds or cfg.seedTags or cfg.seedTagKeys)):
        return (
            "resources "
            f"| {_RESOURCE_PROJECT}"
        )

    clauses: List[str] = []
    if cfg.seedResourceGroups:
        quoted = ", ".join(f"'{_kusto_quote(rg.lower())}'" for rg in cfg.seedResourceGroups)
        clauses.append(f"resourceGroup in~ ({quoted})")
    if cfg.seedResourceIds:
        quoted_ids = ", ".join(f"'{_kusto_quote(normalize_id(rid))}'" for rid in cfg.seedResourceIds)
        clauses.append(f"id in~ ({quoted_ids})")
    for key, value in sorted(cfg.seedTags.items(), key=lambda item: item[0].lower()):
        clauses.append(
            f"tostring(tags['{_kusto_quote(key)}']) =~ '{_kusto_quote(value)}'"
        )
    for key in sorted(cfg.seedTagKeys, key=str.lower):
        clauses.append(f"isnotempty(tostring(tags['{_kusto_quote(key)}']))")
    if not clauses:
        raise ValueError("At least one seed scope is required")
    where_clause = " or ".join(f"({clause})" for clause in clauses)
    return (
        "resources | where "
        f"{where_clause} "
        f"| {_RESOURCE_PROJECT}"
    )


def _seed_scope_summary(cfg: Config) -> str:
    parts: List[str] = []
    if cfg.seedResourceGroups:
        parts.append(f"RGs={cfg.seedResourceGroups}")
    if cfg.seedResourceIds:
        parts.append(f"resourceIds={cfg.seedResourceIds}")
    if cfg.seedTags:
        tag_parts = [f"{key}={value}" for key, value in sorted(cfg.seedTags.items(), key=lambda item: item[0].lower())]
        parts.append(f"tags={tag_parts}")
    if cfg.seedTagKeys:
        parts.append(f"tagKeys={cfg.seedTagKeys}")
    if cfg.tagFallbackToResourceGroup:
        parts.append("tagFallbackToRG=true")
    if cfg.seedManagementGroups:
        parts.append(f"managementGroups={cfg.seedManagementGroups}")
    if cfg.seedEntireSubscriptions:
        parts.append("scope=all-listed-subscriptions")
    return ", ".join(parts)


def _resource_group_seed_tag_query(cfg: Config) -> str:
    clauses: List[str] = []
    for key, value in sorted(cfg.seedTags.items(), key=lambda item: item[0].lower()):
        clauses.append(
            f"tostring(tags['{_kusto_quote(key)}']) =~ '{_kusto_quote(value)}'"
        )
    for key in sorted(cfg.seedTagKeys, key=str.lower):
        clauses.append(f"isnotempty(tostring(tags['{_kusto_quote(key)}']))")
    if not clauses:
        return ""
    where_clause = " or ".join(f"({clause})" for clause in clauses)
    return (
        "resourcecontainers "
        "| where type =~ 'microsoft.resources/subscriptions/resourcegroups' "
        f"| where {where_clause} "
        "| project id, name, subscriptionId, tags"
    )


def _seed_rows_from_matching_resource_group_tags(cfg: Config) -> List[Dict[str, Any]]:
    if not cfg.tagFallbackToResourceGroup:
        return []
    if not cfg.seedTags and not cfg.seedTagKeys:
        return []

    rg_kusto = _resource_group_seed_tag_query(cfg)
    if not rg_kusto:
        return []

    rg_rows = _query_with_cfg(rg_kusto, cfg)
    if not rg_rows:
        return []

    matched_pairs: Set[Tuple[str, str]] = set()
    matched_rg_names: Set[str] = set()
    for row in rg_rows:
        sub_id = str(row.get("subscriptionId") or "").strip().lower()
        rg_name = str(row.get("name") or "").strip().lower()
        if not sub_id or not rg_name:
            continue
        matched_pairs.add((sub_id, rg_name))
        matched_rg_names.add(rg_name)

    if not matched_pairs:
        return []

    kusto = _rg_filter(sorted(matched_rg_names))
    candidates = _query_with_cfg(kusto, cfg)
    selected: List[Dict[str, Any]] = []
    for row in candidates:
        pair = (
            str(row.get("subscriptionId") or "").strip().lower(),
            str(row.get("resourceGroup") or "").strip().lower(),
        )
        if pair in matched_pairs:
            selected.append(row)
    log.info(
        "RG tag fallback matched %d resource groups and added %d candidate seed resources",
        len(matched_pairs),
        len(selected),
    )
    return selected


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


def _append_reference(
    refs: List[Dict[str, str]],
    seen: Set[str],
    raw: Optional[str],
    *,
    path: str,
    relationship: str,
    note: str,
) -> None:
    if not raw or not isinstance(raw, str) or "/providers/" not in raw.lower():
        return
    target_id = normalize_id(raw)
    if target_id in seen:
        return
    seen.add(target_id)
    refs.append({
        "targetId": target_id,
        "path": path,
        "relationship": relationship,
        "note": note,
    })


def _extract_related_references(resource: Dict) -> List[Dict[str, str]]:
    """Extract directly-related ARM IDs with provenance details."""
    refs: List[Dict[str, str]] = []
    seen: Set[str] = set()
    t = (resource.get("type") or "").lower()
    p = resource.get("properties") or {}

    if t == "microsoft.compute/virtualmachines":
        for idx, ni in enumerate(_safe_get(p, "networkProfile", "networkInterfaces") or []):
            _append_reference(refs, seen, _safe_get(ni, "id"), path=f"properties.networkProfile.networkInterfaces[{idx}].id", relationship="vm-nic", note="VM network interface")
        _append_reference(refs, seen, _safe_get(p, "storageProfile", "osDisk", "managedDisk", "id"), path="properties.storageProfile.osDisk.managedDisk.id", relationship="vm-os-disk", note="VM OS managed disk")
        for idx, dd in enumerate(_safe_get(p, "storageProfile", "dataDisks") or []):
            _append_reference(refs, seen, _safe_get(dd, "managedDisk", "id"), path=f"properties.storageProfile.dataDisks[{idx}].managedDisk.id", relationship="vm-data-disk", note="VM data managed disk")

    elif t == "microsoft.network/networkinterfaces":
        _append_reference(refs, seen, _safe_get(p, "networkSecurityGroup", "id"), path="properties.networkSecurityGroup.id", relationship="nic-nsg", note="NIC network security group")
        for idx, ipc in enumerate(_safe_get(p, "ipConfigurations") or []):
            _append_reference(refs, seen, _safe_get(ipc, "properties", "subnet", "id"), path=f"properties.ipConfigurations[{idx}].properties.subnet.id", relationship="nic-subnet", note="NIC subnet")
            for asg_idx, asg in enumerate(_safe_get(ipc, "properties", "applicationSecurityGroups") or []):
                _append_reference(refs, seen, _safe_get(asg, "id"), path=f"properties.ipConfigurations[{idx}].properties.applicationSecurityGroups[{asg_idx}].id", relationship="nic-asg", note="NIC application security group")

    elif t == "microsoft.network/virtualnetworks/subnets" or "/subnets/" in (resource.get("id") or "").lower():
        _append_reference(refs, seen, _safe_get(p, "networkSecurityGroup", "id"), path="properties.networkSecurityGroup.id", relationship="subnet-nsg", note="Subnet network security group")
        rt_id = _safe_get(p, "routeTable", "id")
        _append_reference(refs, seen, rt_id, path="properties.routeTable.id", relationship="subnet-route-table", note="Subnet route table")

    elif t == "microsoft.network/networksecuritygroups":
        for rule_idx, rule in enumerate(_safe_get(p, "securityRules") or []):
            rp = _safe_get(rule, "properties") or {}
            for asg_idx, asg in enumerate(rp.get("sourceApplicationSecurityGroups") or []):
                _append_reference(refs, seen, _safe_get(asg, "id"), path=f"properties.securityRules[{rule_idx}].properties.sourceApplicationSecurityGroups[{asg_idx}].id", relationship="nsg-source-asg", note="NSG source application security group")
            for asg_idx, asg in enumerate(rp.get("destinationApplicationSecurityGroups") or []):
                _append_reference(refs, seen, _safe_get(asg, "id"), path=f"properties.securityRules[{rule_idx}].properties.destinationApplicationSecurityGroups[{asg_idx}].id", relationship="nsg-destination-asg", note="NSG destination application security group")

    elif t == "microsoft.network/privateendpoints":
        _append_reference(refs, seen, _safe_get(p, "subnet", "id"), path="properties.subnet.id", relationship="private-endpoint-subnet", note="Private endpoint subnet")
        for idx, conn in enumerate(_safe_get(p, "privateLinkServiceConnections") or []):
            _append_reference(refs, seen, _safe_get(conn, "properties", "privateLinkServiceId"), path=f"properties.privateLinkServiceConnections[{idx}].properties.privateLinkServiceId", relationship="private-endpoint-target", note="Private endpoint target service")

    elif t == "microsoft.network/loadbalancers":
        for pool_idx, pool in enumerate(_safe_get(p, "backendAddressPools") or []):
            for ipc_idx, ipc in enumerate(_safe_get(pool, "properties", "backendIPConfigurations") or []):
                ipc_id = _safe_get(ipc, "id")
                if ipc_id:
                    nic_id = normalize_id(ipc_id).split("/ipconfigurations/")[0]
                    _append_reference(refs, seen, nic_id, path=f"properties.backendAddressPools[{pool_idx}].properties.backendIPConfigurations[{ipc_idx}].id", relationship="load-balancer-backend-nic", note="Load balancer backend NIC")

    elif t == "microsoft.network/publicipaddresses":
        raw = _safe_get(p, "ipConfiguration", "id")
        if raw:
            nic_id = normalize_id(raw).split("/ipconfigurations/")[0]
            _append_reference(refs, seen, nic_id, path="properties.ipConfiguration.id", relationship="public-ip-nic", note="Public IP attached NIC")

    elif t == "microsoft.web/sites":
        _append_reference(refs, seen, _safe_get(p, "serverFarmId"), path="properties.serverFarmId", relationship="webapp-plan", note="App Service plan")
        _append_reference(refs, seen, _safe_get(p, "virtualNetworkSubnetId"), path="properties.virtualNetworkSubnetId", relationship="webapp-subnet", note="Web app VNet integration subnet")

    elif t == "microsoft.network/azurefirewalls":
        for idx, ipc in enumerate(_safe_get(p, "ipConfigurations") or []):
            _append_reference(refs, seen, _safe_get(ipc, "properties", "subnet", "id"), path=f"properties.ipConfigurations[{idx}].properties.subnet.id", relationship="firewall-subnet", note="Azure Firewall subnet")
            _append_reference(refs, seen, _safe_get(ipc, "properties", "publicIPAddress", "id"), path=f"properties.ipConfigurations[{idx}].properties.publicIPAddress.id", relationship="firewall-public-ip", note="Azure Firewall public IP")

    elif t == "microsoft.network/bastionhosts":
        for idx, ipc in enumerate(_safe_get(p, "ipConfigurations") or []):
            _append_reference(refs, seen, _safe_get(ipc, "properties", "subnet", "id"), path=f"properties.ipConfigurations[{idx}].properties.subnet.id", relationship="bastion-subnet", note="Bastion subnet")
            _append_reference(refs, seen, _safe_get(ipc, "properties", "publicIPAddress", "id"), path=f"properties.ipConfigurations[{idx}].properties.publicIPAddress.id", relationship="bastion-public-ip", note="Bastion public IP")

    elif t == "microsoft.app/containerapps":
        _append_reference(refs, seen, _safe_get(p, "managedEnvironmentId"), path="properties.managedEnvironmentId", relationship="containerapp-environment", note="Container App managed environment")

    elif t == "microsoft.app/managedenvironments":
        _append_reference(refs, seen, _safe_get(p, "vnetConfiguration", "infrastructureSubnetId"), path="properties.vnetConfiguration.infrastructureSubnetId", relationship="managed-environment-subnet", note="Managed environment infrastructure subnet")

    elif t == "microsoft.insights/components":
        _append_reference(refs, seen, _safe_get(p, "WorkspaceResourceId"), path="properties.WorkspaceResourceId", relationship="appinsights-workspace", note="App Insights linked workspace")

    elif t == "microsoft.network/applicationgateways":
        for idx, ipc in enumerate(_safe_get(p, "gatewayIPConfigurations") or []):
            _append_reference(refs, seen, _safe_get(ipc, "properties", "subnet", "id"), path=f"properties.gatewayIPConfigurations[{idx}].properties.subnet.id", relationship="app-gateway-subnet", note="Application Gateway subnet")

    return refs


def _extract_related_ids(resource: Dict) -> Set[str]:
    return {ref["targetId"] for ref in _extract_related_references(resource)}


def _extract_all_references(resource: Dict) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    seen: Set[tuple[str, str]] = set()

    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                next_path = f"{path}.{key}" if path else key
                _walk(value, next_path)
            return
        if isinstance(obj, list):
            for idx, value in enumerate(obj):
                _walk(value, f"{path}[{idx}]")
            return
        if isinstance(obj, str):
            for target_id in extract_arm_ids(obj):
                key = (target_id, path)
                if key in seen:
                    continue
                seen.add(key)
                refs.append({
                    "targetId": target_id,
                    "path": path,
                    "relationship": "arm-reference",
                    "note": f"ARM ID extracted from {path}",
                })

    _walk(resource.get("properties") or {}, "properties")
    return refs


def _reverse_attachment_queries(nic_ids: Iterable[str]) -> List[str]:
    normalized_nics = sorted({normalize_id(rid) for rid in nic_ids if rid})
    if not normalized_nics:
        return []
    quoted_nics = ", ".join(f"'{_kusto_quote(rid)}'" for rid in normalized_nics)
    return [
        (
            "resources "
            "| where type =~ 'microsoft.network/loadBalancers' "
            "| mv-expand backendAddressPool = properties.backendAddressPools to typeof(dynamic) "
            "| mv-expand backendIpConfiguration = backendAddressPool.properties.backendIPConfigurations to typeof(dynamic) "
            "| extend matchedTargetId = tolower(split(tostring(backendIpConfiguration.id), '/ipconfigurations/')[0]) "
            f"| where matchedTargetId in~ ({quoted_nics}) "
            f"| {_RESOURCE_PROJECT}, matchedTargetId"
        ),
        (
            "resources "
            "| where type =~ 'microsoft.network/publicIPAddresses' "
            "| extend matchedTargetId = tolower(split(tostring(properties.ipConfiguration.id), '/ipconfigurations/')[0]) "
            f"| where matchedTargetId in~ ({quoted_nics}) "
            f"| {_RESOURCE_PROJECT}, matchedTargetId"
        ),
    ]


def _find_reverse_attachment_references(collected: Dict[str, Dict], cfg: Config) -> List[Dict[str, str]]:
    nic_ids = [
        rid
        for rid, resource in collected.items()
        if str(resource.get("type", "")).lower() == "microsoft.network/networkinterfaces"
    ]
    refs: List[Dict[str, str]] = []
    seen: Set[tuple[str, str]] = set()
    for kusto in _reverse_attachment_queries(nic_ids):
        for row in _query_reverse_related_with_cfg(kusto, cfg):
            target_id = normalize_id(row.get("id", ""))
            matched_target = normalize_id(row.get("matchedTargetId", ""))
            if not target_id or not matched_target:
                continue
            relation_type = str(row.get("type", "")).lower()
            if relation_type == "microsoft.network/loadbalancers":
                relationship = "backend-nic-load-balancer"
                note = "Load balancer backend pool contains discovered NIC"
            elif relation_type == "microsoft.network/publicipaddresses":
                relationship = "nic-public-ip"
                note = "Public IP is attached to discovered NIC"
            else:
                continue
            key = (target_id, matched_target)
            if key in seen:
                continue
            seen.add(key)
            refs.append({
                "targetId": target_id,
                "sourceId": matched_target,
                "path": "reverse-attachment",
                "relationship": relationship,
                "note": note,
            })
    return refs


def _derive_parent_references(referenced: Iterable[str]) -> List[Dict[str, str]]:
    parents: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for rid in referenced:
        nid = normalize_id(rid)
        if "/subnets/" not in nid:
            continue
        vnet_id = nid.split("/subnets/")[0]
        if vnet_id in seen:
            continue
        seen.add(vnet_id)
        parents.append({
            "targetId": vnet_id,
            "sourceId": nid,
            "path": "derived-parent",
            "relationship": "subnet-parent-vnet",
            "note": "Derived parent VNet from subnet resource ID",
        })
    return parents


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
) -> Set[str]:
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
    return resolved_from_vnet


def _resource_search_haystacks(resource: Dict[str, Any]) -> Dict[str, str]:
    return {
        "name": str(resource.get("name") or ""),
        "tags": json.dumps(resource.get("tags") or {}, sort_keys=True),
        "properties": json.dumps(resource.get("properties") or {}, sort_keys=True),
    }


def _matching_search_details(resource: Dict[str, Any], search_strings: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    matched_fields: Dict[str, List[str]] = {}
    if not search_strings:
        return [], matched_fields
    for field, haystack in _resource_search_haystacks(resource).items():
        lowered = haystack.lower()
        matched = sorted({term for term in search_strings if term.lower() in lowered}, key=str.lower)
        if matched:
            matched_fields[field] = matched
    merged = sorted({term for values in matched_fields.values() for term in values}, key=str.lower)
    return merged, matched_fields


def _matching_inventory_context(resource: Dict[str, Any], inventory: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    matched_terms = [term for term in resource.get(_DEEP_MATCH_FIELD, []) if isinstance(term, str) and term]
    if not matched_terms:
        return []

    resource_id = normalize_id(resource.get("id", ""))
    outgoing_refs: Dict[str, List[Dict[str, str]]] = {}
    for ref in _extract_all_references(resource):
        outgoing_refs.setdefault(ref["targetId"], []).append(ref)

    hits: List[Dict[str, str]] = []
    for candidate in inventory:
        candidate_id = normalize_id(candidate.get("id", ""))
        if not candidate_id or candidate_id == resource_id:
            continue

        associations: List[str] = []
        related_matches, related_fields = _matching_search_details(candidate, matched_terms)
        if related_matches:
            field_text = ", ".join(sorted(related_fields))
            associations.append(f"shared matched terms in base inventory {field_text}")

        if candidate_id in outgoing_refs:
            ref = outgoing_refs[candidate_id][0]
            associations.append(f"candidate refers to base inventory via {ref.get('path', 'properties')}")

        incoming_refs = [ref for ref in _extract_all_references(candidate) if ref.get("targetId") == resource_id]
        if incoming_refs:
            associations.append(f"base inventory refers to candidate via {incoming_refs[0].get('path', 'properties')}")

        has_direct_reference = candidate_id in outgoing_refs or bool(incoming_refs)
        if not has_direct_reference and str(candidate.get("type", "")).lower().startswith("microsoft.network/"):
            continue

        if not associations:
            continue

        hits.append({
            "id": candidate.get("id", ""),
            "name": candidate.get("name", ""),
            "type": candidate.get("type", ""),
            "resourceGroup": candidate.get("resourceGroup", ""),
            "subscriptionId": candidate.get("subscriptionId", ""),
            "matchedTerms": ", ".join(related_matches),
            "association": "; ".join(associations),
            "hasDirectReference": "yes" if len(associations) > (1 if related_matches else 0) else "no",
        })

    hits.sort(key=lambda item: (item["hasDirectReference"] != "yes", item["name"].lower(), item["id"]))
    return hits[:5]


def _candidate_evidence(
    resource: Dict[str, Any],
    matches: List[str],
    matched_fields: Dict[str, List[str]],
    inventory: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not matches:
        return []
    name = resource.get("name") or "<unnamed>"
    field_names = sorted(matched_fields)
    field_label = ", ".join(field_names) if field_names else "name"
    evidence: List[Dict[str, Any]] = [{
        "source": "deep-discovery",
        "matchField": field_label,
        "matchFields": field_names,
        "matchedTerms": matches,
        "explanation": f"Candidate surfaced because search strings matched resource {field_label}: {', '.join(matches)} ({name}).",
    }]
    related = _matching_inventory_context(resource, inventory)
    if related:
        evidence.append({
            "source": "base-inventory",
            "matchField": "shared-terms-or-references",
            "matchedTerms": matches,
            "explanation": "Potential in-scope context found in the base inventory through shared matched terms or direct ARM references.",
            "relatedResources": related,
        })
    return evidence


def write_related_review_report(
    cfg: Config,
    inventory: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    promoted_ids: Optional[Set[str]] = None,
) -> Path:
    promoted = promoted_ids if promoted_ids is not None else {normalize_id(item.get("id", "")) for item in candidates if item.get("id")}
    report_path = cfg.deep_out(_RELATED_REVIEW_REPORT)
    lines = [
        f"# Related Resource Review for {cfg.app}",
        "",
        f"- Base inventory resources: {len(inventory)}",
        f"- Candidate resources: {len(candidates)}",
        f"- Currently promoted: {sum(1 for item in candidates if normalize_id(item.get('id', '')) in promoted)}",
        "",
    ]
    if not candidates:
        lines.append("_No related candidates found._")
        report_path.write_text("\n".join(lines) + "\n")
        return report_path

    for idx, item in enumerate(candidates, start=1):
        rid = normalize_id(item.get("id", ""))
        status = "kept" if rid in promoted else "dropped"
        lines.extend([
            f"## {idx}. {item.get('name', '<unnamed>')} [{status}]",
            "",
            f"- Type: `{item.get('type', '')}`",
            f"- Resource group: `{item.get('resourceGroup', '')}`",
            f"- Subscription: `{item.get('subscriptionId', '')}`",
            f"- ID: `{item.get('id', '')}`",
        ])
        for evidence in item.get(_DEEP_REASON_FIELD, []):
            lines.append(f"- Why: {evidence.get('explanation', '')}")
            related = evidence.get("relatedResources") or []
            if related:
                related_text = "; ".join(
                    f"{entry.get('name', '<unnamed>')} ({entry.get('matchedTerms', '') or 'direct reference'}; {entry.get('association', 'associated')})"
                    for entry in related
                )
                lines.append(f"- Base context: {related_text}")
        lines.append("")
    report_path.write_text("\n".join(lines) + "\n")
    return report_path


def run_seed(cfg: Config) -> List[Dict]:
    log.info("Seeding resources from: %s", _seed_scope_summary(cfg))
    rows = _query_with_cfg(_seed_query(cfg), cfg)
    rows.extend(_seed_rows_from_matching_resource_group_tags(cfg))
    deduped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        rid = normalize_id(row.get("id", ""))
        if not rid:
            continue
        deduped[rid] = row
    rows = [deduped[rid] for rid in sorted(deduped)]
    cfg.ensure_output_dir()
    out = cfg.out("seed.json")
    out.write_text(json.dumps(rows, indent=2, sort_keys=True))
    log.info("Wrote %d seed resources to %s", len(rows), out)
    return rows


def _deep_discovery_query(cfg: Config) -> str:
    if not cfg.deepDiscovery.searchStrings:
        raise ValueError("deepDiscovery.searchStrings must include at least one value")
    clauses = [
        (
            f"name contains '{_kusto_quote(term)}' "
            f"or tostring(tags) contains '{_kusto_quote(term)}' "
            f"or tostring(properties) contains '{_kusto_quote(term)}'"
        )
        for term in cfg.deepDiscovery.searchStrings
    ]
    where_clause = " or ".join(f"({clause})" for clause in clauses)
    return f"resources | where {where_clause} | {_RESOURCE_PROJECT}"


def _matching_search_strings(resource: Dict[str, Any], search_strings: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    return _matching_search_details(resource, search_strings)


def _load_inventory_artifact(path: Path, context: str) -> List[Dict[str, Any]]:
    return load_json_file(
        path,
        context=context,
        expected_type=list,
        advice=f"Fix {path.name} or rerun the producing stage.",
    )


def run_related_candidates(cfg: Config) -> List[Dict]:
    if not cfg.deepDiscovery.enabled:
        raise ValueError("deepDiscovery.enabled must be true to run related candidate discovery")

    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' or 'run' first.")
    inventory = _load_inventory_artifact(inv_path, "Deep discovery base inventory")
    existing_ids = {normalize_id(r.get("id", "")) for r in inventory if r.get("id")}

    rows = _query_with_cfg(_deep_discovery_query(cfg), cfg)
    deduped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        rid = normalize_id(row.get("id", ""))
        if not rid or rid in existing_ids:
            continue
        matches, matched_fields = _matching_search_strings(row, cfg.deepDiscovery.searchStrings)
        if not matches:
            continue
        entry = dict(row)
        prior = deduped.get(rid)
        merged_matches = sorted(set((prior or {}).get(_DEEP_MATCH_FIELD, [])) | set(matches), key=str.lower)
        entry[_DEEP_MATCH_FIELD] = merged_matches
        entry[_DEEP_REASON_FIELD] = _candidate_evidence(entry, merged_matches, matched_fields, inventory)
        deduped[rid] = entry

    candidates = sorted(deduped.values(), key=lambda r: (r.get("subscriptionId", ""), r.get("resourceGroup", ""), r.get("name", ""), r.get("id", "")))
    cfg.ensure_deep_output_dir()
    candidate_path = cfg.deep_out(cfg.deepDiscovery.candidateFile)
    promoted_path = cfg.deep_out(cfg.deepDiscovery.promotedFile)
    payload = json.dumps(candidates, indent=2, sort_keys=True)
    candidate_path.write_text(payload)
    promoted_path.write_text(payload)
    write_related_review_report(cfg, inventory, candidates)
    log.info("Wrote %d related candidates to %s and initialized promoted list at %s", len(candidates), candidate_path, promoted_path)
    return candidates


def _reason_entry(source: Dict[str, Any], ref: Dict[str, str], iteration: int, extraction_mode: str) -> Dict[str, Any]:
    return {
        "sourceId": normalize_id(source.get("id", "")),
        "sourceName": source.get("name", ""),
        "sourceType": source.get("type", ""),
        "iteration": iteration,
        "extractionMode": extraction_mode,
        "path": ref.get("path", ""),
        "relationship": ref.get("relationship", ""),
        "note": ref.get("note", ""),
    }


def _append_discovery_reason(reason_map: Dict[str, List[Dict[str, Any]]], target_id: str, reason: Dict[str, Any]) -> None:
    bucket = reason_map.setdefault(target_id, [])
    key = (reason.get("sourceId"), reason.get("path"), reason.get("relationship"), reason.get("extractionMode"))
    for existing in bucket:
        existing_key = (existing.get("sourceId"), existing.get("path"), existing.get("relationship"), existing.get("extractionMode"))
        if existing_key == key:
            return
    bucket.append(reason)


def _write_expand_reason_artifacts(
    cfg: Config,
    seed_ids: Set[str],
    collected: Dict[str, Dict[str, Any]],
    unresolved: Set[str],
    reason_map: Dict[str, List[Dict[str, Any]]],
    synthesized_ids: Set[str],
) -> None:
    added_resources: List[Dict[str, Any]] = []
    for rid in sorted(set(reason_map) - seed_ids):
        if rid not in collected:
            continue
        resource = collected[rid]
        status = "synthesized" if rid in synthesized_ids else "fetched"
        added_resources.append({
            "resourceId": rid,
            "resourceName": resource.get("name", ""),
            "resourceType": resource.get("type", ""),
            "resourceGroup": resource.get("resourceGroup", ""),
            "subscriptionId": resource.get("subscriptionId", ""),
            "status": status,
            "reasons": reason_map.get(rid, []),
        })

    unresolved_entries = [
        {
            "resourceId": rid,
            "status": "unresolved",
            "reasons": reason_map.get(rid, []),
        }
        for rid in sorted(unresolved)
    ]
    payload = {
        "expandScope": cfg.expandScope,
        "seedCount": len(seed_ids),
        "addedResources": added_resources,
        "unresolvedReferences": unresolved_entries,
    }
    cfg.ensure_output_dir()
    cfg.out(_EXPAND_REASONS_FILE).write_text(json.dumps(payload, indent=2, sort_keys=True))

    lines = [
        f"# Expand Provenance for {cfg.app}",
        "",
        f"- Expand scope: `{cfg.expandScope}`",
        f"- Seed resources: {len(seed_ids)}",
        f"- Added resources: {len(added_resources)}",
        f"- Unresolved references: {len(unresolved_entries)}",
        "",
    ]
    if added_resources:
        lines.append("## Added Resources")
        lines.append("")
        for item in added_resources:
            lines.extend([
                f"### {item['resourceName'] or item['resourceId']} [{item['status']}]",
                "",
                f"- Type: `{item['resourceType']}`",
                f"- ID: `{item['resourceId']}`",
            ])
            for reason in item["reasons"]:
                lines.append(
                    f"- Because `{reason.get('sourceName') or reason.get('sourceId')}` referenced `{reason.get('path')}` ({reason.get('note')})."
                )
            lines.append("")
    if unresolved_entries:
        lines.append("## Unresolved References")
        lines.append("")
        for item in unresolved_entries:
            lines.append(f"### {item['resourceId']}")
            lines.append("")
            for reason in item["reasons"]:
                lines.append(
                    f"- Referenced by `{reason.get('sourceName') or reason.get('sourceId')}` via `{reason.get('path')}` ({reason.get('note')})."
                )
            lines.append("")
    cfg.out(_EXPAND_REASONS_REPORT).write_text("\n".join(lines) + "\n")


def _expand_resources(
    cfg: Config,
    seed: List[Dict[str, Any]],
    *,
    software_inventory_workspace: Optional[str] = None,
    software_inventory_days: int = 30,
) -> None:
    collected: Dict[str, Dict] = {normalize_id(r["id"]): r for r in seed}
    seed_ids = set(collected.keys())
    unresolved: Set[str] = set()
    reason_map: Dict[str, List[Dict[str, Any]]] = {}

    use_scoped = cfg.expandScope == "related"
    extraction_mode = "related" if use_scoped else "all"
    if use_scoped:
        log.info("Using scoped expansion (expandScope=related). Set expandScope=all to follow every ARM reference.")
    else:
        log.info("Using full expansion (expandScope=all). All ARM references will be followed.")

    for iteration in range(_MAX_ITERATIONS):
        referenced: Set[str] = set()
        for resource in collected.values():
            references = _extract_related_references(resource) if use_scoped else _extract_all_references(resource)
            for ref in references:
                target_id = normalize_id(ref["targetId"])
                referenced.add(target_id)
                _append_discovery_reason(reason_map, target_id, _reason_entry(resource, ref, iteration + 1, extraction_mode))
            referenced.add(normalize_id(resource["id"]))
        referenced = {normalize_id(item) for item in referenced}

        parent_refs = _derive_parent_references(referenced)
        for ref in parent_refs:
            target_id = normalize_id(ref["targetId"])
            referenced.add(target_id)
            source = collected.get(ref["sourceId"], {"id": ref["sourceId"], "name": ref["sourceId"], "type": "derived"})
            _append_discovery_reason(reason_map, target_id, _reason_entry(source, ref, iteration + 1, extraction_mode))

        if use_scoped:
            reverse_refs = _find_reverse_attachment_references(collected, cfg)
            for ref in reverse_refs:
                target_id = normalize_id(ref["targetId"])
                referenced.add(target_id)
                source = collected.get(ref["sourceId"], {"id": ref["sourceId"], "name": ref["sourceId"], "type": "derived"})
                _append_discovery_reason(reason_map, target_id, _reason_entry(source, ref, iteration + 1, extraction_mode))

        missing = referenced - set(collected.keys()) - unresolved
        if not missing:
            log.info("Expansion converged after %d iteration(s).", iteration)
            break
        log.info("Iteration %d: fetching %d missing resources", iteration + 1, len(missing))
        fetched: List[Dict[str, Any]] = []
        for resource_id in sorted(missing):
            fetched.extend(_query_by_ids_with_cfg([resource_id], cfg))
        fetched_ids = set()
        for resource in fetched:
            nid = normalize_id(resource["id"])
            collected[nid] = resource
            fetched_ids.add(nid)
        still_missing = missing - fetched_ids
        unresolved.update(still_missing)
        log.debug("Still unresolved: %d", len(still_missing))
    else:
        log.warning("Expansion hit max iterations (%d).", _MAX_ITERATIONS)

    synthesized_ids = {normalize_id(item) for item in _synthesize_subnets_from_vnets(collected, unresolved)}
    for synthesized_id in synthesized_ids:
        vnet_id = synthesized_id.split("/subnets/")[0]
        source = collected.get(vnet_id, {"id": vnet_id, "name": vnet_id, "type": "Microsoft.Network/virtualNetworks"})
        _append_discovery_reason(reason_map, synthesized_id, {
            "sourceId": normalize_id(source.get("id", "")),
            "sourceName": source.get("name", ""),
            "sourceType": source.get("type", ""),
            "iteration": _MAX_ITERATIONS,
            "extractionMode": extraction_mode,
            "path": "properties.subnets[]",
            "relationship": "synthesized-subnet",
            "note": "Subnet synthesized from parent VNet properties because ARG did not return it as a standalone resource",
        })

    inventory = sorted(collected.values(), key=lambda r: normalize_id(r["id"]))
    cfg.ensure_output_dir()
    cfg.out("inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True))
    cfg.out("unresolved.json").write_text(json.dumps(sorted(unresolved), indent=2))
    _write_expand_reason_artifacts(cfg, seed_ids, collected, unresolved, reason_map, synthesized_ids)
    if software_inventory_workspace:
        generate_software_inventory_csv(
            cfg,
            software_inventory_workspace,
            days=software_inventory_days,
            inventory=inventory,
        )
    log.info("Wrote inventory (%d resources) and unresolved (%d IDs)", len(inventory), len(unresolved))


def prepare_related_extended_inventory(cfg: Config) -> Config:
    if not cfg.deepDiscovery.enabled:
        raise ValueError("deepDiscovery.enabled must be true to build an extended related-resource pack")

    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' or 'run' first.")
    promoted_path = cfg.deep_out(cfg.deepDiscovery.promotedFile)
    if not promoted_path.exists():
        raise FileNotFoundError(f"Promoted related resource file not found at {promoted_path}. Run 'related-candidates' first and curate the promoted file.")

    base_inventory = _load_inventory_artifact(inv_path, "Extended pack base inventory")
    promoted_inventory = _load_inventory_artifact(promoted_path, "Extended pack promoted related resources")

    merged: Dict[str, Dict[str, Any]] = {normalize_id(r["id"]): dict(r) for r in base_inventory if r.get("id")}
    for resource in promoted_inventory:
        rid = normalize_id(resource.get("id", ""))
        if not rid:
            continue
        merged[rid] = dict(resource)

    extended_cfg = cfg.with_output_dir(str(cfg.extended_output_dir()))
    extended_cfg.ensure_output_dir()
    extended_seed = sorted(merged.values(), key=lambda r: normalize_id(r.get("id", "")))
    extended_cfg.out("seed.json").write_text(json.dumps(extended_seed, indent=2, sort_keys=True))
    log.info("Prepared extended seed with %d resources at %s", len(extended_seed), extended_cfg.outputDir)
    return extended_cfg


def run_expand(
    cfg: Config,
    *,
    software_inventory_workspace: Optional[str] = None,
    software_inventory_days: int = 30,
) -> None:
    seed_path = cfg.out("seed.json")
    if not seed_path.exists():
        raise FileNotFoundError(f"seed.json not found at {seed_path}. Run 'seed' first.")
    seed: List[Dict] = load_json_file(
        seed_path,
        context="Seed stage artifact",
        expected_type=list,
        advice="Fix seed.json or rerun the seed stage.",
    )

    _expand_resources(
        cfg,
        seed,
        software_inventory_workspace=software_inventory_workspace,
        software_inventory_days=software_inventory_days,
    )


def run_rbac(cfg: Config) -> None:
    if not cfg.includeRbac:
        log.info("RBAC disabled in config.")
        return
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' first.")
    inventory: List[Dict] = load_json_file(
        inv_path,
        context="Expand stage artifact",
        expected_type=list,
        advice="Fix inventory.json or rerun the expand stage.",
    )
    scopes = {normalize_id(r["id"]) for r in inventory}
    scopes.update({r.get("resourceGroup", "").lower() for r in inventory if r.get("resourceGroup")})

    # Query role assignments via authorizationresources
    kusto = "authorizationresources | where type =~ 'microsoft.authorization/roleassignments' | project id, name, type, properties"
    rows = _query_with_cfg(kusto, cfg)
    # Filter to relevant scopes
    relevant = [r for r in rows if normalize_id(r.get("properties", {}).get("scope", "")) in scopes or
                any(normalize_id(r.get("properties", {}).get("scope", "")).startswith(s) for s in scopes)]
    relevant = _enrich_rbac_rows(relevant, cfg)
    cfg.ensure_output_dir()
    cfg.out("rbac.json").write_text(json.dumps(relevant, indent=2, sort_keys=True))
    log.info("Wrote %d RBAC assignments to rbac.json", len(relevant))


def _policy_query_for_ids(resource_ids: List[str]) -> str:
    quoted_ids = ", ".join(f"'{_kusto_quote(resource_id)}'" for resource_id in resource_ids)
    return (
        "policyresources "
        "| where type =~ 'microsoft.policyinsights/policystates' "
        f"| where tostring(properties.resourceId) in~ ({quoted_ids}) "
        "| project id, name, type, subscriptionId, resourceGroup, properties"
    )


def _simplify_policy_row(row: Dict[str, Any]) -> Dict[str, Any]:
    properties = row.get("properties") or {}
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "type": row.get("type"),
        "subscriptionId": row.get("subscriptionId"),
        "resourceGroup": row.get("resourceGroup"),
        "resourceId": properties.get("resourceId"),
        "resourceLocation": properties.get("resourceLocation"),
        "resourceType": properties.get("resourceType"),
        "complianceState": properties.get("complianceState"),
        "policyAssignmentId": properties.get("policyAssignmentId"),
        "policyAssignmentName": properties.get("policyAssignmentName"),
        "policyAssignmentScope": properties.get("policyAssignmentScope"),
        "policyDefinitionId": properties.get("policyDefinitionId"),
        "policyDefinitionName": properties.get("policyDefinitionName"),
        "policyDefinitionReferenceId": properties.get("policyDefinitionReferenceId"),
        "policySetDefinitionId": properties.get("policySetDefinitionId"),
        "policySetDefinitionName": properties.get("policySetDefinitionName"),
        "timestamp": properties.get("timestamp"),
        "properties": properties,
    }


def _policy_identity_key(row: Dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        normalize_id(row.get("resourceId") or ""),
        normalize_id(row.get("policyAssignmentId") or ""),
        (row.get("policyDefinitionReferenceId") or "").strip().lower(),
        normalize_id(row.get("policyDefinitionId") or ""),
    )


def _policy_timestamp_key(row: Dict[str, Any]) -> str:
    return (row.get("timestamp") or "").strip()


def _latest_policy_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    for row in rows:
        identity = _policy_identity_key(row)
        current = latest.get(identity)
        if current is None or _policy_timestamp_key(row) >= _policy_timestamp_key(current):
            latest[identity] = row
    return list(latest.values())


def run_policy(cfg: Config) -> None:
    if not cfg.includePolicy:
        log.info("Azure Policy collection disabled in config.")
        return

    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError("inventory.json not found. Run 'expand' first.")
    inventory: List[Dict] = load_json_file(
        inv_path,
        context="Expand stage artifact",
        expected_type=list,
        advice="Fix inventory.json or rerun the expand stage.",
    )

    resource_ids = sorted({normalize_id(resource["id"]) for resource in inventory if resource.get("id")})
    if not resource_ids:
        cfg.ensure_output_dir()
        cfg.out("policy.json").write_text("[]\n")
        log.info("No inventory resources found. Wrote empty policy.json")
        return

    policy_rows: List[Dict[str, Any]] = []
    for start in range(0, len(resource_ids), _POLICY_BATCH_SIZE):
        batch = resource_ids[start:start + _POLICY_BATCH_SIZE]
        policy_rows.extend(_query_with_cfg(_policy_query_for_ids(batch), cfg))

    relevant: List[Dict[str, Any]] = []
    resource_id_set = set(resource_ids)
    for row in policy_rows:
        normalized_resource_id = normalize_id(((row.get("properties") or {}).get("resourceId") or ""))
        if normalized_resource_id in resource_id_set:
            relevant.append(_simplify_policy_row(row))

    relevant = _latest_policy_rows(relevant)
    relevant.sort(
        key=lambda row: (
            normalize_id(row.get("resourceId") or ""),
            (row.get("policyAssignmentName") or "").lower(),
            (row.get("policyDefinitionName") or "").lower(),
            (row.get("complianceState") or "").lower(),
        )
    )

    cfg.ensure_output_dir()
    cfg.out("policy.json").write_text(json.dumps(relevant, indent=2, sort_keys=True))
    log.info("Wrote %d Azure Policy state records to policy.json", len(relevant))
