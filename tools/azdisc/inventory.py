"""Generate inventory and policy exports from inventory.json and policy.json."""
from __future__ import annotations

import csv
import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .azcli import run_az_json
from .config import Config
from .governance import normalize_compliance_state
from .util import get_in, load_json_file, normalize_id

log = logging.getLogger(__name__)


def _format_tags(tags: Any) -> str:
    if not tags or not isinstance(tags, dict):
        return ""
    return "; ".join(f"{k}={v}" for k, v in sorted(tags.items()))


def _load_inventory(cfg: Config) -> List[Dict]:
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError(
            f"inventory.json not found at {inv_path}. Run 'expand' (or 'run') first."
        )
    return load_json_file(
        inv_path,
        context="Inventory export input",
        expected_type=list,
        advice="Fix inventory.json or rerun the expand stage.",
    )


def _load_policy(cfg: Config) -> List[Dict]:
    policy_path = cfg.out("policy.json")
    if not policy_path.exists():
        raise FileNotFoundError(
            f"policy.json not found at {policy_path}. Run 'policy' (or 'run') first."
        )
    return load_json_file(
        policy_path,
        context="Policy export input",
        expected_type=list,
        advice="Fix policy.json or rerun the policy stage.",
    )


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "Name", "Type", "Location", "ResourceGroup", "SubscriptionId",
    "ProvisioningState", "Tags", "CreatedDate", "CreatedBy", "SkuName",
]

_SOFTWARE_INVENTORY_FIELDS = [
    "VmName", "VmResourceId", "SubscriptionId", "ResourceGroup", "Location",
    "Computer", "SoftwareName", "CurrentVersion", "Publisher", "TimeGenerated",
]


def generate_csv(cfg: Config) -> Path:
    """Read inventory.json and write inventory.csv to outputDir."""
    inventory = _load_inventory(cfg)
    out_path = cfg.out("inventory.csv")

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for r in inventory:
            writer.writerow({
                "Name": r.get("name", ""),
                "Type": r.get("type", ""),
                "Location": r.get("location", ""),
                "ResourceGroup": r.get("resourceGroup", ""),
                "SubscriptionId": r.get("subscriptionId", ""),
                "ProvisioningState": get_in(r, "properties", "provisioningState") or "",
                "Tags": _format_tags(r.get("tags")),
                "CreatedDate": get_in(r, "systemData", "createdAt") or "",
                "CreatedBy": get_in(r, "systemData", "createdBy") or "",
                "SkuName": get_in(r, "sku", "name") or "",
            })

    log.info("Wrote inventory CSV (%d rows) to %s", len(inventory), out_path)
    return out_path


def _software_table_rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        tables = data.get("tables")
        if isinstance(tables, list) and tables:
            table = tables[0]
            columns = [str(col.get("name", "")) for col in table.get("columns", []) if isinstance(col, dict)]
            rows = table.get("rows", [])
            if isinstance(rows, list):
                return [
                    {columns[idx]: values[idx] if idx < len(values) else None for idx in range(len(columns))}
                    for values in rows
                    if isinstance(values, list)
                ]
        value = data.get("value")
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    raise RuntimeError("Unsupported Log Analytics query result shape.")


def _vm_inventory_rows(inventory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in inventory:
        if normalize_id(item.get("type") or "") != "microsoft.compute/virtualmachines":
            continue
        vm_id = normalize_id(item.get("id") or "")
        if not vm_id:
            continue
        name = str(item.get("name") or "")
        rows.append({
            "id": vm_id,
            "name": name,
            "name_lower": name.lower(),
            "name_short_lower": name.split(".")[0].lower() if name else "",
            "subscriptionId": item.get("subscriptionId", ""),
            "resourceGroup": item.get("resourceGroup", ""),
            "location": item.get("location", ""),
        })
    return rows


def _match_software_row(vm_rows: List[Dict[str, Any]], row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("AzureResourceId", "_ResourceId", "ResourceId", "resourceId"):
        value = row.get(key)
        if isinstance(value, str) and "/subscriptions/" in value.lower():
            normalized = normalize_id(value)
            for vm in vm_rows:
                if vm["id"] == normalized:
                    return vm

    computer = str(row.get("Computer") or row.get("computer") or "").strip().lower()
    if not computer:
        return None
    computer_short = computer.split(".")[0]
    for vm in vm_rows:
        if computer in {vm["name_lower"], vm["name_short_lower"]}:
            return vm
        if computer_short and computer_short in {vm["name_lower"], vm["name_short_lower"]}:
            return vm
    return None


def generate_software_inventory_csv(
    cfg: Config,
    workspace: str,
    *,
    days: int = 30,
    inventory: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """Query Change Tracking / Inventory software data and write software_inventory.csv."""
    if days < 1:
        raise ValueError(f"software inventory lookback days must be positive, got {days!r}")

    if inventory is None:
        inventory = _load_inventory(cfg)
    vm_rows = _vm_inventory_rows(inventory)
    out_path = cfg.out("software_inventory.csv")

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_SOFTWARE_INVENTORY_FIELDS)
        writer.writeheader()

        if not vm_rows:
            log.info("No virtual machines found in inventory; wrote empty software inventory CSV to %s", out_path)
            return out_path

        query = "\n".join([
            "ConfigurationData",
            '| where ConfigDataType == "Software"',
            "| summarize arg_max(TimeGenerated, *) by Computer, SoftwareName",
        ])
        data = run_az_json([
            "monitor", "log-analytics", "query",
            "--workspace", workspace,
            "--analytics-query", query,
            "--timespan", f"P{days}D",
        ])
        software_rows = _software_table_rows(data)

        written = 0
        for row in software_rows:
            vm = _match_software_row(vm_rows, row)
            if vm is None:
                continue
            writer.writerow({
                "VmName": vm["name"],
                "VmResourceId": vm["id"],
                "SubscriptionId": vm["subscriptionId"],
                "ResourceGroup": vm["resourceGroup"],
                "Location": vm["location"],
                "Computer": row.get("Computer") or row.get("computer") or "",
                "SoftwareName": row.get("SoftwareName") or row.get("softwareName") or "",
                "CurrentVersion": row.get("CurrentVersion") or row.get("currentVersion") or "",
                "Publisher": row.get("Publisher") or row.get("publisher") or "",
                "TimeGenerated": row.get("TimeGenerated") or row.get("timeGenerated") or "",
            })
            written += 1

    log.info(
        "Wrote software inventory CSV (%d rows across %d VMs) to %s",
        written,
        len(vm_rows),
        out_path,
    )
    return out_path


# ---------------------------------------------------------------------------
# Policy CSV/YAML exports
# ---------------------------------------------------------------------------

_POLICY_CSV_FIELDS = [
    "ResourceName", "ResourceId", "ResourceType", "ResourceGroup", "SubscriptionId",
    "ComplianceState", "PolicyAssignmentName", "PolicyDefinitionName", "PolicyDefinitionReferenceId",
    "PolicyAssignmentId", "PolicyDefinitionId", "PolicySetDefinitionName", "PolicySetDefinitionId",
    "PolicyAssignmentScope", "ResourceLocation", "Timestamp",
]


def _policy_resource_name(row: Dict) -> str:
    resource_id = normalize_id(row.get("resourceId") or "")
    if not resource_id:
        return "unknown"
    return resource_id.rstrip("/").split("/")[-1]


def _policy_sort_key(row: Dict) -> tuple[str, str, str, str]:
    return (
        normalize_id(row.get("resourceId") or ""),
        (row.get("policyAssignmentName") or "").lower(),
        (row.get("policyDefinitionName") or "").lower(),
        normalize_compliance_state(row.get("complianceState")),
    )


def _build_policy_entry(row: Dict) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "resourceName": _policy_resource_name(row),
        "resourceId": row.get("resourceId") or "",
        "resourceType": row.get("resourceType") or "",
        "resourceGroup": row.get("resourceGroup") or "",
        "subscriptionId": row.get("subscriptionId") or "",
        "complianceState": normalize_compliance_state(row.get("complianceState")),
        "policyAssignmentName": row.get("policyAssignmentName") or "",
        "policyDefinitionName": row.get("policyDefinitionName") or "",
        "timestamp": row.get("timestamp") or "",
    }
    for field in (
        "policyDefinitionReferenceId",
        "policyAssignmentId",
        "policyDefinitionId",
        "policySetDefinitionName",
        "policySetDefinitionId",
        "policyAssignmentScope",
        "resourceLocation",
    ):
        value = row.get(field)
        if value not in (None, ""):
            entry[field] = value
    return entry


def generate_policy_csv(cfg: Config) -> Path:
    policy_rows = sorted(_load_policy(cfg), key=_policy_sort_key)
    out_path = cfg.out("policy.csv")

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_POLICY_CSV_FIELDS)
        writer.writeheader()
        for row in policy_rows:
            writer.writerow({
                "ResourceName": _policy_resource_name(row),
                "ResourceId": row.get("resourceId", ""),
                "ResourceType": row.get("resourceType", ""),
                "ResourceGroup": row.get("resourceGroup", ""),
                "SubscriptionId": row.get("subscriptionId", ""),
                "ComplianceState": normalize_compliance_state(row.get("complianceState")),
                "PolicyAssignmentName": row.get("policyAssignmentName", ""),
                "PolicyDefinitionName": row.get("policyDefinitionName", ""),
                "PolicyDefinitionReferenceId": row.get("policyDefinitionReferenceId", ""),
                "PolicyAssignmentId": row.get("policyAssignmentId", ""),
                "PolicyDefinitionId": row.get("policyDefinitionId", ""),
                "PolicySetDefinitionName": row.get("policySetDefinitionName", ""),
                "PolicySetDefinitionId": row.get("policySetDefinitionId", ""),
                "PolicyAssignmentScope": row.get("policyAssignmentScope", ""),
                "ResourceLocation": row.get("resourceLocation", ""),
                "Timestamp": row.get("timestamp", ""),
            })

    log.info("Wrote policy CSV (%d rows) to %s", len(policy_rows), out_path)
    return out_path


def generate_policy_yaml(cfg: Config) -> Path:
    policy_rows = sorted(_load_policy(cfg), key=_policy_sort_key)

    by_resource: Dict[str, Dict[str, Any]] = {}
    by_policy: Dict[str, Dict[str, Any]] = {}
    for row in policy_rows:
        resource_name = _policy_resource_name(row)
        resource_key = f"{resource_name} ({normalize_id(row.get('resourceId') or '')})"
        policy_label = row.get("policyAssignmentName") or row.get("policyDefinitionName") or "Unnamed policy"
        by_resource.setdefault(resource_key, {
            "resourceId": row.get("resourceId") or "",
            "resourceType": row.get("resourceType") or "",
            "resourceGroup": row.get("resourceGroup") or "",
            "subscriptionId": row.get("subscriptionId") or "",
            "policies": {},
        })["policies"][policy_label] = _build_policy_entry(row)

        policy_key = policy_label
        if row.get("policyDefinitionName") and row.get("policyDefinitionName") != policy_label:
            policy_key = f"{policy_label} -> {row.get('policyDefinitionName')}"
        by_policy.setdefault(policy_key, {
            "policyAssignmentId": row.get("policyAssignmentId") or "",
            "policyDefinitionId": row.get("policyDefinitionId") or "",
            "policyDefinitionReferenceId": row.get("policyDefinitionReferenceId") or "",
            "resources": {},
        })["resources"][resource_key] = _build_policy_entry(row)

    sorted_by_resource = {key: by_resource[key] for key in sorted(by_resource)}
    sorted_by_policy = {key: by_policy[key] for key in sorted(by_policy)}

    data = {
        "byResource": sorted_by_resource,
        "byPolicy": sorted_by_policy,
    }

    today = datetime.date.today().isoformat()
    header_lines = [
        "# Azure Policy Compliance Export",
        f"# App: {cfg.app}",
        f"# Generated: {today}",
        "# Groupings: byResource, byPolicy",
        "",
    ]

    buf: list = []
    _yaml_node(data, 0, buf)

    out_path = cfg.out("policy.yaml")
    out_path.write_text("\n".join(header_lines) + "\n".join(buf) + "\n", encoding="utf-8")
    log.info("Wrote policy YAML (%d rows) to %s", len(policy_rows), out_path)
    return out_path


# ---------------------------------------------------------------------------
# YAML export — minimal serializer (no external dependencies)
# ---------------------------------------------------------------------------

def _yaml_scalar(value: Any, indent: int) -> str:
    """Render a scalar value as a YAML-safe string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # Quote strings that could be misinterpreted by YAML parsers:
    #   - contain special leading characters
    #   - contain colons followed by space (key: value ambiguity)
    #   - look like booleans / null / numbers after conversion
    #   - contain newlines
    needs_quote = (
        not s
        or s[0] in ("#", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "'", '"', "{", "}", "[", "]")
        or ": " in s
        or s.endswith(":")
        or "\n" in s
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off")
    )
    if needs_quote:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def _yaml_node(value: Any, indent: int, buf: list) -> None:
    """Recursively render a value into buf lines."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            buf.append("{}")
            return
        for k, v in value.items():
            key_str = _yaml_scalar(str(k), indent)
            if isinstance(v, (dict, list)):
                if isinstance(v, dict) and not v:
                    buf.append(f"{pad}{key_str}: {{}}")
                elif isinstance(v, list) and not v:
                    buf.append(f"{pad}{key_str}: []")
                else:
                    buf.append(f"{pad}{key_str}:")
                    _yaml_node(v, indent + 1, buf)
            else:
                buf.append(f"{pad}{key_str}: {_yaml_scalar(v, indent)}")
    elif isinstance(value, list):
        if not value:
            buf.append(f"{pad}[]")
            return
        for item in value:
            if isinstance(item, (dict, list)):
                buf.append(f"{pad}-")
                _yaml_node(item, indent + 1, buf)
            else:
                buf.append(f"{pad}- {_yaml_scalar(item, indent)}")
    else:
        buf.append(f"{pad}{_yaml_scalar(value, indent)}")


def _build_resource_entry(r: Dict) -> Dict:
    """Build an ordered resource dict: core fields first, properties last."""
    entry: Dict[str, Any] = {}
    for field in ("name", "type", "location", "resourceGroup", "subscriptionId"):
        v = r.get(field)
        if v is not None:
            entry[field] = v
    prov = get_in(r, "properties", "provisioningState")
    if prov is not None:
        entry["provisioningState"] = prov
    tags = r.get("tags")
    if tags:
        entry["tags"] = tags
    sku = r.get("sku")
    if sku:
        entry["sku"] = sku
    system_data = r.get("systemData")
    if system_data:
        entry["systemData"] = system_data
    props = r.get("properties")
    if props:
        entry["properties"] = props
    return entry


def generate_yaml(cfg: Config) -> Path:
    """Read inventory.json and write inventory.yaml to outputDir.

    Default grouping (inventoryGroupBy=type): resource_type → resource_name → fields
    RG grouping (inventoryGroupBy=rg):         resource_group → resource_type → resource_name → fields

    The resulting YAML is structured for VS Code section folding:
      Ctrl+Shift+[  →  fold block at cursor
      Ctrl+Shift+]  →  unfold block at cursor
      Ctrl+K Ctrl+0 →  fold all
      Ctrl+K Ctrl+J →  unfold all
    """
    inventory = _load_inventory(cfg)

    # Build grouped structure: top_key -> (type_key ->) name -> entry
    data: Dict[str, Any] = {}
    group_by = cfg.inventoryGroupBy

    for r in inventory:
        rtype = (r.get("type") or "unknown").lower()
        name = r.get("name") or r.get("id", "unknown")
        entry = _build_resource_entry(r)

        if group_by == "rg":
            rg = (r.get("resourceGroup") or "unknown").lower()
            data.setdefault(rg, {}).setdefault(rtype, {})[name] = entry
        else:
            data.setdefault(rtype, {})[name] = entry

    # Sort top-level and second-level keys; resource names within each group
    def _sort_group(g: Dict) -> Dict:
        return {k: g[k] for k in sorted(g)}

    if group_by == "rg":
        sorted_data = {
            rg: {rtype: _sort_group(names) for rtype, names in _sort_group(types).items()}
            for rg, types in _sort_group(data).items()
        }
    else:
        sorted_data = {
            rtype: _sort_group(names)
            for rtype, names in _sort_group(data).items()
        }

    # Render
    today = datetime.date.today().isoformat()
    header_lines = [
        f"# Azure Resource Inventory",
        f"# App: {cfg.app}",
        f"# Generated: {today}",
        f"# Group: {group_by}",
        f"# VS Code folding: Ctrl+K Ctrl+0 (fold all) / Ctrl+K Ctrl+J (unfold all)",
        "",
    ]

    buf: list = []
    _yaml_node(sorted_data, 0, buf)

    out_path = cfg.out("inventory.yaml")
    out_path.write_text("\n".join(header_lines) + "\n".join(buf) + "\n", encoding="utf-8")
    log.info("Wrote inventory YAML (%d resources, group=%s) to %s", len(inventory), group_by, out_path)
    return out_path


def _slug(value: str) -> str:
    lowered = str(value or '').lower()
    chars = [ch if ch.isalnum() else '-' for ch in lowered]
    slug = ''.join(chars).strip('-')
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug or 'unknown'


def _flatten_resource_for_csv(resource: Dict[str, Any]) -> Dict[str, Any]:
    props = resource.get('properties') or {}
    system_data = resource.get('systemData') or {}
    sku = resource.get('sku') or {}
    return {
        'Name': resource.get('name', ''),
        'Id': resource.get('id', ''),
        'Type': resource.get('type', ''),
        'Location': resource.get('location', ''),
        'ResourceGroup': resource.get('resourceGroup', ''),
        'SubscriptionId': resource.get('subscriptionId', ''),
        'ProvisioningState': props.get('provisioningState', ''),
        'Kind': resource.get('kind', ''),
        'SkuName': sku.get('name', ''),
        'SkuTier': sku.get('tier', ''),
        'ManagedBy': resource.get('managedBy', ''),
        'CreatedAt': system_data.get('createdAt', ''),
        'CreatedBy': system_data.get('createdBy', ''),
        'Tags': _format_tags(resource.get('tags')),
    }


def generate_inventory_by_type_csv(cfg: Config) -> Path:
    inventory = _load_inventory(cfg)
    root = cfg.out('inventory_by_type')
    root.mkdir(parents=True, exist_ok=True)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for resource in inventory:
        key = str(resource.get('type') or 'unknown').lower()
        grouped.setdefault(key, []).append(resource)

    fieldnames = [
        'Name', 'Id', 'Type', 'Location', 'ResourceGroup', 'SubscriptionId', 'ProvisioningState',
        'Kind', 'SkuName', 'SkuTier', 'ManagedBy', 'CreatedAt', 'CreatedBy', 'Tags',
    ]
    manifest: Dict[str, Any] = {'exports': []}
    for resource_type, rows in sorted(grouped.items()):
        filename = f"{_slug(resource_type)}.csv"
        path = root / filename
        flattened = sorted((_flatten_resource_for_csv(row) for row in rows), key=lambda row: (row['SubscriptionId'], row['ResourceGroup'], row['Name']))
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flattened)
        manifest['exports'].append({'type': resource_type, 'count': len(flattened), 'path': f"inventory_by_type/{filename}"})

    manifest_path = root / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    log.info('Wrote %d per-type inventory CSV exports to %s', len(grouped), root)
    return manifest_path
