"""Application-aware inventory partitioning and preview helpers."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .arg import query
from .config import Config
from .docs import generate_docs
from .drawio import generate_drawio
from .inventory import generate_csv, generate_yaml
from .master_report import generate_master_report
from .util import load_json_file, normalize_id

_COMMON_APP_TAG_KEYS = ["Application", "App", "Workload", "Service"]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "application"


def _normalized_tags(tags: object) -> Dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, value in tags.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
            normalized[key.strip().lower()] = value.strip()
    return normalized


def _kusto_quote(value: str) -> str:
    return value.replace("'", "''")


def _load_rg_tag_lookup_from_artifact(cfg: Config) -> Dict[Tuple[str, str], Dict[str, str]]:
    rg_path = cfg.out("resource_groups.json")
    if not rg_path.exists():
        return {}
    rows = load_json_file(
        rg_path,
        context="Split stage resource group tag artifact",
        expected_type=list,
        advice="Fix resource_groups.json or rerun seed before split.",
    )
    lookup: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in rows:
        sub_id = str(row.get("subscriptionId") or "").strip().lower()
        rg_name = str((row.get("name") or row.get("resourceGroup") or "")).strip().lower()
        if not sub_id or not rg_name:
            continue
        lookup[(sub_id, rg_name)] = _normalized_tags(row.get("tags"))
    return lookup


def _query_rg_tag_lookup(cfg: Config, resources: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    pairs = {
        (
            str(resource.get("subscriptionId") or "").strip().lower(),
            str(resource.get("resourceGroup") or "").strip().lower(),
        )
        for resource in resources
        if resource.get("subscriptionId") and resource.get("resourceGroup")
    }
    if not pairs:
        return {}

    subs = sorted({sub for sub, _ in pairs})
    rgs = sorted({rg for _, rg in pairs})
    quoted_subs = ", ".join(f"'{_kusto_quote(sub)}'" for sub in subs)
    quoted_rgs = ", ".join(f"'{_kusto_quote(rg)}'" for rg in rgs)
    kusto = (
        "resourcecontainers "
        "| where type =~ 'microsoft.resources/subscriptions/resourcegroups' "
        f"| where subscriptionId in~ ({quoted_subs}) and name in~ ({quoted_rgs}) "
        "| project subscriptionId, name, tags"
    )

    try:
        rows = query(kusto, cfg.subscriptions, cfg.seedManagementGroups)
    except TypeError:
        rows = query(kusto, cfg.subscriptions)

    lookup: Dict[Tuple[str, str], Dict[str, str]] = {}
    for row in rows:
        sub_id = str(row.get("subscriptionId") or "").strip().lower()
        rg_name = str(row.get("name") or "").strip().lower()
        if not sub_id or not rg_name:
            continue
        pair = (sub_id, rg_name)
        if pair not in pairs:
            continue
        lookup[pair] = _normalized_tags(row.get("tags"))
    return lookup


def _resolve_rg_tag_lookup(cfg: Config, resources: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    lookup = _load_rg_tag_lookup_from_artifact(cfg)
    if lookup:
        return lookup
    return _query_rg_tag_lookup(cfg, resources)


def _tag_value(
    resource: Dict[str, Any],
    tag_keys: List[str],
    rg_tag_lookup: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> Optional[str]:
    tags = _normalized_tags(resource.get("tags"))
    for key in tag_keys:
        value = tags.get(key.lower())
        if value:
            return value
    if not rg_tag_lookup:
        return None

    pair = (
        str(resource.get("subscriptionId") or "").strip().lower(),
        str(resource.get("resourceGroup") or "").strip().lower(),
    )
    rg_tags = rg_tag_lookup.get(pair, {})
    for key in tag_keys:
        value = rg_tags.get(key.lower())
        if value:
            return value
    return None


def _matches_application(
    resource: Dict[str, Any],
    tag_keys: List[str],
    value: str,
    rg_tag_lookup: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> bool:
    tag_value = _tag_value(resource, tag_keys, rg_tag_lookup)
    return bool(tag_value and tag_value.lower() == value.lower())


def _has_other_application(
    resource: Dict[str, Any],
    tag_keys: List[str],
    value: str,
    rg_tag_lookup: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> bool:
    tag_value = _tag_value(resource, tag_keys, rg_tag_lookup)
    return bool(tag_value and tag_value.lower() != value.lower())


def _resolve_split_values(
    resources: List[Dict[str, Any]],
    tag_keys: List[str],
    configured_values: List[str],
    rg_tag_lookup: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> List[str]:
    if configured_values and any(value != "*" for value in configured_values):
        seen = set()
        ordered = []
        for value in configured_values:
            if value == "*":
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            ordered.append(value)
        return ordered

    discovered: Dict[str, str] = {}
    for resource in resources:
        value = _tag_value(resource, tag_keys, rg_tag_lookup)
        if value and value.lower() not in discovered:
            discovered[value.lower()] = value
    return [discovered[key] for key in sorted(discovered)]


def build_split_preview(cfg: Config) -> str:
    split_cfg = cfg.applicationSplit
    tag_keys = split_cfg.tagKeys or _COMMON_APP_TAG_KEYS

    inventory_path = cfg.out("inventory.json")
    seed_path = cfg.out("seed.json")
    if inventory_path.exists():
        source_path = inventory_path
        resources = load_json_file(
            inventory_path,
            context="Split preview inventory",
            expected_type=list,
            advice="Fix inventory.json or rerun the expand stage.",
        )
    elif seed_path.exists():
        source_path = seed_path
        resources = load_json_file(
            seed_path,
            context="Split preview seed inventory",
            expected_type=list,
            advice="Fix seed.json or rerun the seed stage.",
        )
    else:
        raise FileNotFoundError(
            f"Neither inventory.json nor seed.json exists under {cfg.outputDir}. Run seed or expand before split-preview."
        )

    key_counts: Counter[str] = Counter()
    value_counts: Counter[str] = Counter()
    unclassified = 0
    rg_tag_lookup: Dict[Tuple[str, str], Dict[str, str]] = {}
    if cfg.tagFallbackToResourceGroup:
        rg_tag_lookup = _resolve_rg_tag_lookup(cfg, resources)

    for resource in resources:
        tags = _normalized_tags(resource.get("tags"))
        key_counts.update(tags.keys())
        app_value = _tag_value(resource, tag_keys, rg_tag_lookup)
        if app_value:
            value_counts[app_value] += 1
        else:
            unclassified += 1

    candidate_values = _resolve_split_values(resources, tag_keys, split_cfg.values or ["*"], rg_tag_lookup)

    lines = [
        f"# Application Split Preview — {cfg.app}",
        "",
        f"Source: `{source_path}`",
        f"Resources scanned: {len(resources)}",
        f"Split tag keys: {', '.join(f'`{k}`' for k in tag_keys)}",
        f"Configured values: {', '.join(f'`{v}`' for v in (split_cfg.values or ['*']))}",
        "",
        "## Common Tag Keys",
    ]

    if key_counts:
        lines.append("| tag key | resources |")
        lines.append("|---------|-----------|")
        for key, count in key_counts.most_common(12):
            lines.append(f"| `{key}` | {count} |")
    else:
        lines.append("No tags were found in the scanned resources.")

    lines.extend([
        "",
        "## Candidate Application Values",
    ])
    if candidate_values:
        lines.append("| application | resources |")
        lines.append("|-------------|-----------|")
        for value in candidate_values:
            lines.append(f"| `{value}` | {value_counts.get(value, 0)} |")
    else:
        lines.append("No application tag values were discovered for the configured keys.")

    lines.extend([
        "",
        f"Untagged for configured keys: {unclassified}",
    ])
    return "\n".join(lines) + "\n"


def _build_adjacency(edges: Iterable[Dict[str, Any]]) -> Dict[str, Set[str]]:
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    for edge in edges:
        source = normalize_id(edge["source"])
        target = normalize_id(edge["target"])
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def _filter_rbac_entries(rbac_rows: List[Dict[str, Any]], inventory: List[Dict[str, Any]], included_ids: Set[str]) -> List[Dict[str, Any]]:
    rg_scopes = {
        normalize_id(f"/subscriptions/{r.get('subscriptionId')}/resourceGroups/{r.get('resourceGroup')}")
        for r in inventory
        if r.get("subscriptionId") and r.get("resourceGroup")
    }

    filtered = []
    for row in rbac_rows:
        scope = normalize_id(((row.get("properties") or {}).get("scope") or ""))
        if not scope:
            continue
        if scope in included_ids or scope in rg_scopes or any(rid.startswith(scope + "/") for rid in included_ids):
            filtered.append(row)
    return filtered


def _filter_policy_entries(policy_rows: List[Dict[str, Any]], included_ids: Set[str]) -> List[Dict[str, Any]]:
    filtered = []
    for row in policy_rows:
        resource_id = normalize_id(row.get("resourceId") or ((row.get("properties") or {}).get("resourceId") or ""))
        if resource_id and resource_id in included_ids:
            filtered.append(row)
    return filtered


def _project_slice(
    graph: Dict[str, Any],
    inventory: List[Dict[str, Any]],
    application_value: str,
    tag_keys: List[str],
    include_shared_dependencies: bool,
    rg_tag_lookup: Optional[Dict[Tuple[str, str], Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = graph.get("nodes", [])
    edges: List[Dict[str, Any]] = graph.get("edges", [])
    node_by_id = {normalize_id(node["id"]): node for node in nodes}

    matched_ids = {
        normalize_id(node["id"])
        for node in nodes
        if not node.get("isExternal") and _matches_application(node, tag_keys, application_value, rg_tag_lookup)
    }
    if not matched_ids:
        return None

    included_ids = set(matched_ids)
    if include_shared_dependencies:
        adjacency = _build_adjacency(edges)
        queue = deque(sorted(matched_ids))
        while queue:
            current = queue.popleft()
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in included_ids:
                    continue
                neighbor_node = node_by_id.get(neighbor)
                if neighbor_node is None:
                    continue
                if not neighbor_node.get("isExternal") and _has_other_application(neighbor_node, tag_keys, application_value, rg_tag_lookup):
                    continue
                included_ids.add(neighbor)
                queue.append(neighbor)

    projected_nodes = []
    for node_id in sorted(included_ids):
        node = dict(node_by_id[node_id])
        if node.get("isExternal"):
            node["applicationContext"] = "external"
        elif node_id in matched_ids:
            node["applicationContext"] = "direct"
        else:
            node["applicationContext"] = "shared"
        projected_nodes.append(node)

    projected_edges = [
        dict(edge)
        for edge in edges
        if normalize_id(edge["source"]) in included_ids and normalize_id(edge["target"]) in included_ids
    ]

    inventory_by_id = {normalize_id(resource["id"]): resource for resource in inventory if resource.get("id")}
    projected_inventory = [
        inventory_by_id[node_id]
        for node_id in sorted(included_ids)
        if node_id in inventory_by_id
    ]

    projected_unresolved = [
        node["id"]
        for node in projected_nodes
        if node.get("isExternal")
    ]

    direct_count = sum(1 for resource in projected_inventory if _matches_application(resource, tag_keys, application_value, rg_tag_lookup))
    shared_count = sum(1 for resource in projected_inventory if not _matches_application(resource, tag_keys, application_value, rg_tag_lookup))

    return {
        "application": application_value,
        "graph": {"nodes": projected_nodes, "edges": projected_edges},
        "inventory": projected_inventory,
        "unresolved": projected_unresolved,
        "directCount": direct_count,
        "sharedCount": shared_count,
        "externalCount": len(projected_unresolved),
    }


def run_split(cfg: Config) -> List[Dict[str, Any]]:
    split_cfg = cfg.applicationSplit
    if not split_cfg.enabled:
        raise ValueError("applicationSplit.enabled must be true to run the split stage")

    inventory = load_json_file(
        cfg.out("inventory.json"),
        context="Split stage inventory",
        expected_type=list,
        advice="Fix inventory.json or rerun the expand stage.",
    )
    graph = load_json_file(
        cfg.out("graph.json"),
        context="Split stage graph",
        expected_type=dict,
        advice="Fix graph.json or rerun the graph stage.",
    )

    rbac_rows: List[Dict[str, Any]] = []
    rbac_path = cfg.out("rbac.json")
    if rbac_path.exists():
        rbac_rows = load_json_file(
            rbac_path,
            context="Split stage RBAC artifact",
            expected_type=list,
            advice="Fix rbac.json or rerun the RBAC stage.",
        )

    policy_rows: List[Dict[str, Any]] = []
    policy_path = cfg.out("policy.json")
    if policy_path.exists():
        policy_rows = load_json_file(
            policy_path,
            context="Split stage Azure Policy artifact",
            expected_type=list,
            advice="Fix policy.json or rerun the policy stage.",
        )

    tag_keys = split_cfg.tagKeys or _COMMON_APP_TAG_KEYS
    rg_tag_lookup: Dict[Tuple[str, str], Dict[str, str]] = {}
    if cfg.tagFallbackToResourceGroup:
        rg_tag_lookup = _resolve_rg_tag_lookup(cfg, inventory)
    values = _resolve_split_values(inventory, tag_keys, split_cfg.values or ["*"], rg_tag_lookup)

    applications_root = Path(cfg.outputDir) / "applications"
    applications_root.mkdir(parents=True, exist_ok=True)

    summaries: List[Dict[str, Any]] = []
    for value in values:
        projected = _project_slice(
            graph,
            inventory,
            value,
            tag_keys,
            split_cfg.includeSharedDependencies,
            rg_tag_lookup,
        )
        if projected is None:
            continue

        slug = _slugify(value)
        slice_dir = applications_root / slug
        slice_dir.mkdir(parents=True, exist_ok=True)

        (slice_dir / "inventory.json").write_text(json.dumps(projected["inventory"], indent=2, sort_keys=True))
        (slice_dir / "unresolved.json").write_text(json.dumps(sorted(projected["unresolved"]), indent=2))
        (slice_dir / "graph.json").write_text(json.dumps(projected["graph"], indent=2, sort_keys=True))

        included_node_ids = {normalize_id(node["id"]) for node in projected["graph"]["nodes"]}

        if rbac_rows:
            filtered_rbac = _filter_rbac_entries(rbac_rows, projected["inventory"], included_node_ids)
            if filtered_rbac:
                (slice_dir / "rbac.json").write_text(json.dumps(filtered_rbac, indent=2, sort_keys=True))

        if policy_rows:
            filtered_policy = _filter_policy_entries(policy_rows, included_node_ids)
            if filtered_policy:
                (slice_dir / "policy.json").write_text(json.dumps(filtered_policy, indent=2, sort_keys=True))

        manifest = {
            "application": value,
            "slug": slug,
            "tagKeys": tag_keys,
            "directCount": projected["directCount"],
            "sharedCount": projected["sharedCount"],
            "externalCount": projected["externalCount"],
            "includeSharedDependencies": split_cfg.includeSharedDependencies,
        }
        (slice_dir / "slice.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))

        slice_cfg = replace(cfg, app=f"{cfg.app} [{value}]", outputDir=str(slice_dir))
        generate_csv(slice_cfg)
        generate_yaml(slice_cfg)
        generate_drawio(slice_cfg)
        generate_docs(slice_cfg)
        generate_master_report(slice_cfg)

        summaries.append({
            **manifest,
            "path": slice_dir.relative_to(Path(cfg.outputDir)).as_posix(),
        })

    lines = [
        f"# Application Split Report — {cfg.app}",
        "",
        f"Split tag keys: {', '.join(f'`{k}`' for k in tag_keys)}",
        f"Include shared dependencies: {split_cfg.includeSharedDependencies}",
        "",
    ]
    if summaries:
        lines.extend([
            "| application | direct | shared | external | path |",
            "|-------------|--------|--------|----------|------|",
        ])
        for summary in summaries:
            lines.append(
                f"| `{summary['application']}` | {summary['directCount']} | {summary['sharedCount']} | {summary['externalCount']} | `{summary['path']}` |"
            )
    else:
        lines.append("No application slices were produced for the configured tag rules.")

    unclassified = sum(1 for resource in inventory if not _tag_value(resource, tag_keys, rg_tag_lookup))
    lines.extend([
        "",
        f"Unclassified resources for configured keys: {unclassified}",
    ])
    (Path(cfg.outputDir) / "applications.md").write_text("\n".join(lines) + "\n")
    return summaries
