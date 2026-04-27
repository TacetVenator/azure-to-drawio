"""Azure resource type registry helpers.

This module provides three capabilities:
1) Load the static registry (`assets/azure_type_registry.json`)
2) Enrich `resource_catalog.json` payloads with registry metadata
3) Refresh the registry by combining icon-map keys with live ARG type discovery
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .azcli import run_az_json
from .util import load_json_file

log = logging.getLogger(__name__)


# Keep this aligned with drawio._TYPE_CATEGORY_MAP where possible.
_TYPE_CATEGORY_MAP = {
    "microsoft.compute": "Compute",
    "microsoft.network": "Networking",
    "microsoft.storage": "Storage",
    "microsoft.sql": "Databases",
    "microsoft.documentdb": "Databases",
    "microsoft.dbformysql": "Databases",
    "microsoft.dbforpostgresql": "Databases",
    "microsoft.cache": "Databases",
    "microsoft.web": "Web",
    "microsoft.keyvault": "Security",
    "microsoft.authorization": "Security",
    "microsoft.managedidentity": "Identity",
    "microsoft.containerservice": "Containers",
    "microsoft.containerregistry": "Containers",
    "microsoft.app": "Containers",
    "microsoft.cognitiveservices": "AI + Machine Learning",
    "microsoft.search": "AI + Machine Learning",
    "microsoft.operationalinsights": "Monitoring",
    "microsoft.insights": "Monitoring",
    "microsoft.logic": "Integration",
    "microsoft.servicebus": "Integration",
    "microsoft.eventhub": "Integration",
}

# Common ARG types observed in real subscriptions that may not have explicit icons yet.
_SEED_EXTRA_TYPES = {
    "microsoft.authorization/policyassignments",
    "microsoft.authorization/policydefinitions",
    "microsoft.authorization/roleassignments",
    "microsoft.authorization/roledefinitions",
    "microsoft.datafactory/factories/datasets",
    "microsoft.datafactory/factories/pipelines",
    "microsoft.datafactory/factories/triggers",
    "microsoft.insights/activitylogalerts",
    "microsoft.insights/metricalerts",
    "microsoft.insights/scheduledqueryrules",
    "microsoft.keyvault/vaults/secrets",
    "microsoft.logic/workflows/runs",
    "microsoft.logic/workflows/triggers",
    "microsoft.managedidentity/userassignedidentities",
    "microsoft.network/networkmanagers/networkgroups",
    "microsoft.operationsmanagement/solutions",
    "microsoft.portal/dashboards",
    "microsoft.resources/deployments",
    "microsoft.resources/resourcegroups",
    "microsoft.security/assessments",
    "microsoft.security/locations/alerts",
    "microsoft.security/settings",
    "microsoft.sql/servers/firewallrules",
    "microsoft.storage/storageaccounts/blobservices/containers",
    "microsoft.web/sites/config",
    "microsoft.web/sites/hostnamebindings",
}


def _assets_registry_path(assets_dir: Path) -> Path:
    return assets_dir / "azure_type_registry.json"


def _normalize_resource_type(resource_type: str) -> str:
    return (resource_type or "").strip().lower()


def _infer_category(resource_type: str) -> str:
    provider = resource_type.split("/")[0] if "/" in resource_type else resource_type
    return _TYPE_CATEGORY_MAP.get(provider, provider.replace("microsoft.", "").capitalize())


def load_registry(assets_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load the type registry as {resourceType -> metadata} map."""
    registry_path = _assets_registry_path(assets_dir)
    if not registry_path.exists():
        return {}

    raw = load_json_file(
        registry_path,
        context="Azure type registry",
        expected_type=list,
        advice="Ensure assets/azure_type_registry.json is a JSON array of objects.",
    )
    result: Dict[str, Dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        resource_type = _normalize_resource_type(str(entry.get("type", "")))
        if not resource_type:
            continue
        result[resource_type] = {
            "type": resource_type,
            "category": str(entry.get("category") or _infer_category(resource_type)),
            "hasExplicitIcon": bool(entry.get("hasExplicitIcon", False)),
        }
    return result


def enrich_catalog_with_registry(
    catalog: Dict[str, Any],
    registry: Dict[str, Dict[str, Any]],
    icon_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Annotate resource catalog output with registry coverage metadata."""
    icon_map = icon_map or {}
    types_rows = catalog.get("types")
    if not isinstance(types_rows, list):
        return catalog

    discovered_types: Set[str] = set()
    discovered_known = 0
    discovered_unknown_to_registry = 0

    for row in types_rows:
        if not isinstance(row, dict):
            continue
        resource_type = _normalize_resource_type(str(row.get("type") or ""))
        if not resource_type:
            continue
        discovered_types.add(resource_type)
        reg_entry = registry.get(resource_type)
        if reg_entry:
            row["category"] = reg_entry.get("category") or row.get("category") or _infer_category(resource_type)
            row["inRegistry"] = True
            row["hasExplicitIcon"] = bool(reg_entry.get("hasExplicitIcon"))
            discovered_known += 1
        else:
            row["inRegistry"] = False
            row["hasExplicitIcon"] = resource_type in icon_map
            discovered_unknown_to_registry += 1

    registry_only_types: List[Dict[str, Any]] = []
    for resource_type in sorted(registry.keys() - discovered_types):
        entry = registry[resource_type]
        registry_only_types.append(
            {
                "type": resource_type,
                "category": entry.get("category") or _infer_category(resource_type),
                "hasExplicitIcon": bool(entry.get("hasExplicitIcon", False)),
            }
        )

    known_with_icons = sum(1 for r in registry.values() if bool(r.get("hasExplicitIcon")))
    known_without_icons = len(registry) - known_with_icons

    catalog["registry"] = {
        "knownTypeCount": len(registry),
        "knownWithExplicitIconCount": known_with_icons,
        "knownWithoutExplicitIconCount": known_without_icons,
        "discoveredKnownTypeCount": discovered_known,
        "discoveredUnknownToRegistryCount": discovered_unknown_to_registry,
        "registryOnlyTypeCount": len(registry_only_types),
    }
    catalog["registryOnlyTypes"] = registry_only_types
    return catalog


def _extract_arg_supported_types(payload: Any) -> Set[str]:
    if isinstance(payload, dict):
        candidates = payload.get("data")
        if isinstance(candidates, list):
            rows = candidates
        else:
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        return set()

    types: Set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        resource_type = _normalize_resource_type(str(row.get("type") or ""))
        if resource_type:
            types.add(resource_type)
    return types


def _query_arg_types(subscription_ids: Optional[Iterable[str]] = None) -> Set[str]:
    args = [
        "graph",
        "query",
        "-q",
        "resources | where isnotempty(type) | summarize by type | project type",
    ]
    subs = [s.strip() for s in (subscription_ids or []) if s.strip()]
    if subs:
        args.extend(["--subscriptions", *subs])
    payload = run_az_json(
        args,
        context="ARG type inventory",
        advice="Authenticate with 'az login' and ensure Microsoft.ResourceGraph is available.",
    )
    return _extract_arg_supported_types(payload)


def refresh_registry(
    *,
    assets_dir: Path,
    subscription_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Rebuild assets/azure_type_registry.json from icon map + ARG types.

    ARG discovery is best-effort; if Azure CLI is unavailable, this still writes a
    deterministic registry seeded from icon-map keys and well-known extras.
    """
    icon_map_path = assets_dir / "azure_icon_map.json"
    icon_map = load_json_file(
        icon_map_path,
        context="Azure icon map",
        expected_type=dict,
        advice="Ensure assets/azure_icon_map.json exists and is a JSON object.",
    )

    icon_types = {_normalize_resource_type(str(t)) for t in icon_map.keys() if str(t).strip()}
    arg_types: Set[str] = set()
    arg_error: Optional[str] = None
    try:
        arg_types = _query_arg_types(subscription_ids=subscription_ids)
    except Exception as exc:  # best-effort refresh
        arg_error = str(exc)
        log.warning("registry-refresh: ARG query failed; using static seed only: %s", exc)

    all_types = sorted(icon_types | _SEED_EXTRA_TYPES | arg_types)
    rows: List[Dict[str, Any]] = []
    for resource_type in all_types:
        rows.append(
            {
                "type": resource_type,
                "category": _infer_category(resource_type),
                "hasExplicitIcon": resource_type in icon_types,
            }
        )

    out_path = _assets_registry_path(assets_dir)
    out_path.write_text(json.dumps(rows, indent=2, sort_keys=False) + "\n")

    summary = {
        "path": str(out_path),
        "totalTypes": len(rows),
        "iconMappedTypes": sum(1 for row in rows if row["hasExplicitIcon"]),
        "argTypesDiscovered": len(arg_types),
        "argQueryError": arg_error,
    }
    return summary
