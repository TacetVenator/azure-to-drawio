"""Inventory exploration helpers with pagination and lightweight filtering."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .json_preview import iter_json_array

SUPPORTED_ARTIFACTS = {
    "inventory": "inventory.json",
    "seed": "seed.json",
}


def resolve_inventory_path(output_dir: str, artifact: str) -> Path:
    key = str(artifact or "inventory").strip().lower()
    if key not in SUPPORTED_ARTIFACTS:
        raise ValueError(f"Unsupported artifact {artifact!r}. Valid: {sorted(SUPPORTED_ARTIFACTS)}")
    path = Path(output_dir) / SUPPORTED_ARTIFACTS[key]
    if not path.exists():
        raise FileNotFoundError(f"Artifact not found: {path}")
    if not path.is_file():
        raise ValueError(f"Artifact path is not a file: {path}")
    return path


def _contains_query(item: Dict[str, Any], query: str) -> bool:
    if not query:
        return True
    query_l = query.lower()
    return query_l in json.dumps(item, sort_keys=True, separators=(",", ":")).lower()


def _matches_filters(
    item: Dict[str, Any],
    *,
    query: str,
    resource_types: Optional[set[str]],
    resource_groups: Optional[set[str]],
    subscriptions: Optional[set[str]],
) -> bool:
    if resource_types and str(item.get("type", "")).lower() not in resource_types:
        return False
    if resource_groups and str(item.get("resourceGroup", "")).lower() not in resource_groups:
        return False
    if subscriptions and str(item.get("subscriptionId", "")) not in subscriptions:
        return False
    if not _contains_query(item, query):
        return False
    return True


def _shape_row(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "type": item.get("type"),
        "resourceGroup": item.get("resourceGroup"),
        "subscriptionId": item.get("subscriptionId"),
        "location": item.get("location"),
        "kind": item.get("kind"),
        "tags": item.get("tags") if isinstance(item.get("tags"), dict) else {},
    }


def _iter_rows(path: Path) -> Iterator[Dict[str, Any]]:
    for item in iter_json_array(path):
        if isinstance(item, dict):
            yield item


def query_inventory(
    output_dir: str,
    *,
    artifact: str = "inventory",
    offset: int = 0,
    limit: int = 100,
    query: str = "",
    resource_types: Optional[Iterable[str]] = None,
    resource_groups: Optional[Iterable[str]] = None,
    subscriptions: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    path = resolve_inventory_path(output_dir, artifact)
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 500))

    type_filter = {str(v).lower() for v in (resource_types or []) if str(v).strip()} or None
    rg_filter = {str(v).lower() for v in (resource_groups or []) if str(v).strip()} or None
    sub_filter = {str(v) for v in (subscriptions or []) if str(v).strip()} or None
    query_text = str(query or "").strip()

    total_rows = 0
    filtered_rows = 0
    page: List[Dict[str, Any]] = []
    index_start = offset
    index_end = offset + limit

    for item in _iter_rows(path):
        total_rows += 1
        if not _matches_filters(
            item,
            query=query_text,
            resource_types=type_filter,
            resource_groups=rg_filter,
            subscriptions=sub_filter,
        ):
            continue
        if filtered_rows >= index_start and filtered_rows < index_end:
            page.append(_shape_row(item))
        filtered_rows += 1

    return {
        "artifact": artifact,
        "artifactPath": path.name,
        "totalRows": total_rows,
        "filteredRows": filtered_rows,
        "offset": offset,
        "limit": limit,
        "rows": page,
        "hasMore": filtered_rows > index_end,
    }


def get_inventory_facets(output_dir: str, *, artifact: str = "inventory") -> Dict[str, Any]:
    """Return distinct field values for fast dropdown filters."""
    path = resolve_inventory_path(output_dir, artifact)

    types: set[str] = set()
    resource_groups: set[str] = set()
    subscriptions: set[str] = set()
    total_rows = 0

    for item in _iter_rows(path):
        total_rows += 1
        item_type = str(item.get("type", "")).strip()
        item_rg = str(item.get("resourceGroup", "")).strip()
        item_sub = str(item.get("subscriptionId", "")).strip()
        if item_type:
            types.add(item_type)
        if item_rg:
            resource_groups.add(item_rg)
        if item_sub:
            subscriptions.add(item_sub)

    return {
        "artifact": artifact,
        "artifactPath": path.name,
        "totalRows": total_rows,
        "facets": {
            "resourceTypes": sorted(types, key=str.lower),
            "resourceGroups": sorted(resource_groups, key=str.lower),
            "subscriptions": sorted(subscriptions, key=str.lower),
        },
    }
