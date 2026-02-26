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
    for e in edges:
        if e["kind"] == "subnet->routeTable":
            subnet_to_rt[e["source"]] = e["target"]
        elif e["kind"] == "subnet->nsg":
            subnet_to_nsg[e["source"]] = e["target"]

    lines = [f"# Routing & NSG Details — {cfg.app}\n"]

    # UDR section
    lines.append("## User-Defined Routes (UDR)\n")
    subnets = [n for n in nodes if "/subnets/" in n["id"]]
    if not subnets:
        lines.append("_No subnets found._\n")
    else:
        for subnet in sorted(subnets, key=lambda n: n["id"]):
            rt_id = subnet_to_rt.get(subnet["id"])
            if not rt_id:
                continue
            rt_node = id_to_node.get(rt_id)
            lines.append(f"### Subnet: `{subnet['name']}` (`{subnet['id']}`)\n")
            lines.append(f"Route Table: `{rt_id}`\n")
            if rt_node:
                routes = (rt_node.get("properties") or {}).get("routes") or []
                if routes:
                    lines.append("| destination | nextHopType | nextHopIp |")
                    lines.append("|-------------|-------------|-----------|")
                    for r in routes:
                        rp = r.get("properties") or {}
                        lines.append(
                            f"| {rp.get('addressPrefix','?')} "
                            f"| {rp.get('nextHopType','?')} "
                            f"| {rp.get('nextHopIpAddress','')} |"
                        )
                else:
                    lines.append("_No route entries._\n")

    # NSG section
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
                        lines.append(
                            f"| {r.get('name','')} | {rp.get('priority','')} "
                            f"| {rp.get('protocol','')} "
                            f"| {rp.get('sourceAddressPrefix','')} "
                            f"| {rp.get('destinationAddressPrefix','')} "
                            f"| {rp.get('access','')} |"
                        )

    cfg.out("routing.md").write_text("\n".join(lines) + "\n")
