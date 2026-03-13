"""Documentation generators: catalog.md, edges.md, routing.md."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from .config import Config

log = logging.getLogger(__name__)


def generate_docs(cfg: Config) -> None:
    graph_path = cfg.out("graph.json")
    if not graph_path.exists():
        raise FileNotFoundError("graph.json not found. Run 'graph' first.")
    graph = json.loads(graph_path.read_text())
    nodes: List[Dict] = graph["nodes"]
    edges: List[Dict] = graph["edges"]

    unresolved: List[str] = []
    unresolved_path = cfg.out("unresolved.json")
    if unresolved_path.exists():
        unresolved = json.loads(unresolved_path.read_text())

    cfg.ensure_output_dir()
    _write_catalog(cfg, nodes)
    _write_edges(cfg, nodes, edges, unresolved)
    _write_routing(cfg, nodes, edges)
    log.info("Wrote catalog.md, edges.md, routing.md")


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
