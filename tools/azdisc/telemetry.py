"""Telemetry enrichment: App Insights, Activity Log, and NSG Flow Log phases."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .arg import query as arg_query, resolve_subscriptions
from .config import Config
from .util import load_json_file, normalize_id, parse_json_text

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# Mapping of hostname suffix → used only for logging; actual resolution is by
# name lookup, so no type discrimination is required here.
_HOSTNAME_SUFFIXES = [
    ".blob.core.windows.net",
    ".queue.core.windows.net",
    ".table.core.windows.net",
    ".file.core.windows.net",
    ".dfs.core.windows.net",
    ".database.windows.net",
    ".servicebus.windows.net",
    ".azurewebsites.net",
    ".vault.azure.net",
    ".documents.azure.com",
    ".search.windows.net",
    ".cognitiveservices.azure.com",
    ".azurecr.io",
    ".redis.cache.windows.net",
    ".azurehdinsight.net",
    ".eventgrid.azure.net",
    ".mysql.database.azure.com",
    ".postgres.database.azure.com",
]

_LA_WORKSPACE_CACHE: Dict[str, str] = {}


def _looks_like_uuid(s: str) -> bool:
    """Return True if s looks like an Azure object ID (UUID format)."""
    return bool(_UUID_RE.match(s.strip()))


def _resolve_hostname(hostname: str, node_by_name: Dict[str, str]) -> Optional[str]:
    """Try to resolve an Azure service hostname to an ARM resource ID.

    Strips well-known Azure service suffixes to extract a resource name, then
    looks up the name in the provided node_by_name mapping. Returns the ARM
    resource ID if found, or None if unresolvable.
    """
    hostname = hostname.lower().strip()
    # Strip port if present (e.g. "myacct.blob.core.windows.net:443")
    hostname = hostname.split(":")[0]

    for suffix in _HOSTNAME_SUFFIXES:
        if hostname.endswith(suffix):
            name = hostname[: -len(suffix)]
            # Names with dots indicate a path component, not a direct name
            if "." not in name and name:
                resource_id = node_by_name.get(name)
                if resource_id:
                    log.debug(
                        "Resolved hostname %r -> %s (via suffix %s)", hostname, resource_id, suffix
                    )
                    return resource_id
            break

    log.debug("Could not resolve hostname %r to a known ARM resource", hostname)
    return None


def _collect_nic_ips(nodes: List[Dict]) -> Dict[str, str]:
    """Build privateIPAddress -> node_id map from NIC nodes."""
    ip_map: Dict[str, str] = {}
    for node in nodes:
        if node.get("type", "").lower() != "microsoft.network/networkinterfaces":
            continue
        props = node.get("properties") or {}
        ip_configs = props.get("ipConfigurations") or []
        for ipc in ip_configs:
            ipc_props = ipc.get("properties") or {}
            ip = ipc_props.get("privateIPAddress")
            if ip:
                ip_map[ip] = normalize_id(node["id"])
    return ip_map


def _resolve_la_workspace_identifier(workspace_ref: str) -> str:
    """Resolve a workspace ARM ID to a Log Analytics customer ID for querying."""
    workspace_ref = workspace_ref.strip()
    if not workspace_ref:
        return workspace_ref
    if not workspace_ref.lower().startswith("/subscriptions/"):
        return workspace_ref

    cached = _LA_WORKSPACE_CACHE.get(workspace_ref)
    if cached:
        return cached

    cmd = [
        "az", "monitor", "log-analytics", "workspace", "show",
        "--ids", workspace_ref,
        "--output", "json",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.warning(
                "Failed to resolve Log Analytics workspace %s to a customer ID; telemetry query will use the raw reference. stderr: %s",
                workspace_ref,
                result.stderr.strip() or "<empty>",
            )
            return workspace_ref
        raw = parse_json_text(
            result.stdout,
            source=' '.join(cmd),
            context='Log Analytics workspace metadata',
            expected_type=dict,
            advice='Check Azure CLI output and verify the workspace ID is valid.',
        )
    except RuntimeError as exc:
        log.warning(
            "Failed to parse workspace metadata while resolving %s: %s. Telemetry query will use the raw reference.",
            workspace_ref,
            exc,
        )
        return workspace_ref
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Unexpected error resolving Log Analytics workspace %s: %s. Telemetry query will use the raw reference.",
            workspace_ref,
            exc,
        )
        return workspace_ref

    customer_id = (raw.get("customerId") or ((raw.get("properties") or {}).get("customerId") or "")).strip()
    if customer_id:
        _LA_WORKSPACE_CACHE[workspace_ref] = customer_id
        return customer_id

    log.warning(
        "Workspace metadata for %s did not include customerId. Telemetry query will use the raw reference.",
        workspace_ref,
    )
    return workspace_ref


def _is_missing_la_table_error(stderr: str) -> bool:
    """Return True when LA query stderr indicates the referenced table is absent."""
    if not stderr:
        return False
    stderr_lower = stderr.lower()
    return (
        "semanticerror" in stderr_lower
        and "failed to resolve table or column expression named" in stderr_lower
    )


def _run_la_query(workspace_id: str, kql: str, subscriptions: List[str]) -> List[Dict]:
    """Run a Log Analytics query via az CLI. Returns list of row dicts or [] on failure."""
    query_workspace = _resolve_la_workspace_identifier(workspace_id)
    cmd = [
        "az", "monitor", "log-analytics", "query",
        "--workspace", query_workspace,
        "--analytics-query", kql,
        "--output", "json",
    ]
    log.debug("Running LA query on workspace %s (query target %s)", workspace_id, query_workspace)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip() or "<empty>"
            if _is_missing_la_table_error(result.stderr):
                log.info(
                    "Log Analytics workspace %s (query target %s) does not contain the requested table; skipping query. stderr: %s",
                    workspace_id,
                    query_workspace,
                    stderr,
                )
                return []
            log.warning(
                "Log Analytics query failed for workspace %s (query target %s). stderr: %s. Troubleshooting: verify the workspace exists, resolve its customerId, and check Azure CLI access with `az monitor log-analytics workspace show --ids <workspace-arm-id>`.",
                workspace_id,
                query_workspace,
                stderr,
            )
            return []
        raw = parse_json_text(
            result.stdout,
            source=' '.join(cmd),
            context='Log Analytics query JSON output',
            advice='Check Azure CLI output, workspace access, and the KQL query.',
        )
    except RuntimeError as exc:
        log.warning(
            "Failed to parse LA query output as JSON for workspace %s (query target %s): %s",
            workspace_id,
            query_workspace,
            exc,
        )
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Unexpected error running LA query for workspace %s (query target %s): %s",
            workspace_id,
            query_workspace,
            exc,
        )
        return []

    # Support both direct list output and {"tables": [...]} envelope
    if isinstance(raw, list):
        return raw

    tables = raw.get("tables")
    if not isinstance(tables, list) or not tables:
        log.warning("Unexpected LA query response structure from workspace %s", workspace_id)
        return []

    rows_out: List[Dict] = []
    for table in tables:
        columns = [c["name"] for c in table.get("columns", [])]
        for row in table.get("rows", []):
            if len(row) == len(columns):
                rows_out.append(dict(zip(columns, row)))
            else:
                log.warning("LA row length mismatch: expected %d cols, got %d", len(columns), len(row))
    return rows_out


# ---------------------------------------------------------------------------
# Phase 1: App Insights dependencies
# ---------------------------------------------------------------------------

_KQL_APP_DEPS_MODERN = """\
AppDependencies
| where TimeGenerated > ago({days}d)
| where isnotempty(Target)
| summarize CallCount=count() by Target, DependencyType
| order by CallCount desc"""

_KQL_APP_DEPS_CLASSIC = """\
dependencies
| where timestamp > ago({days}d)
| where isnotempty(target)
| summarize count() by target, type
| project Target=target, DependencyType=type"""


def _phase_app_insights(cfg: Config, nodes: List[Dict]) -> List[Dict]:
    """Phase 1: Emit appInsights->dependency edges from App Insights telemetry."""
    ai_nodes = [n for n in nodes if n.get("type", "").lower() == "microsoft.insights/components"]
    if not ai_nodes:
        log.info("No App Insights components in scope, skipping Phase 1")
        return []

    log.info("Found %d App Insights component(s), querying dependencies", len(ai_nodes))

    node_by_name: Dict[str, str] = {
        n["name"].lower(): normalize_id(n["id"]) for n in nodes if "name" in n and "id" in n
    }

    new_edges: List[Dict] = []

    for ai_node in ai_nodes:
        ai_id = normalize_id(ai_node["id"])
        props = ai_node.get("properties") or {}
        workspace_id = props.get("WorkspaceResourceId")
        if not workspace_id:
            log.debug("App Insights %s has no WorkspaceResourceId, skipping", ai_id)
            continue

        # Try modern table first, fall back to classic
        rows: List[Dict] = []
        kql_modern = _KQL_APP_DEPS_MODERN.format(days=cfg.telemetryLookbackDays)
        rows = _run_la_query(workspace_id, kql_modern, cfg.subscriptions)
        if not rows:
            log.debug("Modern AppDependencies table returned no rows for %s, trying classic", ai_id)
            kql_classic = _KQL_APP_DEPS_CLASSIC.format(days=cfg.telemetryLookbackDays)
            rows = _run_la_query(workspace_id, kql_classic, cfg.subscriptions)

        log.debug("App Insights %s: got %d dependency rows", ai_id, len(rows))

        resolved = 0
        for row in rows:
            target_host = row.get("Target") or ""
            if not target_host:
                continue
            target_id = _resolve_hostname(target_host, node_by_name)
            if target_id is None:
                # Keep as external dependency with synthetic ID
                target_id = f"external/{target_host}"
            edge = {"source": ai_id, "target": target_id, "kind": "appInsights->dependency"}
            new_edges.append(edge)
            resolved += 1

        log.info(
            "App Insights %s: resolved %d dependency edge(s) from %d rows",
            ai_id,
            resolved,
            len(rows),
        )

    return new_edges


# ---------------------------------------------------------------------------
# Phase 2: Activity Log enrichment
# ---------------------------------------------------------------------------


def _phase_activity_log(cfg: Config, nodes: List[Dict]) -> List[Dict]:
    """Phase 2: Emit activityLog->access edges from Activity Log events."""
    # Collect managed identity principal IDs
    principal_to_node: Dict[str, str] = {}
    for node in nodes:
        if node.get("type", "").lower() == "microsoft.managedidentity/userassignedidentities":
            props = node.get("properties") or {}
            pid = props.get("principalId")
            if pid:
                principal_to_node[pid.lower()] = normalize_id(node["id"])

    if not principal_to_node:
        log.info("No managed identities in scope, skipping Phase 2")
        return []

    log.info(
        "Found %d managed identity principal(s), querying activity logs",
        len(principal_to_node),
    )

    # Build set of seed RG names (lowercase) for cross-RG detection
    seed_rgs = {rg.lower() for rg in cfg.seedResourceGroups}

    # Build set of resource IDs from inventory
    inventory_ids = {normalize_id(n["id"]) for n in nodes if "id" in n}

    start_iso = (
        datetime.now(timezone.utc) - timedelta(days=cfg.telemetryLookbackDays)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_edges: List[Dict] = []
    seen_edges: set = set()

    def _add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if key not in seen_edges:
            seen_edges.add(key)
            new_edges.append({"source": source, "target": target, "kind": kind})

    for rg in cfg.seedResourceGroups:
        cmd = [
            "az", "monitor", "activity-log", "list",
            "--resource-group", rg,
            "--start-time", start_iso,
            "--max-events", "5000",
            "--output", "json",
        ]
        log.debug("Querying activity log for RG %s", rg)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                log.warning(
                    "Activity log query failed for RG %s: %s", rg, result.stderr.strip()
                )
                continue
            events = parse_json_text(
                result.stdout,
                source=' '.join(cmd),
                context=f'Activity log JSON output for RG {rg}',
                expected_type=list,
                advice='Check Azure CLI output and verify access to monitor activity logs.',
            )
        except RuntimeError as exc:
            log.warning("Failed to parse activity log JSON for RG %s: %s", rg, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            log.warning("Unexpected error querying activity log for RG %s: %s", rg, exc)
            continue

        log.debug("RG %s: got %d activity log events", rg, len(events))

        for event in events:
            try:
                caller = (event.get("caller") or "").strip()
                resource_id_raw = event.get("resourceId") or ""
                status = (
                    (event.get("status") or {}).get("value") or ""
                ).lower()
                if not caller or not resource_id_raw:
                    continue

                resource_id = normalize_id(resource_id_raw)
                caller_lower = caller.lower()

                # Determine whether the accessed resource is outside seed RGs
                # ARM ID pattern: /subscriptions/.../resourcegroups/<rg>/...
                rg_match = re.search(r'/resourcegroups/([^/]+)/', resource_id, re.IGNORECASE)
                resource_rg = rg_match.group(1).lower() if rg_match else ""

                resource_outside_seed = resource_rg not in seed_rgs

                # Outbound: known MI principal accessed something outside seed RGs
                if caller_lower in principal_to_node and resource_outside_seed and status == "succeeded":
                    mi_node_id = principal_to_node[caller_lower]
                    _add_edge(mi_node_id, resource_id, "activityLog->access")

                # Inbound: resource in seed-RG accessed by an external service principal
                elif (
                    resource_id in inventory_ids
                    and not resource_outside_seed
                    and _looks_like_uuid(caller)
                    and caller_lower not in principal_to_node
                ):
                    log.debug(
                        "Inbound call to %s from external SP %s (cannot resolve without AD query)",
                        resource_id,
                        caller,
                    )

            except Exception as exc:  # noqa: BLE001
                log.warning("Error processing activity log event: %s", exc)
                continue

    log.info("Phase 2: generated %d activityLog->access edge(s)", len(new_edges))
    return new_edges


# ---------------------------------------------------------------------------
# Phase 3: NSG Flow Logs / Traffic Analytics
# ---------------------------------------------------------------------------

_KQL_FLOW = """\
AzureNetworkAnalytics_CL
| where TimeGenerated > ago({days}d)
| where isnotempty(SrcIP_s) and isnotempty(DestIP_s)
| where FlowStatus_s =~ "A"
| summarize FlowCount=sum(toint(AllowedInFlows_d) + toint(AllowedOutFlows_d))
    by SrcIP_s, DestIP_s, L7Protocol_s, DestPort_d
| order by FlowCount desc
| limit 500"""


def _phase_flow_logs(cfg: Config, nodes: List[Dict]) -> List[Dict]:
    """Phase 3: Emit flowLog->flow edges from Traffic Analytics workspaces."""
    # Query ARG for flow log resources
    from .arg import query as arg_query  # local import to avoid circular

    try:
        flow_log_kql = (
            "resources"
            " | where type =~ 'microsoft.network/networkwatchers/flowlogs'"
            " | project id, name, properties"
        )
        flow_logs = arg_query(flow_log_kql, cfg.subscriptions, cfg.seedManagementGroups)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to query ARG for flow logs: %s", exc)
        return []

    if not flow_logs:
        log.info("No NSG flow log resources found, skipping Phase 3")
        return []

    log.info("Found %d flow log resource(s), checking Traffic Analytics", len(flow_logs))

    # Collect workspaces with Traffic Analytics enabled
    ta_workspaces: List[str] = []
    for fl in flow_logs:
        try:
            props = fl.get("properties") or {}
            fac = props.get("flowAnalyticsConfiguration") or {}
            nwfac = fac.get("networkWatcherFlowAnalyticsConfiguration") or {}
            if nwfac.get("enabled") is True:
                ws_id = nwfac.get("workspaceResourceId")
                if ws_id and ws_id not in ta_workspaces:
                    ta_workspaces.append(ws_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Error reading flow log properties: %s", exc)

    if not ta_workspaces:
        log.info("No Traffic Analytics workspaces configured, skipping Phase 3")
        return []

    log.info("Querying %d Traffic Analytics workspace(s)", len(ta_workspaces))

    # Build IP-to-NIC mapping from inventory
    ip_to_nic = _collect_nic_ips(nodes)
    if not ip_to_nic:
        log.info("No NIC IP addresses in inventory, Phase 3 flows will not resolve")

    kql = _KQL_FLOW.format(days=cfg.telemetryLookbackDays)
    new_edges: List[Dict] = []
    seen_edges: set = set()

    for ws_id in ta_workspaces:
        rows = _run_la_query(ws_id, kql, cfg.subscriptions)
        log.debug("Workspace %s: got %d flow rows", ws_id, len(rows))

        for row in rows:
            src_ip = row.get("SrcIP_s") or ""
            dst_ip = row.get("DestIP_s") or ""
            if not src_ip or not dst_ip:
                continue

            src_nic = ip_to_nic.get(src_ip)
            dst_nic = ip_to_nic.get(dst_ip)

            if src_nic and dst_nic:
                key = (src_nic, dst_nic, "flowLog->flow")
                if key not in seen_edges:
                    seen_edges.add(key)
                    new_edges.append({"source": src_nic, "target": dst_nic, "kind": "flowLog->flow"})
            else:
                log.debug(
                    "Flow %s -> %s: could not resolve one or both IPs to NICs", src_ip, dst_ip
                )

    log.info("Phase 3: generated %d flowLog->flow edge(s)", len(new_edges))
    return new_edges


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_telemetry_enrichment(cfg: Config) -> None:
    """Run all telemetry enrichments and merge new edges into graph.json."""
    graph_path = Path(cfg.outputDir) / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"graph.json not found at {graph_path}")

    graph = load_json_file(
        graph_path,
        context='Telemetry stage graph artifact',
        expected_type=dict,
        advice='Fix graph.json or rerun the graph stage before telemetry enrichment.',
    )
    nodes: List[Dict] = graph.get("nodes", [])
    existing_edges: List[Dict] = graph.get("edges", [])

    log.info(
        "Telemetry enrichment starting: %d nodes, %d existing edges",
        len(nodes),
        len(existing_edges),
    )

    # Run phases individually; each is resilient to failure
    ai_edges: List[Dict] = []
    al_edges: List[Dict] = []
    fl_edges: List[Dict] = []

    try:
        ai_edges = _phase_app_insights(cfg, nodes)
    except Exception as exc:  # noqa: BLE001
        log.warning("Phase 1 (App Insights) failed: %s", exc)

    try:
        al_edges = _phase_activity_log(cfg, nodes)
    except Exception as exc:  # noqa: BLE001
        log.warning("Phase 2 (Activity Log) failed: %s", exc)

    try:
        fl_edges = _phase_flow_logs(cfg, nodes)
    except Exception as exc:  # noqa: BLE001
        log.warning("Phase 3 (Flow Logs) failed: %s", exc)

    all_new_edges = ai_edges + al_edges + fl_edges

    # Deduplicate new edges
    seen: set = set()
    deduped: List[Dict] = []
    for edge in all_new_edges:
        key = (edge["source"], edge["target"], edge["kind"])
        if key not in seen:
            seen.add(key)
            deduped.append(edge)

    # Merge into existing edges (avoid duplicating existing)
    existing_keys: set = {
        (e["source"], e["target"], e["kind"]) for e in existing_edges
    }
    truly_new = [e for e in deduped if (e["source"], e["target"], e["kind"]) not in existing_keys]

    graph["edges"] = existing_edges + truly_new
    graph["telemetryEdges"] = truly_new

    graph_path.write_text(json.dumps(graph, indent=2))

    log.info(
        "Telemetry enrichment: +%d edges (%d appInsights, %d activityLog, %d flowLog)",
        len(truly_new),
        len(ai_edges),
        len(al_edges),
        len(fl_edges),
    )
