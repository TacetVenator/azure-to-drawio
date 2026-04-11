"""Optional advisory, quota, and VM-detail exports."""
from __future__ import annotations

import csv
import json
import logging
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from .arg import resolve_subscriptions
from .config import Config
from .util import load_json_file, normalize_id, parse_json_text

log = logging.getLogger(__name__)


def _run_az_json(args: List[str]) -> Any:
    cmd = ["az"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"az command failed (rc={result.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    if not result.stdout.strip():
        return []
    return parse_json_text(
        result.stdout,
        source=" ".join(cmd),
        context="Azure CLI JSON output",
        advice="Verify Azure CLI permissions and whether the requested command is supported in this environment.",
    )


def _load_inventory(cfg: Config) -> List[Dict[str, Any]]:
    path = cfg.out("inventory.json")
    if not path.exists():
        raise FileNotFoundError(f"inventory.json not found at {path}. Run 'expand' (or 'run') first.")
    return load_json_file(
        path,
        context="Insights inventory artifact",
        expected_type=list,
        advice="Fix inventory.json or rerun the expand stage.",
    )


def _effective_subscriptions(cfg: Config) -> List[str]:
    return resolve_subscriptions(cfg.subscriptions, cfg.seedManagementGroups)


def _write_lines(path: Path, lines: Iterable[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_advisor(cfg: Config) -> Path | None:
    if not cfg.includeAdvisor:
        log.info("Advisor collection disabled in config.")
        return None

    inventory = _load_inventory(cfg)
    resource_ids = {normalize_id(item.get("id") or "") for item in inventory if item.get("id")}
    rows: List[Dict[str, Any]] = []
    for subscription in _effective_subscriptions(cfg):
        data = _run_az_json(["advisor", "recommendation", "list", "--subscription", subscription, "--output", "json"])
        for row in data if isinstance(data, list) else []:
            impacted = normalize_id(
                row.get("resourceMetadata", {}).get("resourceId")
                or row.get("resourceMetadata", {}).get("resourceUri")
                or row.get("impactedValue")
                or row.get("id")
                or ""
            )
            if impacted and impacted in resource_ids:
                rows.append(row)

    rows.sort(key=lambda row: (
        str(row.get("category") or "").lower(),
        str(row.get("impact") or "").lower(),
        normalize_id(row.get("resourceMetadata", {}).get("resourceId") or row.get("resourceMetadata", {}).get("resourceUri") or row.get("impactedValue") or ""),
        str(row.get("shortDescription", {}).get("problem") or row.get("name") or "").lower(),
    ))
    cfg.ensure_output_dir()
    json_path = cfg.out("advisor.json")
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True))

    category_counts = Counter(str(row.get("category") or "Unknown") for row in rows)
    impact_counts = Counter(str(row.get("impact") or "Unknown") for row in rows)
    lines = [
        f"# Advisor Summary - {cfg.app}",
        "",
        f"- Recommendations in discovered scope: {len(rows)}",
        f"- Categories: {len(category_counts)}",
        f"- Impact levels: {len(impact_counts)}",
        "",
        "## By Category",
        "",
    ]
    if category_counts:
        for category, count in sorted(category_counts.items()):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- No Azure Advisor recommendations matched the discovered inventory.")
    lines += ["", "## Top Findings", ""]
    for row in rows[:20]:
        metadata = row.get("resourceMetadata") or {}
        problem = (row.get("shortDescription") or {}).get("problem") or row.get("name") or "Unnamed recommendation"
        lines.append(
            f"- [{row.get('category', 'Unknown')}/{row.get('impact', 'Unknown')}] {problem} :: {metadata.get('resourceId') or metadata.get('resourceUri') or row.get('impactedValue') or 'unknown target'}"
        )
    if not rows:
        lines.append("- None")
    _write_lines(cfg.out("advisor_summary.md"), lines)
    log.info("Wrote advisor.json and advisor_summary.md with %d recommendations", len(rows))
    return json_path


def _collect_locations(inventory: List[Dict[str, Any]]) -> Dict[str, Set[str]]:
    by_sub: Dict[str, Set[str]] = defaultdict(set)
    for item in inventory:
        sub = str(item.get("subscriptionId") or "").strip()
        loc = str(item.get("location") or "").strip()
        if sub and loc:
            by_sub[sub].add(loc)
    return by_sub


def run_quota(cfg: Config) -> Path | None:
    if not cfg.includeQuota:
        log.info("Quota collection disabled in config.")
        return None

    inventory = _load_inventory(cfg)
    locations_by_sub = _collect_locations(inventory)
    rows: List[Dict[str, Any]] = []
    for subscription in _effective_subscriptions(cfg):
        for location in sorted(locations_by_sub.get(subscription, [])):
            for service, command in (
                ("compute", ["vm", "list-usage", "--location", location, "--subscription", subscription, "--output", "json"]),
                ("network", ["network", "list-usages", "--location", location, "--subscription", subscription, "--output", "json"]),
            ):
                try:
                    data = _run_az_json(command)
                except RuntimeError as exc:
                    log.warning("Skipping %s quota for %s/%s: %s", service, subscription, location, exc)
                    continue
                for row in data if isinstance(data, list) else []:
                    rows.append({
                        "subscriptionId": subscription,
                        "location": location,
                        "service": service,
                        "name": (row.get("name") or {}).get("localizedValue") or (row.get("name") or {}).get("value") or row.get("name") or "unknown",
                        "currentValue": row.get("currentValue"),
                        "limit": row.get("limit"),
                        "unit": row.get("unit") or "count",
                    })
    rows.sort(key=lambda row: (row["subscriptionId"], row["location"], row["service"], str(row["name"]).lower()))
    cfg.ensure_output_dir()
    json_path = cfg.out("quota.json")
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True))

    lines = [
        f"# Quota Summary - {cfg.app}",
        "",
        f"- Quota rows collected: {len(rows)}",
        f"- Subscription/region pairs: {len({(row['subscriptionId'], row['location']) for row in rows})}",
        "",
        "## Near Limits (>= 80%)",
        "",
    ]
    near_limit = []
    for row in rows:
        limit = row.get("limit")
        current = row.get("currentValue")
        if isinstance(limit, (int, float)) and isinstance(current, (int, float)) and limit > 0 and current / limit >= 0.8:
            near_limit.append(row)
    for row in near_limit[:40]:
        lines.append(
            f"- {row['subscriptionId']} / {row['location']} / {row['service']} / {row['name']}: {row['currentValue']} of {row['limit']} {row['unit']}"
        )
    if not near_limit:
        lines.append("- No quota rows met the >= 80% threshold.")
    _write_lines(cfg.out("quota_summary.md"), lines)
    log.info("Wrote quota.json and quota_summary.md with %d rows", len(rows))
    return json_path


_VM_DETAIL_FIELDS = [
    "Name", "ResourceId", "SubscriptionId", "ResourceGroup", "Location", "VmSize", "VmGeneration",
    "OsType", "PowerState", "AvailabilityZone", "NicCount", "DataDiskCount", "OsDiskSku", "ImageReference",
]


def generate_vm_details_csv(cfg: Config) -> Path | None:
    if not cfg.includeVmDetails:
        log.info("VM details export disabled in config.")
        return None

    inventory = _load_inventory(cfg)
    rows: List[Dict[str, Any]] = []
    for item in inventory:
        if normalize_id(item.get("type") or "") != "microsoft.compute/virtualmachines":
            continue
        props = item.get("properties") or {}
        hardware = props.get("hardwareProfile") or {}
        storage = props.get("storageProfile") or {}
        image = storage.get("imageReference") or {}
        nic_refs = (props.get("networkProfile") or {}).get("networkInterfaces") or []
        data_disks = storage.get("dataDisks") or []
        zones = item.get("zones") or props.get("zones") or []
        image_ref = "/".join(str(image.get(key) or "") for key in ("publisher", "offer", "sku", "version") if image.get(key))
        rows.append({
            "Name": item.get("name", ""),
            "ResourceId": item.get("id", ""),
            "SubscriptionId": item.get("subscriptionId", ""),
            "ResourceGroup": item.get("resourceGroup", ""),
            "Location": item.get("location", ""),
            "VmSize": hardware.get("vmSize", ""),
            "VmGeneration": str((props.get("additionalCapabilities") or {}).get("hibernationEnabled") or ""),
            "OsType": (storage.get("osDisk") or {}).get("osType", ""),
            "PowerState": props.get("extended", {}).get("instanceView", {}).get("powerState", {}).get("code", ""),
            "AvailabilityZone": ",".join(str(zone) for zone in zones),
            "NicCount": len(nic_refs),
            "DataDiskCount": len(data_disks),
            "OsDiskSku": ((storage.get("osDisk") or {}).get("managedDisk") or {}).get("storageAccountType", ""),
            "ImageReference": image_ref,
        })
    rows.sort(key=lambda row: (row["SubscriptionId"], row["ResourceGroup"], row["Name"]))
    path = cfg.out("vm_details.csv")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_VM_DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote vm_details.csv with %d VM rows", len(rows))
    return path
