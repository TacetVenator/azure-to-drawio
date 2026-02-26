"""Wrapper around `az graph query` for Azure Resource Graph."""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any, Dict, List

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
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse az output as JSON: {e}\nOutput: {result.stdout[:500]}")


def query(kusto: str, subscriptions: List[str]) -> List[Dict[str, Any]]:
    """Run a Kusto query against ARG and return all rows (handles paging)."""
    sub_args = []
    for s in subscriptions:
        sub_args += ["--subscriptions", s]
    all_rows: List[Dict[str, Any]] = []
    skip = 0
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
        id_list = ", ".join(f"'{rid}'" for rid in batch)
        kusto = f"resources | where id in~ ({id_list}) | project id, name, type, location, subscriptionId, resourceGroup, properties"
        all_results.extend(query(kusto, subscriptions))
    return all_results
