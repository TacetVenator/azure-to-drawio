"""Wrapper around `az graph query` for Azure Resource Graph."""
from __future__ import annotations

import logging
import subprocess
import ipaddress
from typing import Any, Dict, List

from .util import parse_json_text

log = logging.getLogger(__name__)

_BATCH_SIZE = 200
_MAX_ARG_ROWS = 1000


def _run_az(args: List[str]) -> Dict[str, Any]:
    cmd = ["az"] + args
    log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"az command failed (rc={result.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    if not result.stdout.strip():
        raise RuntimeError(
            f"Azure CLI returned empty stdout for: {' '.join(cmd)}. "
            f"stderr: {result.stderr.strip() or '<empty>'}"
        )
    return parse_json_text(
        result.stdout,
        source=' '.join(cmd),
        context='Azure CLI JSON output',
        expected_type=dict,
        advice='Re-run the command with --verbose or check whether az emitted warnings or non-JSON output to stdout.',
    )


def query(kusto: str, subscriptions: List[str]) -> List[Dict[str, Any]]:
    """Run a Kusto query against ARG and return all rows (handles paging)."""
    results = []
    skip = 0
    all_rows: List[Dict[str, Any]] = []
    # Query all subscriptions at once (ARG supports multi-sub)
    sub_args = []
    for s in subscriptions:
        sub_args += ["--subscriptions", s]
    while True:
        data = _run_az(
            ["graph", "query", "--graph-query", kusto,
             "--first", str(_MAX_ARG_ROWS),
             "--skip", str(skip)]
            + sub_args
        )
        rows = data.get("data", [])
        all_rows.extend(rows)
        log.debug("ARG page skip=%d got %d rows (total so far: %d)", skip, len(rows), len(all_rows))
        if len(rows) < _MAX_ARG_ROWS:
            break
        skip += _MAX_ARG_ROWS
    return all_rows


def query_by_ids(ids: List[str], subscriptions: List[str]) -> List[Dict[str, Any]]:
    """Fetch resources by a list of ARM IDs (batched)."""
    all_results: List[Dict[str, Any]] = []
    for i in range(0, len(ids), _BATCH_SIZE):
        batch = ids[i: i + _BATCH_SIZE]
        # Group batch by subscription
        batch_by_sub = {}
        for rid in batch:
            # Extract subscription from ARM ID
            parts = rid.split("/")
            if "subscriptions" in parts:
                sub_idx = parts.index("subscriptions") + 1
                sub_id = parts[sub_idx]
                batch_by_sub.setdefault(sub_id, []).append(rid)
            else:
                batch_by_sub.setdefault("default", []).append(rid)
        for sub_id, batch_ids in batch_by_sub.items():
            id_list = ", ".join(f"'{rid}'" for rid in batch_ids)
            kusto = f"resources | where id in~ ({id_list}) | project id, name, type, location, subscriptionId, resourceGroup, tags, sku, kind, systemData, properties"
            # Only query the relevant subscription
            sub_args = ["--subscriptions", sub_id] if sub_id != "default" else []
            data = _run_az(
                ["graph", "query", "--graph-query", kusto,
                 "--first", str(_MAX_ARG_ROWS)]
                + sub_args
            )
            rows = data.get("data", [])
            all_results.extend(rows)
    return all_results


def filter_resources_by_cidr(resources, cidr_blocks):
    """Filter resources whose IPs/subnets are within the given CIDR blocks."""
    networks = [ipaddress.ip_network(cidr) for cidr in cidr_blocks]
    filtered = []
    for r in resources:
        # Example: check subnet property
        subnet = r.get("properties", {}).get("addressPrefix")
        if subnet:
            try:
                net = ipaddress.ip_network(subnet, strict=False)
                if any(net.subnet_of(n) or net.overlaps(n) for n in networks):
                    filtered.append(r)
                else:
                    log.info(f"Excluded {r.get('id')} not in CIDR scope")
            except ValueError:
                log.warning(f"Invalid subnet {subnet} for resource {r.get('id')}")
        else:
            # Optionally handle other IP properties
            filtered.append(r)  # Keep if no subnet info
    return filtered
