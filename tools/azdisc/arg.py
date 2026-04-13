"""Wrapper around Azure Resource Graph queries."""
from __future__ import annotations

import ipaddress
import logging
import subprocess
from typing import Any, Dict, List

from .azcli import run_az_json
from .util import parse_json_text

log = logging.getLogger(__name__)

_BATCH_SIZE = 200
_MAX_ARG_ROWS = 1000
_RESOURCE_PROJECTION = "project id, name, type, location, subscriptionId, resourceGroup, tags, sku, kind, systemData, properties"


def _run_az(args: List[str]) -> Dict[str, Any]:
    """Backward-compatible Azure CLI JSON wrapper."""
    cmd = ["az"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "az command failed (rc=%s):\n  cmd: %s\n  stderr: %s"
            % (result.returncode, " ".join(cmd), result.stderr.strip())
        )
    if not result.stdout.strip():
        raise RuntimeError(
            "Azure CLI returned empty stdout for: %s. stderr: %s"
            % (" ".join(cmd), result.stderr.strip() or "<empty>")
        )
    return parse_json_text(
        result.stdout,
        source=" ".join(cmd),
        context="Azure CLI JSON output",
        expected_type=dict,
        advice="Re-run the command with --verbose or check whether az emitted warnings or non-JSON output to stdout.",
    )


def resolve_subscriptions(subscriptions: List[str], management_groups: List[str] | None = None) -> List[str]:
    effective: List[str] = []
    seen = set()

    def _add(sub_id: str) -> None:
        value = str(sub_id or "").strip()
        if value and value not in seen:
            seen.add(value)
            effective.append(value)

    for sub in subscriptions:
        _add(sub)

    for mg in management_groups or []:
        data = run_az_json(
            [
                "rest",
                "--method", "get",
                "--url", f"https://management.azure.com/providers/Microsoft.Management/managementGroups/{mg}?$expand=children&api-version=2021-04-01",
            ],
            expected_type=dict,
        )
        children = (((data.get("properties") or {}).get("children")) or [])
        pending = list(children)
        while pending:
            child = pending.pop(0)
            child_type = str(child.get("type") or "").lower()
            if child_type.endswith("/subscriptions"):
                name = child.get("name") or ""
                display_name = (((child.get("properties") or {}).get("displayName")) or "")
                sub_id = name.split("/")[-1] if "/" in name else name
                _add(sub_id or display_name)
                continue
            if child_type.endswith("/managementgroups"):
                child_name = child.get("name") or ""
                nested = run_az_json(
                    [
                        "rest",
                        "--method", "get",
                        "--url", f"https://management.azure.com/providers/Microsoft.Management/managementGroups/{child_name}?$expand=children&api-version=2021-04-01",
                    ],
                    expected_type=dict,
                )
                pending.extend((((nested.get("properties") or {}).get("children")) or []))

    if not effective:
        raise ValueError("No subscriptions were resolved from subscriptions/management groups configuration")
    return effective


def query(kusto: str, subscriptions: List[str], management_groups: List[str] | None = None) -> List[Dict[str, Any]]:
    """Run a Kusto query against ARG and return all rows."""
    skip = 0
    all_rows: List[Dict[str, Any]] = []
    sub_args: List[str] = []
    for subscription in resolve_subscriptions(subscriptions, management_groups):
        sub_args += ["--subscriptions", subscription]
    while True:
        data = run_az_json(
            ["graph", "query", "--graph-query", kusto, "--first", str(_MAX_ARG_ROWS), "--skip", str(skip)] + sub_args,
            expected_type=dict,
            advice="Re-run the command with --verbose or check whether az emitted warnings or non-JSON output to stdout.",
        )
        rows = data.get("data", [])
        all_rows.extend(rows)
        log.debug("ARG page skip=%d got %d rows (total so far: %d)", skip, len(rows), len(all_rows))
        if len(rows) < _MAX_ARG_ROWS:
            break
        skip += _MAX_ARG_ROWS
    return all_rows


def query_by_ids(ids: List[str], subscriptions: List[str], management_groups: List[str] | None = None) -> List[Dict[str, Any]]:
    """Fetch resources by a list of ARM IDs in batches."""
    all_results: List[Dict[str, Any]] = []
    effective_subs = resolve_subscriptions(subscriptions, management_groups)
    fallback_sub = effective_subs[0] if effective_subs else ""
    for i in range(0, len(ids), _BATCH_SIZE):
        batch = ids[i:i + _BATCH_SIZE]
        batch_by_sub: Dict[str, List[str]] = {}
        for rid in batch:
            parts = rid.split("/")
            if "subscriptions" in parts:
                sub_idx = parts.index("subscriptions") + 1
                sub_id = parts[sub_idx]
                batch_by_sub.setdefault(sub_id, []).append(rid)
            else:
                batch_by_sub.setdefault("default", []).append(rid)
        for sub_id, batch_ids in batch_by_sub.items():
            id_list = ", ".join("'{}'".format(rid) for rid in batch_ids)
            kusto = f"resources | where id in~ ({id_list}) | {_RESOURCE_PROJECTION}"
            query_sub = sub_id if sub_id != "default" else fallback_sub
            sub_args = ["--subscriptions", query_sub] if query_sub else []
            data = run_az_json(
                ["graph", "query", "--graph-query", kusto, "--first", str(_MAX_ARG_ROWS)] + sub_args,
                expected_type=dict,
                advice="Re-run the command with --verbose or check whether az emitted warnings or non-JSON output to stdout.",
            )
            all_results.extend(data.get("data", []))
    return all_results


def filter_resources_by_cidr(resources, cidr_blocks):
    """Filter resources whose IPs/subnets are within the given CIDR blocks."""
    networks = [ipaddress.ip_network(cidr) for cidr in cidr_blocks]
    filtered = []
    for resource in resources:
        subnet = resource.get("properties", {}).get("addressPrefix")
        if subnet:
            try:
                net = ipaddress.ip_network(subnet, strict=False)
                if any(net.subnet_of(network) or net.overlaps(network) for network in networks):
                    filtered.append(resource)
                else:
                    log.info("Excluded %s not in CIDR scope", resource.get("id"))
            except ValueError:
                log.warning("Invalid subnet %s for resource %s", subnet, resource.get("id"))
        else:
            filtered.append(resource)
    return filtered
