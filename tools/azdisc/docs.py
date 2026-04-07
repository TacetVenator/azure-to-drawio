"""Documentation generators: catalog.md, edges.md, routing.md, migration.md, policy_summary.md, rbac_summary.md."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .config import Config
from .governance import normalize_compliance_state, simplify_rbac_rows, summarize_policy_rows, summarize_resource_access
from .util import load_json_file, normalize_id

log = logging.getLogger(__name__)

_TELEMETRY_EDGE_KINDS = {
    "appInsights->dependency",
    "activityLog->access",
    "flowLog->flow",
}


def generate_docs(cfg: Config) -> None:
    graph_path = cfg.out("graph.json")
    if not graph_path.exists():
        raise FileNotFoundError("graph.json not found. Run 'graph' first.")
    graph = load_json_file(
        graph_path,
        context="Docs stage graph artifact",
        expected_type=dict,
        advice="Fix graph.json or rerun the graph stage.",
    )
    nodes: List[Dict] = graph["nodes"]
    edges: List[Dict] = graph["edges"]

    unresolved: List[str] = []
    unresolved_path = cfg.out("unresolved.json")
    if unresolved_path.exists():
        unresolved = load_json_file(
            unresolved_path,
            context="Docs stage unresolved references",
            expected_type=list,
            advice="Fix unresolved.json or rerun the expand stage.",
        )

    inventory: List[Dict] = []
    inventory_path = cfg.out("inventory.json")
    if inventory_path.exists():
        inventory = load_json_file(
            inventory_path,
            context="Docs stage inventory artifact",
            expected_type=list,
            advice="Fix inventory.json or rerun the expand stage.",
        )

    rbac_rows: List[Dict] = []
    rbac_path = cfg.out("rbac.json")
    if rbac_path.exists():
        rbac_rows = load_json_file(
            rbac_path,
            context="Docs stage RBAC artifact",
            expected_type=list,
            advice="Fix rbac.json or rerun the RBAC stage.",
        )
    policy_rows: List[Dict] = []
    policy_path = cfg.out("policy.json")
    if policy_path.exists():
        policy_rows = load_json_file(
            policy_path,
            context="Docs stage policy artifact",
            expected_type=list,
            advice="Fix policy.json or rerun the policy stage.",
        )

    rbac_present = rbac_path.exists()

    cfg.ensure_output_dir()
    _write_catalog(cfg, nodes)
    _write_edges(cfg, nodes, edges, unresolved)
    _write_routing(cfg, nodes, edges)
    _write_migration(cfg, nodes, edges, unresolved, inventory, rbac_present)
    _write_policy_summary(cfg, nodes, policy_rows, policy_path.exists())
    _write_policy_by_resource(cfg, nodes, policy_rows, policy_path.exists())
    _write_policy_by_policy(cfg, nodes, policy_rows, policy_path.exists())
    _write_rbac_summary(cfg, nodes, rbac_rows, rbac_path.exists())
    log.info("Wrote catalog.md, edges.md, routing.md, migration.md, policy_summary.md, policy_by_resource.md, policy_by_policy.md, rbac_summary.md")


def _write_catalog(cfg: Config, nodes: List[Dict]) -> None:
    # type -> {count, regions, rgs, subs}
    stats: Dict[str, Dict] = {}
    for n in nodes:
        t = n["type"]
        if t not in stats:
            stats[t] = {"count": 0, "regions": set(), "rgs": set(), "subs": set()}
        s = stats[t]
        s["count"] += 1
        if n.get("location"):
            s["regions"].add(n["location"])
        if n.get("resourceGroup"):
            s["rgs"].add(n["resourceGroup"])
        if n.get("subscriptionId"):
            s["subs"].add(n["subscriptionId"])

    lines = [
        f"# Resource Catalog — {cfg.app}\n",
        "| type | count | regions | resource groups | subscriptions |",
        "|------|-------|---------|-----------------|---------------|",
    ]
    for t in sorted(stats.keys()):
        s = stats[t]
        lines.append(
            f"| `{t}` | {s['count']} | {', '.join(sorted(s['regions']))} "
            f"| {', '.join(sorted(s['rgs']))} | {', '.join(sorted(s['subs']))} |"
        )
    cfg.out("catalog.md").write_text("\n".join(lines) + "\n")


def _write_edges(cfg: Config, nodes: List[Dict], edges: List[Dict], unresolved: List[str]) -> None:
    kind_counts = Counter(e["kind"] for e in edges)
    degree = Counter()
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    top20 = degree.most_common(20)
    id_to_name = {n["id"]: n.get("name", n["id"]) for n in nodes}
    external_count = sum(1 for n in nodes if n.get("isExternal"))

    lines = [
        f"# Edge Statistics — {cfg.app}\n",
        "## Edge Counts by Kind\n",
        "| kind | count |",
        "|------|-------|",
    ]
    for k, c in sorted(kind_counts.items()):
        lines.append(f"| `{k}` | {c} |")

    lines += [
        "\n## Top 20 Nodes by Degree\n",
        "| name | id | degree |",
        "|------|----|--------|",
    ]
    for nid, deg in top20:
        name = id_to_name.get(nid, nid)
        lines.append(f"| {name} | `{nid}` | {deg} |")

    lines.append(f"\n## External Placeholders\n\n{external_count} external nodes.\n")

    if unresolved:
        lines.append("## Unresolved References (first 50)\n")
        for uid in unresolved[:50]:
            lines.append(f"- `{uid}`")

    cfg.out("edges.md").write_text("\n".join(lines) + "\n")


def _write_routing(cfg: Config, nodes: List[Dict], edges: List[Dict]) -> None:
    # Build lookup maps
    id_to_node = {n["id"]: n for n in nodes}
    subnet_to_rt = {}
    subnet_to_nsg = {}
    nic_to_asgs: Dict[str, List[str]] = defaultdict(list)
    nsg_to_src_asgs: Dict[str, List[str]] = defaultdict(list)
    nsg_to_dst_asgs: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        if e["kind"] == "subnet->routeTable":
            subnet_to_rt[e["source"]] = e["target"]
        elif e["kind"] == "subnet->nsg":
            subnet_to_nsg[e["source"]] = e["target"]
        elif e["kind"] == "nic->asg":
            nic_to_asgs[e["source"]].append(e["target"])
        elif e["kind"] == "nsgRule->sourceAsg":
            nsg_to_src_asgs[e["source"]].append(e["target"])
        elif e["kind"] == "nsgRule->destAsg":
            nsg_to_dst_asgs[e["source"]].append(e["target"])

    rt_nodes = [n for n in nodes if n["type"] == "microsoft.network/routetables"]
    subnets = sorted(
        [n for n in nodes if "/subnets/" in n["id"]],
        key=lambda n: (n.get("name", ""), n["id"]),
    )
    subnets_with_udr = [s for s in subnets if s["id"] in subnet_to_rt]

    lines = [f"# Routing & NSG Details — {cfg.app}\n"]

    # Summary
    lines.append("## Summary\n")
    lines.append(f"- Route tables: {len(rt_nodes)}")
    lines.append(f"- Subnets with UDRs: {len(subnets_with_udr)}")
    if subnets_with_udr:
        for s in subnets_with_udr:
            lines.append(f"  - `{s['name']}`")
    lines.append("")

    # UDR section — each route table with deterministic route ordering
    lines.append("## Route Tables\n")
    if not rt_nodes:
        lines.append("_No route tables found._\n")
    else:
        for rt in sorted(rt_nodes, key=lambda n: (n.get("name", ""), n["id"])):
            lines.append(f"### Route Table: `{rt['name']}` (`{rt['id']}`)\n")
            raw_routes = (rt.get("properties") or {}).get("routes") or []
            if raw_routes:
                # Sort routes deterministically
                sorted_routes = sorted(raw_routes, key=lambda r: (
                    (r.get("properties") or {}).get("addressPrefix", ""),
                    (r.get("properties") or {}).get("nextHopType", ""),
                    (r.get("properties") or {}).get("nextHopIpAddress", ""),
                    r.get("name", ""),
                ))
                lines.append("| name | destination | nextHopType | nextHopIp |")
                lines.append("|------|-------------|-------------|-----------|")
                for r in sorted_routes:
                    rp = r.get("properties") or {}
                    lines.append(
                        f"| {r.get('name','')} "
                        f"| {rp.get('addressPrefix','?')} "
                        f"| {rp.get('nextHopType','?')} "
                        f"| {rp.get('nextHopIpAddress','')} |"
                    )
            else:
                lines.append("_No route entries._\n")
            lines.append("")

    # Subnet-to-route-table associations
    lines.append("## Subnet UDR Associations\n")
    if not subnets_with_udr:
        lines.append("_No subnets with UDRs._\n")
    else:
        for subnet in subnets_with_udr:
            rt_id = subnet_to_rt[subnet["id"]]
            rt_node = id_to_node.get(rt_id)
            rt_name = rt_node["name"] if rt_node else rt_id.split("/")[-1]
            lines.append(f"- `{subnet['name']}` → `{rt_name}` (`{rt_id}`)")
        lines.append("")

    # NSG section
    # Build ASG ID -> name lookup for resolving ASG references in NSG rules
    asg_name_map = {}
    for n in nodes:
        if n["type"] == "microsoft.network/applicationsecuritygroups":
            asg_name_map[n["id"]] = n.get("name", n["id"].split("/")[-1])

    lines.append("\n## Network Security Groups\n")
    nsg_nodes = [n for n in nodes if n["type"] == "microsoft.network/networksecuritygroups"]
    if not nsg_nodes:
        lines.append("_No NSGs found._\n")
    else:
        for nsg in sorted(nsg_nodes, key=lambda n: n["id"]):
            lines.append(f"### NSG: `{nsg['name']}` (`{nsg['id']}`)\n")
            p = nsg.get("properties") or {}
            for direction in ("inbound", "outbound"):
                rules = p.get("securityRules") or []
                direction_rules = [r for r in rules if (r.get("properties") or {}).get("direction", "").lower() == direction]
                if direction_rules:
                    lines.append(f"#### {direction.capitalize()} Rules\n")
                    lines.append("| name | priority | protocol | src | dst | action |")
                    lines.append("|------|----------|----------|-----|-----|--------|")
                    for r in sorted(direction_rules, key=lambda x: (x.get("properties") or {}).get("priority", 0)):
                        rp = r.get("properties") or {}
                        # Resolve source: prefer ASG names over address prefix
                        src_asgs = rp.get("sourceApplicationSecurityGroups") or []
                        if src_asgs:
                            src = ", ".join(
                                asg_name_map.get(a.get("id", "").lower(), a.get("id", "").split("/")[-1])
                                for a in src_asgs
                            )
                        else:
                            src = rp.get("sourceAddressPrefix", "")
                        # Resolve destination: prefer ASG names over address prefix
                        dst_asgs = rp.get("destinationApplicationSecurityGroups") or []
                        if dst_asgs:
                            dst = ", ".join(
                                asg_name_map.get(a.get("id", "").lower(), a.get("id", "").split("/")[-1])
                                for a in dst_asgs
                            )
                        else:
                            dst = rp.get("destinationAddressPrefix", "")
                        lines.append(
                            f"| {r.get('name','')} | {rp.get('priority','')} "
                            f"| {rp.get('protocol','')} "
                            f"| {src} "
                            f"| {dst} "
                            f"| {rp.get('access','')} |"
                        )

    # ASG section
    lines.append("\n## Application Security Groups\n")
    asg_nodes = sorted(
        [n for n in nodes if n["type"] == "microsoft.network/applicationsecuritygroups"],
        key=lambda n: (n.get("name", ""), n["id"]),
    )
    if not asg_nodes:
        lines.append("_No ASGs found._\n")
    else:
        lines.append(f"- Application security groups: {len(asg_nodes)}")
        # Build ASG -> NIC membership from edges
        asg_to_nics: Dict[str, List[str]] = defaultdict(list)
        for nic_id, asg_ids in nic_to_asgs.items():
            nic_node = id_to_node.get(nic_id)
            nic_name = nic_node["name"] if nic_node else nic_id.split("/")[-1]
            for asg_id in asg_ids:
                asg_to_nics[asg_id].append(nic_name)
        # Build ASG -> NSG rule references
        asg_to_nsg_rules: Dict[str, List[str]] = defaultdict(list)
        for nsg_id, asg_ids in nsg_to_src_asgs.items():
            nsg_node = id_to_node.get(nsg_id)
            nsg_name = nsg_node["name"] if nsg_node else nsg_id.split("/")[-1]
            for asg_id in asg_ids:
                asg_to_nsg_rules[asg_id].append(f"{nsg_name} (source)")
        for nsg_id, asg_ids in nsg_to_dst_asgs.items():
            nsg_node = id_to_node.get(nsg_id)
            nsg_name = nsg_node["name"] if nsg_node else nsg_id.split("/")[-1]
            for asg_id in asg_ids:
                asg_to_nsg_rules[asg_id].append(f"{nsg_name} (destination)")
        lines.append("")
        for asg in asg_nodes:
            lines.append(f"### ASG: `{asg['name']}` (`{asg['id']}`)\n")
            members = sorted(set(asg_to_nics.get(asg["id"], [])))
            if members:
                lines.append(f"- Member NICs: {', '.join(f'`{m}`' for m in members)}")
            else:
                lines.append("- Member NICs: _none discovered_")
            nsg_refs = sorted(set(asg_to_nsg_rules.get(asg["id"], [])))
            if nsg_refs:
                lines.append(f"- Referenced in NSG rules: {', '.join(nsg_refs)}")
            lines.append("")

    cfg.out("routing.md").write_text("\n".join(lines) + "\n")


def _safe_get(obj: Any, *keys) -> Any:
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


def _fmt_seed_scope(cfg: Config) -> List[str]:
    lines: List[str] = []
    if cfg.seedResourceGroups:
        lines.append(f"- Seed resource groups: {', '.join(f'`{rg}`' for rg in cfg.seedResourceGroups)}")
    if cfg.seedTags:
        tag_pairs = ", ".join(
            f"`{key}={value}`" for key, value in sorted(cfg.seedTags.items(), key=lambda item: item[0].lower())
        )
        lines.append(f"- Seed tags: {tag_pairs}")
    if cfg.seedTagKeys:
        lines.append(f"- Seed tag keys: {', '.join(f'`{key}`' for key in cfg.seedTagKeys)}")
    return lines


def _node_label(node: Dict) -> str:
    return node.get("name") or node.get("id", "").split("/")[-1] or node.get("id", "unknown")


def _node_tags(node: Dict) -> Dict[str, str]:
    tags = node.get("tags") or {}
    return {str(k).strip().lower(): str(v).strip() for k, v in tags.items() if str(v).strip()}


def _tag_group_label(node: Dict, group_by_tag: List[str]) -> str:
    if not group_by_tag:
        return ""
    tags = _node_tags(node)
    requested = [tag.strip() for tag in group_by_tag if tag and tag.strip()]
    any_requested = any(tag.lower() == "any" for tag in requested)
    candidates = requested
    if any_requested:
        candidates = ["Application", "App", "Service", "Workload", "System", "Product"]
    for candidate in candidates:
        value = tags.get(candidate.lower())
        if value:
            return f"{candidate}: {value}"
    return "Untagged"


def _app_boundary_rows(cfg: Config, nodes: List[Dict]) -> List[Tuple[str, int, int, int, int]]:
    requested_tags = list(cfg.groupByTag)
    if not requested_tags and cfg.seedTags:
        requested_tags = list(cfg.seedTags.keys())
    if not requested_tags and cfg.seedTagKeys:
        requested_tags = list(cfg.seedTagKeys)
    if not requested_tags:
        return []

    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for node in nodes:
        grouped[_tag_group_label(node, requested_tags)].append(node)

    rows: List[Tuple[str, int, int, int, int]] = []
    for label, group_nodes in grouped.items():
        rg_count = len({n.get("resourceGroup") for n in group_nodes if n.get("resourceGroup")})
        sub_count = len({n.get("subscriptionId") for n in group_nodes if n.get("subscriptionId")})
        type_count = len({n.get("type") for n in group_nodes if n.get("type")})
        rows.append((label, len(group_nodes), rg_count, sub_count, type_count))

    rows.sort(key=lambda row: (row[0] == "Untagged", -row[1], row[0].lower()))
    return rows


def _public_endpoint_rows(nodes: List[Dict], edges: List[Dict]) -> List[Tuple[str, str, str, str]]:
    node_by_id = {n["id"]: n for n in nodes}
    attached_by_pip: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    public_ip_by_id: Dict[str, str] = {
        n["id"]: ((n.get("properties") or {}).get("ipAddress") or n.get("name", ""))
        for n in nodes
        if n.get("type") == "microsoft.network/publicipaddresses"
    }
    attached_by_lb: Dict[str, List[str]] = defaultdict(list)
    attached_by_appgw: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        if edge["kind"] == "publicIp->attachment":
            attached = node_by_id.get(edge["target"])
            attached_by_pip[edge["source"]].append({
                "name": _node_label(attached) if attached else edge["target"].split("/")[-1],
                "type": attached.get("type", edge["target"]) if attached else edge["target"],
            })
        elif edge["kind"] in {"firewall->publicIp", "bastion->publicIp"}:
            src = node_by_id.get(edge["source"])
            attached_by_pip[edge["target"]].append({
                "name": _node_label(src) if src else edge["source"].split("/")[-1],
                "type": src.get("type", edge["source"]) if src else edge["source"],
            })
        elif edge["kind"] == "loadBalancer->backendNic":
            attached = node_by_id.get(edge["target"])
            attached_by_lb[edge["source"]].append(_node_label(attached) if attached else edge["target"].split("/")[-1])
        elif edge["kind"] == "appGw->backend":
            attached_by_appgw[edge["source"]].append(edge["target"])

    rows: List[Tuple[str, str, str, str]] = []
    for node in nodes:
        ntype = node.get("type", "")
        props = node.get("properties") or {}
        if ntype == "microsoft.network/publicipaddresses":
            ip_addr = props.get("ipAddress", "")
            attached = attached_by_pip.get(node["id"], [])
            if attached:
                target_desc = ", ".join(f"{item['name']} ({item['type']})" for item in attached)
            else:
                target_desc = "No attachment discovered"
            rows.append((_node_label(node), ntype, ip_addr or "_not allocated_", target_desc))
        elif ntype == "microsoft.network/loadbalancers":
            frontends = []
            for frontend in props.get("frontendIPConfigurations") or []:
                pip_id = _safe_get(frontend, "properties", "publicIPAddress", "id")
                if pip_id:
                    frontends.append(normalize_id(pip_id))
            if frontends:
                indicator = ", ".join(public_ip_by_id.get(pip_id, pip_id.split("/")[-1]) for pip_id in frontends)
                backends = sorted(set(attached_by_lb.get(node["id"], [])))
                notes = (
                    "Backends: " + ", ".join(backends)
                    if backends else "Public frontend detected; backend NICs were not resolved"
                )
                rows.append((_node_label(node), ntype, indicator, notes))
        elif ntype == "microsoft.network/applicationgateways":
            frontends = []
            for frontend in props.get("frontendIPConfigurations") or []:
                pip_id = _safe_get(frontend, "properties", "publicIPAddress", "id")
                if pip_id:
                    frontends.append(normalize_id(pip_id))
            if frontends:
                indicator = ", ".join(public_ip_by_id.get(pip_id, pip_id.split("/")[-1]) for pip_id in frontends)
                backends = sorted(set(attached_by_appgw.get(node["id"], [])))
                notes = (
                    "Backends: " + ", ".join(backends)
                    if backends else "Public frontend detected; backend targets were not resolved"
                )
                rows.append((_node_label(node), ntype, indicator, notes))
        elif ntype == "microsoft.web/sites":
            host = props.get("defaultHostName") or ""
            if host:
                rows.append((_node_label(node), ntype, host, "App Service default hostname"))
        elif ntype == "microsoft.cdn/profiles":
            endpoint_host = _safe_get(props, "endpoint", "hostName") or props.get("hostName") or props.get("originHostHeader")
            if endpoint_host:
                rows.append((_node_label(node), ntype, endpoint_host, "CDN or Front Door profile hostname"))
        elif ntype == "microsoft.network/trafficmanagerprofiles":
            fqdn = _safe_get(props, "dnsConfig", "fqdn")
            if fqdn:
                rows.append((_node_label(node), ntype, fqdn, "Traffic Manager DNS endpoint"))
        elif ntype in {
            "microsoft.storage/storageaccounts",
            "microsoft.keyvault/vaults",
            "microsoft.sql/servers",
            "microsoft.documentdb/databaseaccounts",
            "microsoft.servicebus/namespaces",
            "microsoft.eventhub/namespaces",
            "microsoft.cognitiveservices/accounts",
        }:
            public_network = (
                props.get("publicNetworkAccess")
                or _safe_get(props, "networkAcls", "defaultAction")
                or _safe_get(props, "networkRuleSet", "defaultAction")
            )
            if isinstance(public_network, str) and public_network.lower() in {"enabled", "allow"}:
                rows.append((_node_label(node), ntype, public_network, "Public network access appears enabled"))
    return sorted(rows)


def _private_endpoint_rows(nodes: List[Dict], edges: List[Dict]) -> List[Tuple[str, str, str, str]]:
    node_by_id = {n["id"]: n for n in nodes}
    subnet_by_pe: Dict[str, str] = {}
    target_by_pe: Dict[str, List[str]] = defaultdict(list)

    for edge in edges:
        if edge["kind"] == "privateEndpoint->subnet":
            subnet = node_by_id.get(edge["target"])
            subnet_by_pe[edge["source"]] = _node_label(subnet) if subnet else edge["target"].split("/")[-1]
        elif edge["kind"] == "privateEndpoint->target":
            target = node_by_id.get(edge["target"])
            target_by_pe[edge["source"]].append(
                f"{_node_label(target) if target else edge['target'].split('/')[-1]} ({target.get('type', edge['target']) if target else edge['target']})"
            )

    rows: List[Tuple[str, str, str, str]] = []
    for node in nodes:
        if node.get("type") != "microsoft.network/privateendpoints":
            continue
        props = node.get("properties") or {}
        connections = props.get("privateLinkServiceConnections") or []
        group_ids: List[str] = []
        for conn in connections:
            for group_id in _safe_get(conn, "properties", "groupIds") or []:
                if group_id:
                    group_ids.append(str(group_id))
        target_desc = ", ".join(sorted(set(target_by_pe.get(node["id"], [])))) or "Target not resolved"
        subnet_name = subnet_by_pe.get(node["id"], "Subnet not resolved")
        notes = ", ".join(sorted(set(group_ids))) if group_ids else "Private Link group not surfaced"
        rows.append((_node_label(node), subnet_name, target_desc, notes))
    return sorted(rows)


def _shared_dependency_rows(nodes: List[Dict], edges: List[Dict]) -> List[Tuple[str, str, int, int, int]]:
    node_by_id = {n["id"]: n for n in nodes}
    incoming_sources: Dict[str, List[Dict]] = defaultdict(list)
    for edge in edges:
        src = node_by_id.get(edge["source"])
        tgt = node_by_id.get(edge["target"])
        if not src or not tgt or tgt.get("isExternal"):
            continue
        incoming_sources[tgt["id"]].append(src)

    rows: List[Tuple[str, str, int, int, int]] = []
    for target_id, sources in incoming_sources.items():
        uniq_ids = {s["id"] for s in sources}
        uniq_rgs = {s.get("resourceGroup", "") for s in sources if s.get("resourceGroup")}
        uniq_subs = {s.get("subscriptionId", "") for s in sources if s.get("subscriptionId")}
        if len(uniq_rgs) < 2 and len(uniq_subs) < 2:
            continue
        target = node_by_id[target_id]
        rows.append((
            _node_label(target),
            target.get("type", ""),
            len(uniq_ids),
            len(uniq_rgs),
            len(uniq_subs),
        ))
    rows.sort(key=lambda row: (-row[4], -row[3], -row[2], row[1], row[0].lower()))
    return rows


def _shared_service_candidates(nodes: List[Dict], edges: List[Dict]) -> List[Tuple[str, str, str, int, int, str]]:
    node_by_id = {n["id"]: n for n in nodes}
    shared_type_meta = {
        "microsoft.network/virtualnetworks": ("Network", "Shared VNet or hub network candidate"),
        "microsoft.network/privatednszones": ("DNS", "Shared private DNS candidate"),
        "microsoft.operationalinsights/workspaces": ("Monitoring", "Shared Log Analytics workspace candidate"),
        "microsoft.insights/components": ("Monitoring", "Shared Application Insights candidate"),
        "microsoft.keyvault/vaults": ("Secrets", "Shared Key Vault candidate"),
        "microsoft.appconfiguration/configurationstores": ("Configuration", "Shared App Configuration candidate"),
        "microsoft.containerregistry/registries": ("Container", "Shared container registry candidate"),
    }

    incoming_sources: Dict[str, List[Dict]] = defaultdict(list)
    for edge in edges:
        src = node_by_id.get(edge["source"])
        tgt = node_by_id.get(edge["target"])
        if not src or not tgt or tgt.get("isExternal"):
            continue
        incoming_sources[tgt["id"]].append(src)

    rows: List[Tuple[str, str, str, int, int, str]] = []
    for target_id, sources in incoming_sources.items():
        target = node_by_id[target_id]
        target_type = (target.get("type") or "").lower()
        if target_type not in shared_type_meta:
            continue

        uniq_rgs = {s.get("resourceGroup", "") for s in sources if s.get("resourceGroup")}
        uniq_subs = {s.get("subscriptionId", "") for s in sources if s.get("subscriptionId")}
        if len(uniq_rgs) < 2 and len(uniq_subs) < 2:
            continue

        category, meaning = shared_type_meta[target_type]
        rows.append((
            category,
            _node_label(target),
            target_type,
            len(uniq_rgs),
            len(uniq_subs),
            meaning,
        ))

    rows.sort(key=lambda row: (-row[4], -row[3], row[0], row[2], row[1].lower()))
    return rows


def _write_migration(
    cfg: Config,
    nodes: List[Dict],
    edges: List[Dict],
    unresolved: List[str],
    inventory: List[Dict],
    rbac_present: bool,
) -> None:
    node_by_id = {n["id"]: n for n in nodes}
    types = {n.get("type", "") for n in nodes}
    subs = sorted({n.get("subscriptionId", "") for n in nodes if n.get("subscriptionId")})
    rgs = sorted({n.get("resourceGroup", "") for n in nodes if n.get("resourceGroup")})
    external_count = sum(1 for n in nodes if n.get("isExternal"))
    app_boundary_rows = _app_boundary_rows(cfg, nodes)
    cross_rg_edges = sum(
        1 for e in edges
        for src in [node_by_id.get(e["source"])]
        for tgt in [node_by_id.get(e["target"])]
        if src and tgt and src.get("resourceGroup") and tgt.get("resourceGroup") and src.get("resourceGroup") != tgt.get("resourceGroup")
    )
    cross_sub_edges = sum(
        1 for e in edges
        for src in [node_by_id.get(e["source"])]
        for tgt in [node_by_id.get(e["target"])]
        if src and tgt and src.get("subscriptionId") and tgt.get("subscriptionId") and src.get("subscriptionId") != tgt.get("subscriptionId")
    )

    public_rows = _public_endpoint_rows(nodes, edges)
    private_rows = _private_endpoint_rows(nodes, edges)
    private_endpoint_count = sum(1 for n in nodes if n.get("type") == "microsoft.network/privateendpoints")
    private_dns_count = sum(1 for item in inventory if (item.get("type") or "").lower() == "microsoft.network/privatednszones")
    shared_rows = _shared_dependency_rows(nodes, edges)
    platform_rows = _shared_service_candidates(nodes, edges)
    evidence = _edge_evidence_summary(nodes, edges)

    inventory_types = {(item.get("type") or "").lower() for item in inventory}
    has_app_insights = "microsoft.insights/components" in types
    has_log_analytics = "microsoft.operationalinsights/workspaces" in types
    has_diag_settings = "microsoft.insights/diagnosticsettings" in inventory_types
    has_identity_resources = any(
        (n.get("type") or "").lower() == "microsoft.managedidentity/userassignedidentities"
        or bool(_safe_get(n, "identity", "type"))
        or bool(_safe_get(n, "properties", "principalId"))
        or bool(_safe_get(n, "properties", "tenantId"))
        for n in nodes
    )

    lines = [
        f"# Migration Assessment — {cfg.app}",
        "",
        "Read-only assessment generated from discovered Azure resources and inferred graph relationships.",
        "",
        "## Scope",
        "",
    ]
    lines.extend(_fmt_seed_scope(cfg))
    lines += [
        f"- Subscriptions discovered: {len(subs)}",
        f"- Resource groups discovered: {len(rgs)}",
        f"- Resources in graph: {len(nodes)}",
        f"- Graph relationships: {len(edges)}",
        f"- Unresolved references: {len(unresolved)}",
        f"- External placeholder nodes: {external_count}",
        "",
        "## Application Boundary",
        "",
    ]

    if not app_boundary_rows:
        lines.append("_No tag-based application boundary summary is available. Configure `groupByTag`, `seedTags`, or `seedTagKeys` to make app grouping explicit._")
    else:
        lines += [
            "| boundary label | resources | resource groups | subscriptions | resource types |",
            "|----------------|-----------|-----------------|---------------|----------------|",
        ]
        for label, resource_count, rg_count, sub_count, type_count in app_boundary_rows[:20]:
            lines.append(f"| {label} | {resource_count} | {rg_count} | {sub_count} | {type_count} |")

    lines += [
        "",
        "## Exposure",
        "",
        "### Public-facing indicators",
        "",
    ]

    if not public_rows:
        lines.append("_No obvious public entry points detected from current ARM / ARG evidence._")
    else:
        lines += [
            "| resource | type | indicator | notes |",
            "|----------|------|-----------|-------|",
        ]
        for name, ntype, indicator, notes in public_rows:
            lines.append(f"| {name} | `{ntype}` | `{indicator}` | {notes} |")

    lines += [
        "",
        "### Private connectivity indicators",
        "",
        f"- Private endpoints discovered: {private_endpoint_count}",
        f"- Private DNS zones discovered: {private_dns_count}",
        "",
    ]

    if private_rows:
        lines += [
            "| private endpoint | subnet | target | notes |",
            "|------------------|--------|--------|-------|",
        ]
        for name, subnet_name, target_desc, notes in private_rows:
            lines.append(f"| {name} | {subnet_name} | {target_desc} | {notes} |")
        lines.append("")

    lines += [
        "## Shared Dependencies And Coupling",
        "",
        f"- Cross-resource-group edges discovered: {cross_rg_edges}",
        f"- Cross-subscription edges discovered: {cross_sub_edges}",
        "",
    ]

    if not shared_rows:
        lines.append("_No strong shared-service candidates detected from current graph evidence._")
    else:
        lines += [
            "| target | type | source resources | source RGs | source subscriptions |",
            "|--------|------|------------------|------------|----------------------|",
        ]
        for name, ntype, source_count, rg_count, sub_count in shared_rows[:20]:
            lines.append(f"| {name} | `{ntype}` | {source_count} | {rg_count} | {sub_count} |")

    lines += [
        "",
        "### Shared Platform Service Candidates",
        "",
    ]

    if not platform_rows:
        lines.append("_No obvious shared platform services were detected from current graph evidence._")
    else:
        lines += [
            "| category | target | type | source RGs | source subscriptions | migration meaning |",
            "|----------|--------|------|------------|----------------------|-------------------|",
        ]
        for category, name, ntype, rg_count, sub_count, meaning in platform_rows[:20]:
            lines.append(f"| {category} | {name} | `{ntype}` | {rg_count} | {sub_count} | {meaning} |")

    blocker_lines: List[str] = []
    if platform_rows:
        blocker_lines.append(
            f"{len(platform_rows)} shared platform service candidates may need landing-zone ownership decisions before migration waves are defined."
        )
    if cross_sub_edges:
        blocker_lines.append(
            f"{cross_sub_edges} cross-subscription relationships were discovered. Validate whether those dependencies will remain reachable after subscription realignment."
        )
    if unresolved:
        blocker_lines.append(
            f"{len(unresolved)} unresolved references remain. These can hide shared services, deleted resources, or dependencies outside the current subscription and tenant scope."
        )
    if shared_rows and not platform_rows:
        blocker_lines.append(
            "Cross-resource-group or cross-subscription coupling exists even though no known shared-platform resource types were identified. Review application boundaries and shared RG usage manually."
        )

    lines += [
        "",
        "### Migration Blockers And Unknowns",
        "",
    ]

    if blocker_lines:
        for blocker in blocker_lines:
            lines.append(f"- {blocker}")
    else:
        lines.append("_No major migration blockers were inferred from current graph structure alone._")

    lines += [
        "",
        "## Evidence And Confidence",
        "",
        "| evidence source | edge count | interpretation |",
        "|-----------------|------------|----------------|",
        f"| Configuration-derived | {evidence['config_edges']} | Relationships inferred from ARM / ARG properties and resource structure. |",
        f"| Telemetry-derived | {evidence['telemetry_edges']} | Relationships observed from logs or telemetry enrichment when available. |",
        f"| RBAC-derived | {evidence['rbac_edges']} | Access relationships derived from role assignments. |",
        f"| Edges touching external placeholders | {evidence['external_edges']} | Dependencies involving unresolved or out-of-scope resources. |",
        "",
    ]

    if evidence["telemetry_kinds"]:
        lines.append(f"- Telemetry edge kinds present: {', '.join(f'`{kind}`' for kind in sorted(evidence['telemetry_kinds']))}")
    else:
        lines.append("- No telemetry-derived relationships are present in the current graph.")

    if evidence["external_kinds"]:
        lines.append(f"- Edge kinds touching unresolved/external resources: {', '.join(f'`{kind}`' for kind in sorted(evidence['external_kinds']))}")
    else:
        lines.append("- No graph relationships currently terminate at unresolved/external placeholder nodes.")

    lines += [
        "",
        "## Visibility Gaps And Next Checks",
        "",
    ]

    advisories: List[str] = []
    if unresolved:
        advisories.append(
            f"{len(unresolved)} referenced resources could not be resolved. Next checks: confirm subscription coverage, look for cross-tenant dependencies, and verify whether the referenced resources were deleted or renamed."
        )
    if not has_app_insights:
        advisories.append(
            "No Application Insights components were discovered in scope. Runtime dependency visibility may be limited. Next checks: inspect app settings and deployment patterns for connection strings or instrumentation keys, then verify whether telemetry is sent to an out-of-scope workspace or subscription."
        )
    if not has_log_analytics:
        advisories.append(
            "No Log Analytics workspace was discovered in scope. Centralized operational evidence may be missing or outside the current seed scope. Next checks: review monitoring resource groups, shared platform subscriptions, and diagnostic destinations referenced by policy or landing-zone standards."
        )
    if not has_diag_settings:
        advisories.append(
            "No diagnostic settings resources were discovered in inventory. Next checks: confirm whether diagnostics are enabled, whether they are inherited from policy, or whether they are simply not visible with current permissions."
        )
    if not cfg.enableTelemetry:
        advisories.append(
            "Telemetry enrichment is disabled in config. Enable it only when read access to logs exists and you want additional inferred runtime relationships. Next checks: confirm whether reader access exists to Application Insights, Log Analytics, or NSG flow-log data before turning it on."
        )
    elif evidence["telemetry_edges"] == 0:
        advisories.append(
            f"Telemetry enrichment is enabled but no telemetry-derived relationships were observed in the last {cfg.telemetryLookbackDays} day(s). Next checks: verify log retention, workspace scope, and whether diagnostic pipelines are configured for the seeded application."
        )
    if cfg.includeRbac and not rbac_present:
        advisories.append(
            "RBAC collection was requested but no rbac.json was found. Next checks: re-run the RBAC stage and verify reader access to authorization resources such as role assignments at subscription and resource-group scope."
        )
    if not cfg.includeRbac:
        advisories.append(
            "RBAC collection is disabled. Role assignment visibility may be incomplete for migration planning. Next checks: review subscription, resource-group, and critical-resource role assignments separately before finalizing migration waves."
        )
    if has_identity_resources:
        advisories.append(
            "Identity-bearing resources were detected. Identity relationships remain partial without Entra visibility. Next checks: review managed identities, service principals, Key Vault access, and principal ownership in Entra ID when that access is available."
        )
    if not advisories:
        advisories.append("No major visibility gaps were detected from the available artifacts, but all relationships should still be treated as configuration-derived unless corroborated operationally.")

    for advisory in advisories:
        lines.append(f"- {advisory}")

    lines += [
        "",
        "## Interpretation Notes",
        "",
        "- This report is read-only and does not modify Azure.",
        "- Public exposure and dependency findings are based on discovered ARM / ARG configuration and graph inference.",
        "- Missing telemetry or identity visibility is reported as a gap rather than assumed away.",
        "",
    ]

    cfg.out("migration.md").write_text("\n".join(lines) + "\n")


def _edge_evidence_summary(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    node_by_id = {n["id"]: n for n in nodes}
    telemetry_kinds: Set[str] = set()
    external_kinds: Set[str] = set()
    telemetry_edges = 0
    rbac_edges = 0
    config_edges = 0
    external_edges = 0

    for edge in edges:
        kind = edge["kind"]
        src = node_by_id.get(edge["source"])
        tgt = node_by_id.get(edge["target"])
        touches_external = bool((src and src.get("isExternal")) or (tgt and tgt.get("isExternal")))

        if kind in _TELEMETRY_EDGE_KINDS:
            telemetry_edges += 1
            telemetry_kinds.add(kind)
        elif kind == "rbac_assignment":
            rbac_edges += 1
        else:
            config_edges += 1

        if touches_external:
            external_edges += 1
            external_kinds.add(kind)

    return {
        "config_edges": config_edges,
        "telemetry_edges": telemetry_edges,
        "rbac_edges": rbac_edges,
        "external_edges": external_edges,
        "telemetry_kinds": telemetry_kinds,
        "external_kinds": external_kinds,
    }


def _resource_label(node: Dict[str, Any], resource_id: str) -> str:
    name = node.get("name") or resource_id
    rtype = node.get("type") or "unknown"
    return f"{name} ({rtype})"


def _policy_assignment_label(row: Dict[str, Any]) -> str:
    return str(
        row.get("policyAssignmentName")
        or row.get("policyDefinitionName")
        or row.get("policySetDefinitionName")
        or row.get("policyAssignmentId")
        or row.get("policyDefinitionId")
        or row.get("policySetDefinitionId")
        or "Unnamed policy"
    )


def _policy_definition_label(row: Dict[str, Any]) -> str:
    return str(
        row.get("policyDefinitionName")
        or row.get("policySetDefinitionName")
        or row.get("policyDefinitionId")
        or row.get("policySetDefinitionId")
        or "Unnamed definition"
    )


def _principal_label(assignment: Dict[str, Any]) -> str:
    principal_name = str(assignment.get("principalName") or "Unknown principal")
    principal_id = str(assignment.get("principalId") or "")
    if principal_id and principal_name != principal_id:
        return f"{principal_name} ({principal_id})"
    return principal_name


def _write_policy_summary(cfg: Config, nodes: List[Dict], policy_rows: List[Dict], artifact_present: bool) -> None:
    node_by_id = {normalize_id(node.get("id") or ""): node for node in nodes if node.get("id")}
    lines = [f"# Policy Compliance Summary — {cfg.app}", ""]

    if not artifact_present:
        lines.append("_No policy.json artifact was found. Run the policy stage or enable `includePolicy` to generate this report._")
        cfg.out("policy_summary.md").write_text("\n".join(lines) + "\n")
        return

    counts = summarize_policy_rows(policy_rows)
    noncompliant_rows = [row for row in policy_rows if normalize_compliance_state(row.get("complianceState")) == "NonCompliant"]
    noncompliant_by_resource: Dict[str, List[Dict]] = defaultdict(list)
    for row in noncompliant_rows:
        resource_id = normalize_id(row.get("resourceId") or "")
        noncompliant_by_resource[resource_id].append(row)

    other_states = sum(counts.values()) - counts.get("Compliant", 0) - counts.get("NonCompliant", 0) - counts.get("Exempt", 0)
    lines += [
        "## Executive Summary",
        "",
        f"- Policy state records: {len(policy_rows)}",
        f"- Compliant: {counts.get('Compliant', 0)}",
        f"- Non-compliant: {counts.get('NonCompliant', 0)}",
        f"- Exempt: {counts.get('Exempt', 0)}",
        f"- Other states: {other_states}",
        f"- Resources with at least one non-compliant policy: {len(noncompliant_by_resource)}",
        "- Detailed views: see `policy_by_resource.md` and `policy_by_policy.md`.",
        "",
    ]

    if not noncompliant_by_resource:
        lines += [
            "## Non-Compliant Resources",
            "",
            "_No non-compliant policy records were found in the current artifact._",
        ]
        cfg.out("policy_summary.md").write_text("\n".join(lines) + "\n")
        return

    lines += [
        "## Non-Compliant Resources",
        "",
        "| resource | resource group | non-compliant policies | examples |",
        "|----------|----------------|------------------------|----------|",
    ]
    summary_rows = []
    for resource_id, rows in noncompliant_by_resource.items():
        node = node_by_id.get(resource_id, {})
        label = _resource_label(node, resource_id)
        rg = node.get("resourceGroup") or rows[0].get("resourceGroup") or ""
        examples = ", ".join(sorted({_policy_assignment_label(row) for row in rows})[:3])
        summary_rows.append((label.lower(), label, rg, len(rows), examples, resource_id, rows))
    for _, label, rg, count, examples, _resource_id, _rows in sorted(summary_rows):
        lines.append(f"| {label} | {rg} | {count} | {examples} |")

    lines += ["", "## Detail By Resource", ""]
    for _, label, _rg, _count, _examples, resource_id, rows in sorted(summary_rows):
        lines.append(f"### {label}")
        lines.append(f"- Resource ID: `{resource_id}`")
        for row in sorted(rows, key=lambda item: ((item.get("policyAssignmentName") or "").lower(), (item.get("policyDefinitionName") or "").lower())):
            assignment = _policy_assignment_label(row)
            definition = _policy_definition_label(row)
            timestamp = row.get("timestamp") or "unknown time"
            lines.append(f"- {assignment}: {definition} ({normalize_compliance_state(row.get('complianceState'))}, {timestamp})")
            if row.get("policyAssignmentId"):
                lines.append(f"  Assignment ID: `{row.get('policyAssignmentId')}`")
            if row.get("policyDefinitionId"):
                lines.append(f"  Definition ID: `{row.get('policyDefinitionId')}`")
            if row.get("policySetDefinitionId"):
                lines.append(f"  Initiative ID: `{row.get('policySetDefinitionId')}`")
        lines.append("")

    cfg.out("policy_summary.md").write_text("\n".join(lines) + "\n")


def _policy_group_key(row: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        normalize_id(row.get("policyAssignmentId") or ""),
        normalize_id(row.get("policyDefinitionId") or ""),
        (row.get("policyDefinitionReferenceId") or "").strip().lower(),
        (row.get("policyAssignmentName") or "").strip().lower(),
        (row.get("policyDefinitionName") or "").strip().lower(),
    )


def _policy_display_name(row: Dict[str, Any]) -> str:
    assignment = _policy_assignment_label(row)
    definition = _policy_definition_label(row)
    reference = row.get("policyDefinitionReferenceId") or ""
    if reference:
        return f"{assignment} -> {definition} [{reference}]"
    return f"{assignment} -> {definition}"


def _write_policy_by_resource(cfg: Config, nodes: List[Dict], policy_rows: List[Dict], artifact_present: bool) -> None:
    node_by_id = {normalize_id(node.get("id") or ""): node for node in nodes if node.get("id")}
    lines = [f"# Policy Compliance By Resource — {cfg.app}", ""]

    if not artifact_present:
        lines.append("_No policy.json artifact was found. Run the policy stage or enable `includePolicy` to generate this report._")
        cfg.out("policy_by_resource.md").write_text("\n".join(lines) + "\n")
        return

    rows_by_resource: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in policy_rows:
        rows_by_resource[normalize_id(row.get("resourceId") or "")].append(row)

    if not rows_by_resource:
        lines.append("_No policy state rows were found in the current artifact._")
        cfg.out("policy_by_resource.md").write_text("\n".join(lines) + "\n")
        return

    lines += [
        "## Resource Index",
        "",
        "| resource | resource group | compliant | non-compliant | exempt | other |",
        "|----------|----------------|-----------|---------------|--------|-------|",
    ]

    resource_sections = []
    for resource_id, rows in rows_by_resource.items():
        node = node_by_id.get(resource_id, {})
        label = _resource_label(node, resource_id)
        rg = node.get("resourceGroup") or rows[0].get("resourceGroup") or ""
        counts = summarize_policy_rows(rows)
        other = sum(counts.values()) - counts.get("Compliant", 0) - counts.get("NonCompliant", 0) - counts.get("Exempt", 0)
        resource_sections.append((label.lower(), label, rg, counts, other, resource_id, rows))

    for _, label, rg, counts, other, _resource_id, _rows in sorted(resource_sections):
        lines.append(
            f"| {label} | {rg} | {counts.get('Compliant', 0)} | {counts.get('NonCompliant', 0)} | {counts.get('Exempt', 0)} | {other} |"
        )

    lines += ["", "## Detail", ""]
    for _, label, _rg, counts, other, resource_id, rows in sorted(resource_sections):
        lines.append(f"### {label}")
        lines.append(f"- Resource ID: `{resource_id}`")
        lines.append(
            f"- States: compliant={counts.get('Compliant', 0)}, non-compliant={counts.get('NonCompliant', 0)}, exempt={counts.get('Exempt', 0)}, other={other}"
        )
        lines.append("")
        lines.append("| state | assignment | definition | timestamp |")
        lines.append("|-------|------------|------------|-----------|")
        for row in sorted(rows, key=lambda item: (normalize_compliance_state(item.get("complianceState")), (item.get("policyAssignmentName") or "").lower(), (item.get("policyDefinitionName") or "").lower())):
            lines.append(
                f"| {normalize_compliance_state(row.get('complianceState'))} | {_policy_assignment_label(row)} | {_policy_definition_label(row)} | {row.get('timestamp') or ''} |"
            )
        lines.append("")

    cfg.out("policy_by_resource.md").write_text("\n".join(lines) + "\n")


def _write_policy_by_policy(cfg: Config, nodes: List[Dict], policy_rows: List[Dict], artifact_present: bool) -> None:
    node_by_id = {normalize_id(node.get("id") or ""): node for node in nodes if node.get("id")}
    lines = [f"# Policy Compliance By Policy — {cfg.app}", ""]

    if not artifact_present:
        lines.append("_No policy.json artifact was found. Run the policy stage or enable `includePolicy` to generate this report._")
        cfg.out("policy_by_policy.md").write_text("\n".join(lines) + "\n")
        return

    rows_by_policy: Dict[Tuple[str, str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in policy_rows:
        rows_by_policy[_policy_group_key(row)].append(row)

    if not rows_by_policy:
        lines.append("_No policy state rows were found in the current artifact._")
        cfg.out("policy_by_policy.md").write_text("\n".join(lines) + "\n")
        return

    lines += [
        "## Policy Index",
        "",
        "| policy | compliant resources | non-compliant resources | exempt resources | other resources |",
        "|--------|---------------------|-------------------------|------------------|-----------------|",
    ]

    policy_sections = []
    for key, rows in rows_by_policy.items():
        sample = rows[0]
        counts = Counter()
        for row in rows:
            counts[normalize_compliance_state(row.get("complianceState"))] += 1
        other = sum(counts.values()) - counts.get("Compliant", 0) - counts.get("NonCompliant", 0) - counts.get("Exempt", 0)
        label = _policy_display_name(sample)
        policy_sections.append((label.lower(), label, counts, other, rows))

    for _, label, counts, other, _rows in sorted(policy_sections):
        lines.append(
            f"| {label} | {counts.get('Compliant', 0)} | {counts.get('NonCompliant', 0)} | {counts.get('Exempt', 0)} | {other} |"
        )

    lines += ["", "## Detail", ""]
    for _, label, counts, other, rows in sorted(policy_sections):
        sample = rows[0]
        lines.append(f"### {label}")
        if sample.get("policyAssignmentId"):
            lines.append(f"- Assignment: {_policy_assignment_label(sample)}")
            lines.append(f"- Assignment ID: `{sample.get('policyAssignmentId')}`")
        if sample.get("policyDefinitionId"):
            lines.append(f"- Definition: {_policy_definition_label(sample)}")
            lines.append(f"- Definition ID: `{sample.get('policyDefinitionId')}`")
        if sample.get("policySetDefinitionId"):
            lines.append(f"- Initiative ID: `{sample.get('policySetDefinitionId')}`")
        lines.append(
            f"- Resources: compliant={counts.get('Compliant', 0)}, non-compliant={counts.get('NonCompliant', 0)}, exempt={counts.get('Exempt', 0)}, other={other}"
        )
        lines.append("")
        lines.append("| state | resource | resource group | timestamp |")
        lines.append("|-------|----------|----------------|-----------|")
        for row in sorted(rows, key=lambda item: (normalize_compliance_state(item.get("complianceState")), normalize_id(item.get("resourceId") or ""))):
            resource_id = normalize_id(row.get("resourceId") or "")
            node = node_by_id.get(resource_id, {})
            lines.append(
                f"| {normalize_compliance_state(row.get('complianceState'))} | {_resource_label(node, resource_id)} | {node.get('resourceGroup') or row.get('resourceGroup') or ''} | {row.get('timestamp') or ''} |"
            )
        lines.append("")

    cfg.out("policy_by_policy.md").write_text("\n".join(lines) + "\n")


def _write_rbac_summary(cfg: Config, nodes: List[Dict], rbac_rows: List[Dict], artifact_present: bool) -> None:
    lines = [f"# RBAC Access Review Summary — {cfg.app}", ""]

    if not artifact_present:
        lines.append("_No rbac.json artifact was found. Run the RBAC stage or enable `includeRbac` to generate this report._")
        cfg.out("rbac_summary.md").write_text("\n".join(lines) + "\n")
        return

    simplified = simplify_rbac_rows(rbac_rows)
    access_rows = summarize_resource_access(nodes, rbac_rows)
    lines += [
        "## Executive Summary",
        "",
        f"- Role assignments captured: {len(rbac_rows)}",
        f"- Unique principals: {len({row['principalName'] for row in simplified})}",
        f"- Unique roles: {len({row['roleName'] for row in simplified})}",
        f"- Resources with effective access captured: {len(access_rows)}",
        "- Effective access counts include direct assignments and inherited assignments from parent scopes such as resource group or subscription.",
        f"- Unresolved principal display names: {sum(1 for row in simplified if row.get('principalResolutionStatus') == 'unresolved')}",
        "",
    ]

    if not access_rows:
        lines += [
            "## Access Review View",
            "",
            "_No effective RBAC assignments were matched to discovered resources._",
        ]
        cfg.out("rbac_summary.md").write_text("\n".join(lines) + "\n")
        return

    lines += [
        "## Access Review View",
        "",
        "| resource | resource group | effective assignments | distinct roles | distinct principals | inherited assignments |",
        "|----------|----------------|-----------------------|----------------|---------------------|-----------------------|",
    ]
    for row in access_rows[:25]:
        lines.append(
            f"| {row['resourceName']} ({row['resourceType']}) | {row['resourceGroup']} | {row['effectiveAssignments']} | {row['distinctRoles']} | {row['distinctPrincipals']} | {row['inheritedAssignments']} |"
        )

    lines += ["", "## Detail By Resource", ""]
    for row in access_rows[:25]:
        lines.append(f"### {row['resourceName']} ({row['resourceType']})")
        lines.append(f"- Resource ID: `{row['resourceId']}`")
        lines.append(f"- Effective assignments: {row['effectiveAssignments']}")
        lines.append(f"- Direct assignments: {row['directAssignments']}")
        lines.append(f"- Inherited assignments: {row['inheritedAssignments']}")
        for assignment in sorted(row['assignments'], key=lambda item: (item['roleName'].lower(), item['principalName'].lower(), item['scope'])):
            scope_note = "direct" if assignment['scope'] == row['resourceId'] else f"inherited from {assignment['scope']}"
            lines.append(f"- {assignment['roleName']} -> {_principal_label(assignment)} ({assignment['principalType']}; {scope_note})")
        lines.append("")

    cfg.out("rbac_summary.md").write_text("\n".join(lines) + "\n")
